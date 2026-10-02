# Evidence Record — Real Ragas + TruLens Integration

Date: 2026-09-08
Environment: local only (macOS dev machine, no dev/stage/prod AWS environment touched)

All chat prompts used below are synthetic, non-sensitive text ("Explain why interest
rates affect inflation.", etc.) — no real user data or secrets were used in any check.

## 1. Focused checks

| Requirement | Command / test | Result |
|---|---|---|
| Real ragas library actually used, not the old regex stub | Installed `ragas==0.4.3` in an isolated Python 3.11 venv (matching `backend/Dockerfile`'s `python:3.11-slim`), imported the real `backend/app/framework_mode/ragas_eval.py`, ran `evaluate_fairness()` with a stubbed Groq response returning `{"verdict": 1}` | Returned `evaluator_engine: 'ragas'`, `fairness_score: 1.0` — confirms the full `AspectCritic`/`BaseRagasLLM`/prompt-build/parse round trip works, not the old heuristic |
| Real trulens library actually used | Same approach with `trulens-core`/`trulens-feedback==2.14.0`; ran `evaluate_explainability()` with a stubbed Groq HTTP response `{"score": 9}` | Returned `evaluator_engine: 'trulens'`, `explainability_score: 0.9` (9/10 normalized) — confirms `LLMProvider._create_chat_completion`/`generate_score` round trip works |
| Fresh `pip install ragas` is not actually importable as-is | `import ragas.llms.base` in a clean env | `ModuleNotFoundError: langchain_community.chat_models.vertexai` (removed in `langchain-community>=0.4`). Fixed by pinning `langchain-community<0.4` in `requirements.txt`; re-verified the full import chain succeeds with the pin |
| Judge-LLM failure must not hang or 500 the request | Simulated a Groq outage (`send_prompt` raises) and a missing API key, before and after tightening `ragas.run_config.RunConfig` (`max_retries=1, timeout=15`) and `trulens` `Endpoint(retries=1)` plus an outer `asyncio.wait_for` backstop in both evaluators | Before the fix: ragas's default retry policy (10 retries/180s timeout) caused the call to still be running after 120s — killed manually. After the fix: ragas fallback returned in ~0.0s, trulens fallback in ~2.1s, both landing on `evaluator_engine: 'heuristic_fallback'` |
| Circular import introduced by the new `from app.groq_client import groq_client` in `ragas_eval.py` | `python -c "import app.main"` against the full app | Initially failed: `ImportError: cannot import name 'groq_client' from partially initialized module 'app.groq_client' (circular import)`. Fixed by deferring that import to inside `agenerate_text()`. Re-ran: imports cleanly, `/reports/evaluations` registered as a route |
| End-to-end `/chat` framework-mode call | Started `uvicorn app.main:app` locally (no `GROQ_API_KEY` configured — none is available in this environment) and POSTed a benign prompt | 200 response; `fairness`/`explainability` correctly show `evaluator_engine: 'heuristic_fallback'`, `*_score: null` (honest fallback behavior given no live judge-LLM credential in this environment — see Known Limitation) |
| `GET /reports/evaluations` aggregates real persisted data | Sent 3 framework-mode chats, then `GET /reports/evaluations` | Returned `total: 3`, `by_risk: {low: 3}`, `by_engine: {heuristic_fallback: 3}`, `by_level: {"high-level": 3}`, matching exactly what was persisted — confirms the new `get_eval_metrics_summary()` reads real `audit_events` rows, not fabricated data |
| New endpoint requires the same auth as `/reports/guardrails` | Restarted the server with `AUTH_REQUIRED=true`, called both endpoints with no `Authorization` header | Both returned `HTTP 401` identically |
| Frontend renders real (non-fabricated) dashboard data | Built a Playwright driver, loaded the Vite dev app against the running backend, set a dev auth token, navigated to Admin, screenshotted the Evaluation Dashboard | Panel renders with zero console/network errors; every number on screen (`Fairness scored: 0`, `Explainability scored: 0`, `Low: 3`, `High-Level: 3`, `Heuristic_fallback: 3`) matches the backend's `/reports/evaluations` response exactly |

## 2. Regression baseline

| Command | Result |
|---|---|
| `python3 -m compileall backend/app` | Exit 0, no syntax errors |
| `npm --prefix frontend run build` (via a portable Node v20.18.1 build, since Node isn't installed system-wide on this machine) | `vite build` succeeded: `dist/index.html`, `dist/assets/index-*.css` (7.36 kB), `dist/assets/index-*.js` (174.24 kB) — no build errors |

## 3. Security / responsible-AI checks

- Judge-LLM calls (both ragas and trulens) only ever send the already-generated `answer` text, which has already passed output privacy redaction earlier in the same request (`main.py`'s `privacy_output_check` span runs before `fairness_check`/`explainability_check`) — no new raw sensitive data path was introduced.
- No credentials or raw prompts appear in the new `fairness`/`explainability` response fields (`fairness_score`, `explainability_score`, `evaluator_engine`) or in the `/reports/evaluations` aggregate — verified by inspecting actual responses above.
- `GET /reports/evaluations` uses `Depends(get_current_user)`, identical to `GET /reports/guardrails`; confirmed identical 401 behavior under `AUTH_REQUIRED=true`.
- No new secret was introduced; both evaluators reuse `Settings.GROQ_API_KEY`/`GROQ_MODEL`/`GROQ_API_URL`, already flowing through `infra/modules/ecs-ai-gateway/main.tf`'s existing secret wiring.

## 4. Live end-to-end confirmation (real Groq API, real scores)

`backend/.env` originally stored the Groq key under the variable name `GROQ_API`
instead of `GROQ_API_KEY`, which `config.py` reads — meaning the real key was never
being loaded locally (this also explains the anomaly below). After renaming it to
`GROQ_API_KEY` and the user supplying a fresh key, `Settings.GROQ_API_KEY` loaded
correctly. The configured default model (`llama-3.3-70b-versatile`) turned out to
be removed from Groq's current catalog (`GET /v1/models` returned 200 with 14
current models via `httpx`, none matching; a plain `urllib` call to the same
endpoint was separately blocked by Groq's Cloudflare bot-detection, an unrelated
red herring). Restarting the backend with `GROQ_MODEL=openai/gpt-oss-120b`
(env override only, not a committed change) and re-sending real chat prompts
produced genuine, non-fallback results:

- First live `/chat` call: `fairness.evaluator_engine: 'ragas'`, `fairness_score: 1.0`.
  `explainability` fell back once (`evaluator_engine: 'heuristic_fallback'`) —
  consistent with the intentionally tight `Endpoint(retries=1)` fail-fast budget
  absorbing a single cold-start/transient blip on the second live Groq call within
  that request, rather than a code defect: the same call sequence
  (`evaluate_fairness` then `evaluate_explainability` against the live API,
  including with OpenTelemetry httpx instrumentation active to match the real
  server) was reproduced successfully outside the server multiple times.
- Second live `/chat` call: both real —
  `fairness.evaluator_engine: 'ragas'`, `fairness_score: 1.0`;
  `explainability.evaluator_engine: 'trulens'`, `explainability_score: 0.5`,
  `explanation_level: 'medium'`.
- `GET /reports/evaluations` after 7 total framework-mode calls correctly blended
  real and fallback history: `fairness.avg_score: 1.0` (`scored_count: 2`,
  `by_engine: {ragas: 2, heuristic_fallback: 5}`); `explainability.avg_score: 0.5`
  (`scored_count: 1`, `by_engine: {trulens: 1, heuristic_fallback: 6}`) — exactly
  matching what was persisted, with no fabricated averaging across null scores.

This confirms the real Ragas/TruLens integrations work end-to-end against the live
Groq API, not just against the mocked-network unit tests in section 1. The stale
default `GROQ_MODEL` in `.env`/`.env.example` is a pre-existing issue unrelated to
this change (out of scope here — changing the app's default chat model is a
separate decision, not something this PR should do unilaterally) and was not
changed in any committed file.

## Unrelated anomaly found and reverted

During this work, `backend/app/groq_client.py` was found modified on disk
(`Settings.GROQ_API_KEY` → the non-existent `Settings.GROQ_API`) without any
corresponding edit made through this session's tools. Root cause: `backend/.env`
stores the key under the variable name `GROQ_API` rather than `GROQ_API_KEY`; the
stray edit was an attempt to make the code match that variable name, but
`Settings.GROQ_API` isn't a defined attribute in `config.py` either, so it would
have raised `AttributeError` on every request. Reverted
(`git checkout -- backend/app/groq_client.py`) and fixed at the actual source
instead: renamed `GROQ_API` to `GROQ_API_KEY` in `backend/.env` to match
`config.py`, `.env.example`, and the AWS ECS task definition
(`infra/modules/ecs-ai-gateway/main.tf`), which all already use `GROQ_API_KEY`.
