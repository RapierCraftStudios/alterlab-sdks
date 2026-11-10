# AlterLab SDKs

Official client libraries and integrations for [AlterLab](https://alterlab.io), the web data API for apps and AI agents: search, read and extract the live web, with automatic fallback from a direct fetch to full browser rendering. You pay only for successful requests.

Every package here is published from this source by an automated release after each AlterLab production deploy, so the code you read is the code you install.

## Packages

| Package | Language | Install | Latest |
|---|---|---|---|
| [`alterlab`](node) | Node.js / TypeScript | `npm install alterlab` | [![npm](https://img.shields.io/npm/v/alterlab?logo=npm&label=)](https://www.npmjs.com/package/alterlab) |
| [`alterlab`](python) | Python (SDK + CLI) | `pip install alterlab` | [![PyPI](https://img.shields.io/pypi/v/alterlab?logo=pypi&logoColor=white&label=)](https://pypi.org/project/alterlab/) |
| [`alterlab-cli`](cli) | CLI via npx | `npx alterlab-cli` | [![npm](https://img.shields.io/npm/v/alterlab-cli?logo=npm&label=)](https://www.npmjs.com/package/alterlab-cli) |
| [`unblock-fetch`](unblock-fetch/node) | Node.js | `npm install unblock-fetch` | [![npm](https://img.shields.io/npm/v/unblock-fetch?logo=npm&label=)](https://www.npmjs.com/package/unblock-fetch) |
| [`unblock-fetch`](unblock-fetch/python) | Python | `pip install unblock-fetch` | [![PyPI](https://img.shields.io/pypi/v/unblock-fetch?logo=pypi&logoColor=white&label=)](https://pypi.org/project/unblock-fetch/) |
| [`unblock-fetch-mcp`](unblock-fetch/mcp) | MCP server | `npx unblock-fetch-mcp` | [![npm](https://img.shields.io/npm/v/unblock-fetch-mcp?logo=npm&label=)](https://www.npmjs.com/package/unblock-fetch-mcp) |
| [`langchain-alterlab`](integrations/langchain) | LangChain | `pip install langchain-alterlab` | [![PyPI](https://img.shields.io/pypi/v/langchain-alterlab?logo=pypi&logoColor=white&label=)](https://pypi.org/project/langchain-alterlab/) |
| [`crewai-alterlab`](integrations/crewai) | CrewAI | `pip install crewai-alterlab` | [![PyPI](https://img.shields.io/pypi/v/crewai-alterlab?logo=pypi&logoColor=white&label=)](https://pypi.org/project/crewai-alterlab/) |
| [`llama-index-readers-alterlab`](integrations/llama-index) | LlamaIndex | `pip install llama-index-readers-alterlab` | [![PyPI](https://img.shields.io/pypi/v/llama-index-readers-alterlab?logo=pypi&logoColor=white&label=)](https://pypi.org/project/llama-index-readers-alterlab/) |

Also from AlterLab:
- [AlterLab MCP server](https://github.com/RapierCraft/alterlab-mcp-server) ([`alterlab-mcp-server`](https://www.npmjs.com/package/alterlab-mcp-server)) for Claude, Cursor and other MCP clients
- [n8n community node](https://github.com/RapierCraft/n8n-nodes-alterlab) ([`n8n-nodes-alterlab`](https://www.npmjs.com/package/n8n-nodes-alterlab))

## Quick start

```typescript
import { AlterLab } from "alterlab";

const client = new AlterLab({ apiKey: process.env.ALTERLAB_API_KEY });
const result = await client.scrape({ url: "https://example.com" });
console.log(result.content);
```

```python
import asyncio
import os

from alterlab import AlterLab

async def main():
    async with AlterLab(api_key=os.environ["ALTERLAB_API_KEY"]) as client:
        result = await client.scrape("https://example.com")
        print(result["content"])

asyncio.run(main())
```

Get an API key at [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests). Documentation: [alterlab.io/docs](https://alterlab.io/docs).

## Releases and verification

- Each release is tagged here as `<package>/v<version>` on the commit it was built from.
- npm packages are published with npm trusted publishing (OIDC) from GitHub Actions, and PyPI packages with PyPI trusted publishing and attestations. No long-lived publish tokens are involved.
- Versions follow semantic versioning. A patch release ships whenever a package's code changes.

## Contributing and support

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). For account or billing questions, contact [support@alterlab.io](mailto:support@alterlab.io). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
