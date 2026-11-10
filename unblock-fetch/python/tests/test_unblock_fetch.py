import httpx
import pytest

import unblock_fetch.client as uc
from unblock_fetch import get, is_blocked

CLOUDFLARE = "<html><head><title>Just a moment...</title></head><body>challenge-platform</body></html>"
DATADOME = "<html><body><script src='https://geo.captcha-delivery.com/c.js'></script>datadome</body></html>"
CAPTCHA = (
    "<html><body><div class='g-recaptcha'></div>Please solve the CAPTCHA</body></html>"
)
JS_SHELL = "<html><head><script src='/app.js'></script></head><body><div id='root'></div></body></html>"
REAL = (
    "<html><body><h1>Products</h1>"
    + "<p>A perfectly ordinary page of text.</p>" * 10
    + "</body></html>"
)


@pytest.mark.parametrize(
    "status,body",
    [(403, CLOUDFLARE), (503, CLOUDFLARE), (200, DATADOME), (200, CAPTCHA), (200, JS_SHELL),
     (429, ""), (200, "")],
)  # fmt: skip
def test_detects_blocks(status, body):
    assert is_blocked(status, body)


@pytest.mark.parametrize(
    "status,body", [(404, "<html><body>Not found</body></html>"), (404, ""), (500, "oops"),
                    (200, REAL), (503, "Service temporarily unavailable")],
)  # fmt: skip
def test_does_not_flag_served_or_plain_errors(status, body):
    assert not is_blocked(status, body)


class Server:
    """httpx mock transport that records every call."""

    def __init__(self, direct, trial=None, scrape=None):
        self.calls, self.direct, self.trial, self.scrape = [], direct, trial, scrape

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, dict(request.headers)))
        if request.url.host == "target.test":
            return self.direct
        if request.url.path == "/api/v1/agent/trial":
            return self.trial
        if request.url.path == "/api/v1/scrape":
            return self.scrape
        return httpx.Response(404)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))

    def api_calls(self):
        return [c for c in self.calls if c[1].startswith("/api/")]


SCRAPED = httpx.Response(200, json={"content": {"markdown": "# real page"}})
TRIAL_OK = httpx.Response(201, json={"key": "sk_trial_x"})


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    uc._trial_keys.clear()
    monkeypatch.delenv("ALTERLAB_API_KEY", raising=False)


def test_direct_success_makes_zero_api_calls(monkeypatch):
    monkeypatch.setenv("ALTERLAB_API_KEY", "k")
    s = Server(httpx.Response(200, text=REAL))
    r = get("https://target.test/", client=s.client())
    assert r.via == "direct" and r.status_code == 200 and "Products" in r.text
    assert s.api_calls() == []


def test_plain_404_does_not_fall_back():
    s = Server(httpx.Response(404, text="<html><body>Not found</body></html>"))
    r = get("https://target.test/x", client=s.client())
    assert r.via == "direct" and r.status_code == 404
    assert s.api_calls() == []


def test_blocked_with_key_uses_users_key(monkeypatch):
    monkeypatch.setenv("ALTERLAB_API_KEY", "mykey")
    s = Server(httpx.Response(403, text=CLOUDFLARE), scrape=SCRAPED)
    r = get("https://target.test/", client=s.client())
    assert r.via == "alterlab" and r.text == "# real page"
    assert [c[1] for c in s.api_calls()] == ["/api/v1/scrape"]
    assert s.api_calls()[0][2]["x-api-key"] == "mykey"
    assert (
        r.attribution["source"] == "unblock-fetch" and "unblock-fetch" in r.get_key_url
    )


def test_blocked_keyless_mints_trial_with_source_header():
    s = Server(httpx.Response(403, text=CLOUDFLARE), trial=TRIAL_OK, scrape=SCRAPED)
    r = get("https://target.test/", client=s.client())
    assert r.via == "alterlab" and r.next_action
    trial = s.api_calls()[0]
    assert trial[1] == "/api/v1/agent/trial" and trial[2][
        "x-alterlab-source"
    ].startswith("unblock-fetch/")
    assert s.api_calls()[1][2]["x-api-key"] == "sk_trial_x"


def test_over_cap_returns_original_response_with_get_key_url_and_no_scrape():
    capped = httpx.Response(
        429,
        json={
            "detail": {
                "error": "unblock_fetch_keyless_cap",
                "get_key_url": "https://alterlab.io/signup?x=1",
            }
        },
    )
    s = Server(httpx.Response(403, text=CLOUDFLARE), trial=capped, scrape=SCRAPED)
    r = get("https://target.test/", client=s.client())
    assert r.via == "direct" and r.status_code == 403 and r.text == CLOUDFLARE
    assert r.get_key_url == "https://alterlab.io/signup?x=1" and r.next_action
    assert [c[1] for c in s.api_calls()] == [
        "/api/v1/agent/trial"
    ]  # no scrape, no spend


def test_scrape_failure_returns_original_response():
    s = Server(
        httpx.Response(403, text=CLOUDFLARE), trial=TRIAL_OK, scrape=httpx.Response(500)
    )
    r = get("https://target.test/", client=s.client())
    assert r.via == "direct" and r.status_code == 403 and r.get_key_url
