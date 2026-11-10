# Contributing

Thanks for helping improve the AlterLab SDKs.

## Reporting a bug

Open an [issue](https://github.com/RapierCraftStudios/alterlab-sdks/issues) with:

- the package and version (`npm ls alterlab`, `pip show alterlab`)
- a minimal code sample
- what you expected and what happened, including the `request_id` or job ID from the error if there is one

Never paste your API key.

## Pull requests

This repository is published from AlterLab's main source tree by an automated release, so we apply accepted changes there and they come back here with the next release. Small, focused pull requests are easiest to review. Please include a test, and run the package's own test command first:

| Package | Test |
|---|---|
| `node`, `unblock-fetch/node` | `npm install && npm test` |
| `unblock-fetch/mcp` | `npm test` |
| `python`, `integrations/*` | `pip install -e '.[dev]' && pytest` (Poetry packages: `poetry install && poetry run pytest`) |
| `unblock-fetch/python` | `pip install -e . pytest && pytest` |

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
