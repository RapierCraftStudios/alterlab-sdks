# unblock-fetch

[![PyPI](https://img.shields.io/pypi/v/unblock-fetch?logo=pypi&logoColor=white)](https://pypi.org/project/unblock-fetch/) [![downloads](https://img.shields.io/pypi/dm/unblock-fetch)](https://pypi.org/project/unblock-fetch/) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/python)

A drop-in `requests.get` / `httpx.get` that tries the request directly first and only calls [AlterLab](https://alterlab.io) when the site refuses it: a 403 or 429, a challenge or verification page, or an empty JavaScript shell. Requests that already work never leave your machine.

## Install

```bash
pip install unblock-fetch
```

## Usage

```python
from unblock_fetch import get

r = get("https://example.com", headers={"User-Agent": "my-app/1.0"}, timeout=20)

print(r.via)          # "direct" or "alterlab"
print(r.status_code)  # origin status code
print(r.text)         # page content
```

Use `is_blocked(status_code, body)` on its own if you only want the detection.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `url` | — | URL to fetch |
| `headers` | `None` | Headers for the direct request |
| `timeout` | `20.0` | Seconds per attempt |
| `api_key` | `ALTERLAB_API_KEY` env | Your AlterLab key for the fallback |
| `base_url` | `https://api.alterlab.io` | API base URL |
| `client` | new `httpx.Client` | Reuse your own `httpx.Client` |

## How the fallback works

- A direct request that succeeds is returned as-is and never calls AlterLab. A plain 404 is returned as-is too.
- With `ALTERLAB_API_KEY` set (or `api_key=`), the fallback is billed to your account, and only successful requests are charged.
- With no key it uses a free keyless trial, capped per IP per day and by a global daily budget. Past a cap you get the original response back with `get_key_url` and `next_action`.

Get a key at [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests).

## Related

- [`unblock-fetch` for Node.js](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/node) (`npm install unblock-fetch`)
- [`alterlab`](https://pypi.org/project/alterlab/), the full Python SDK and CLI

## Links

- Package: [unblock-fetch on PyPI](https://pypi.org/project/unblock-fetch/)
- Source: [RapierCraftStudios/alterlab-sdks/unblock-fetch/python](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/unblock-fetch/python)
- Issues: [https://github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)

MIT licensed.
