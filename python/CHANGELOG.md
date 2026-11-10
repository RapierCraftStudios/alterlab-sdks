# Changelog

## Unreleased

- Add `research()`, `get_research()`, `cancel_research()`, `wait_for_research()`, `research_events()` and the plan methods (async and sync) for `/v1/research`.
- Add `feedback()` (async and sync) for the public agent feedback API and an `alterlab feedback` CLI.

## 2.4.4

- docs/registry copy: new PyPI summary and README opening, tier table renamed to capability names with prices from `shared/pricing.py`. No code changes.

## 2.4.3

- Widen the `httpx` requirement from `^0.25.2` (`>=0.25.2,<0.26`) to `>=0.25.2,<1.0` so
  `alterlab` installs next to modern libraries (crewai, chromadb, langchain, llama-index).
- The test suite runs against both ends of the range: httpx 0.25.2 (the locked floor) and the
  latest 0.28.x (CI matrix in `test-sdk-python`).
