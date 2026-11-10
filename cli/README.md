# alterlab-cli

[![npm](https://img.shields.io/npm/v/alterlab-cli?logo=npm)](https://www.npmjs.com/package/alterlab-cli) [![downloads](https://img.shields.io/npm/dm/alterlab-cli)](https://www.npmjs.com/package/alterlab-cli) [![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/RapierCraftStudios/alterlab-sdks/blob/main/LICENSE) [![source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/cli)

Run the [AlterLab](https://alterlab.io) command-line tool with `npx`, no Python setup needed.

`alterlab-cli` is a small launcher. It runs the official [`alterlab`](https://pypi.org/project/alterlab/) Python CLI through [`uvx`](https://docs.astral.sh/uv/) or, if uv is not installed, through `pipx`. Every argument is passed through unchanged.

## Quick start

```bash
npx alterlab-cli scrape https://example.com
```

Some commands need no account at all:

```bash
npx alterlab-cli md https://example.com          # page or HTML file to markdown
npx alterlab-cli robots https://example.com      # robots.txt, llms.txt and AI-crawler rules
npx alterlab-cli doctor https://example.com      # why a request to this URL is failing
```

For everything else, sign in once with a browser-approved device flow, or set `ALTERLAB_API_KEY`:

```bash
npx alterlab-cli login
export ALTERLAB_API_KEY=sk_live_...
```

## Commands

| Command | What it does |
|---|---|
| `scrape <url>` | Fetch a page and return clean content (markdown, text, HTML, JSON) |
| `fetch <url>` | Fetch directly first; use AlterLab only if the direct fetch fails |
| `search <query>` | Web search with optional full-page content |
| `extract <url>` | Structured data extraction |
| `crawl <url>` | Crawl a site |
| `map <url>` | List a site's URLs |
| `batch` | Scrape URLs read from stdin |
| `screenshot <url>` | Save a screenshot |
| `run ...` | Agent runs (beta): plan, approve, stream events, fetch results |
| `mcp` | Run a local stdio MCP server for AI agents |
| `skill install` | Install the AlterLab agent skill |
| `feedback` | Tell AlterLab what went wrong |
| `md`, `robots`, `detect`, `doctor` | Local helpers that need no account |

Run `npx alterlab-cli --help` or `npx alterlab-cli <command> --help` for every option.

## Requirements

- Node.js 18 or newer (for `npx`)
- [uv](https://docs.astral.sh/uv/) (recommended) or [pipx](https://pipx.pypa.io/)

Prefer Python directly? `pip install alterlab` installs the same `alterlab` command.

## Links

- Package: [alterlab-cli on npm](https://www.npmjs.com/package/alterlab-cli)
- Python CLI and SDK: [alterlab on PyPI](https://pypi.org/project/alterlab/)
- Source: [RapierCraftStudios/alterlab-sdks/cli](https://github.com/RapierCraftStudios/alterlab-sdks/tree/main/cli)
- Documentation: [alterlab.io/docs](https://alterlab.io/docs)
- Issues: [github.com/RapierCraftStudios/alterlab-sdks/issues](https://github.com/RapierCraftStudios/alterlab-sdks/issues)
- Get an API key: [alterlab.io/signup](https://alterlab.io/signup) (up to 5,000 free requests)

MIT licensed.
