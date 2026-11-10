"""``alterlab login``: agent signup device flow with keychain key storage (#38951)."""

import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

DEFAULT_BASE_URL = "https://api.alterlab.io"
KEYRING_SERVICE = "alterlab"
KEYRING_USER = "api-key"


def _config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return Path(root) / "alterlab" / "credentials.json"


def _keyring() -> Any:
    try:
        import keyring  # type: ignore

        return keyring
    except Exception:
        return None


def store_key(api_key: str) -> str:
    """Persist the key; returns where it went ("keychain" or the file path)."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, KEYRING_USER, api_key)
            return "keychain"
        except Exception:
            pass
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
    )
    with os.fdopen(fd, "w") as fh:
        json.dump({"api_key": api_key}, fh)
    os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    return str(path)


def load_key() -> Optional[str]:
    """Key lookup order: ``ALTERLAB_API_KEY`` env, keychain, credentials file."""
    env = os.environ.get("ALTERLAB_API_KEY", "").strip()
    if env:
        return env
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(KEYRING_SERVICE, KEYRING_USER)
            if value:
                return value
        except Exception:
            pass
    try:
        return json.loads(_config_path().read_text()).get("api_key") or None
    except (OSError, ValueError):
        return None


def login(
    email: str,
    agent_name: str = "alterlab-cli",
    base_url: str = DEFAULT_BASE_URL,
    client: Optional[httpx.Client] = None,
    sleep=time.sleep,
) -> int:
    """Run the device flow. The key is stored on arrival and never printed."""
    own = client is None
    http = client or httpx.Client(
        base_url=base_url, timeout=30, headers={"User-Agent": "alterlab-cli"}
    )
    try:
        resp = http.post(
            "/api/v1/agent/signup", json={"email": email, "agent_name": agent_name}
        )
        if resp.status_code >= 400:
            print(f"alterlab: signup failed ({resp.status_code})", file=sys.stderr)
            return 1
        start: Dict[str, Any] = resp.json()
        print(
            f"Approve in your browser: {start['verification_url']}\n"
            f"Code: {start['user_code']}",
            file=sys.stderr,
        )
        deadline = time.monotonic() + int(start.get("expires_in", 600))
        interval = max(1, int(start.get("poll_interval", 5)))
        while time.monotonic() < deadline:
            sleep(interval)
            poll = http.get(f"/api/v1/agent/signup/{start['signup_id']}")
            if poll.status_code >= 400:
                print(f"alterlab: poll failed ({poll.status_code})", file=sys.stderr)
                return 1
            data = poll.json()
            state = data.get("status")
            interval = max(1, int(data.get("poll_interval", interval)))
            if state == "approved":
                key = data.get("api_key")
                if not key:
                    # The key is delivered once; a retry cannot recover it (#38902).
                    print(
                        "alterlab: approved, but the key was already delivered. "
                        "Run `alterlab login` again to get a new one.",
                        file=sys.stderr,
                    )
                    return 1
                where = store_key(key)  # persist before anything else can fail
                print(
                    f"Logged in. Key {data.get('key_prefix', '')}... saved to {where}.",
                    file=sys.stderr,
                )
                return 0
            if state in ("denied", "expired"):
                print(f"alterlab: signup {state}", file=sys.stderr)
                return 1
        print("alterlab: timed out waiting for approval", file=sys.stderr)
        return 1
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"alterlab: login failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if own:
            http.close()
