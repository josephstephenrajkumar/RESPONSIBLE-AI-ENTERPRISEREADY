# Workflows: Activepieces pieces and templates

Everything the gateway ships into the Activepieces engine lives here. Architecture, decisions and the
community-versus-enterprise matrix are in [docs/ACTIVEPIECES_INTEGRATION.md](../docs/ACTIVEPIECES_INTEGRATION.md).

```text
workflows/
  pieces/
    build.mjs                 bundles each piece like the official CLI (esbuild, cjs, inlined deps) and packs a .tgz
    package.json              build tooling + the third-party packages the framework sources need
    tsconfig.json             editor/type-check paths into the read-only Activepieces checkout
    responsible-ai-gateway/   piece: governed chat through the gateway (/chat with an app token)
    litellm-proxy/            piece: direct inference on the LiteLLM proxy with a per-app virtual key
    dist/                     build output (gitignored): <name>-<version>.tgz installed by the gateway
```

## Build

```bash
cd workflows/pieces
npm install
ACTIVEPIECES_SRC=/path/to/activepieces-main npm run build    # default: ../../../ActivateDev/activepieces-main
```

The checkout is only read. The bundler aliases `@activepieces/pieces-framework`, `pieces-common`, `core-utils`,
`core-piece-types` and `shared` to the checkout's `packages/*/src` folders, inlines every third-party dependency,
keeps class names (the engine finds the piece by `constructor.name === 'Piece'`) and writes a package with
`dependencies: {}`. Each bundle is about 360 KB.

## Install into the engine

The gateway installs `dist/*.tgz` at startup (`WORKFLOW_BOOTSTRAP_ON_STARTUP=true`) and on
`POST /workflows/bootstrap` through `POST /api/v1/pieces` (`packageType=ARCHIVE`, `scope=PLATFORM`). Bump the
`version` in a piece's `package.json` for every change: piece versions are immutable in Activepieces and flows pin
them with a tilde range.

## Templates

Flow templates are Python builders in `backend/app/workflow_templates.py` (trigger trees in the Activepieces
`IMPORT_FLOW` shape); piece versions are read from the live catalogue when an app is created.

| Template | Steps | Governance |
|---|---|---|
| `responsible-ai-chat` | Chat UI → Responsible AI Gateway `chat` → Respond on UI | full gateway pipeline |
| `litellm-chat` | Chat UI → LiteLLM Proxy `chat_completion` → Respond on UI | proxy budget and guardrails only |
| `blank` | Chat UI trigger | whatever the builder adds |

## Local run and test

```bash
docker compose up -d                                  # LiteLLM, Jaeger, Activepieces (http://localhost:8080)
cd backend && ./venv/bin/uvicorn app.main:app --port 8000   # ACTIVEPIECES_SERVICE_PASSWORD set in backend/.env
python3 tests/workflow_apps_e2e.py                    # bootstrap, create, publish, chat, usage sync
cd backend && ./venv/bin/python -m unittest tests.test_workflow_apps -v
```
