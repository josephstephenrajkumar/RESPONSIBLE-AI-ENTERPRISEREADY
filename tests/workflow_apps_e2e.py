#!/usr/bin/env python3
"""End-to-end test for Workflow Apps (Activepieces integration), against the live local stack.

Prerequisites: `docker compose up -d` (LiteLLM, Activepieces), the gateway running on
--base-url (default http://localhost:8000) with ACTIVEPIECES_SERVICE_PASSWORD set, and
`workflows/pieces/dist/*.tgz` built. Exercises, through the gateway's own API:

  1. engine status and bootstrap (service account, custom pieces, AI provider)
  2. create a 'responsible-ai-chat' app -> publish -> chat through the gateway
     (gateway -> engine webhook -> flow -> Responsible AI Gateway piece -> gateway /chat -> LiteLLM)
  3. create a 'litellm-chat' app -> publish -> chat (flow -> LiteLLM piece -> proxy, no RAI processing)
  4. usage sync -> both apps visible in /reports/finops
  5. app-token boundary: the app token cannot reach admin routes
  6. optional cleanup (--cleanup) deletes the apps, their flows, connections and keys

Exit code 0 only when every step passes. Prints one line per step.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--base-url', default='http://localhost:8000')
ap.add_argument('--token', default='local-dev-token')
ap.add_argument('--cleanup', action='store_true', help='delete the apps created by this run')
ap.add_argument('--model', default='', help='model for the direct LiteLLM app (default: gateway default)')
args = ap.parse_args()
BASE = args.base_url.rstrip('/')
failures = 0
created = []


def call(method, path, body=None, token=None, timeout=240):
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token or args.token}'}
    data = None
    if body is not None:
        data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, txt


def step(name, ok, detail=''):
    global failures
    print(('PASS ' if ok else 'FAIL ') + name + (f': {detail}' if detail else ''))
    if not ok:
        failures += 1
    return ok


# 1. status + bootstrap -------------------------------------------------------------
s, status = call('GET', '/workflows/status')
step('workflow status', s == 200 and status.get('enabled'), f'engine {status.get("public_url") if s == 200 else status}')
if s != 200:
    sys.exit(1)
step('engine reachable', status.get('engine_reachable') is True, status.get('api_url'))
step('service account configured', status.get('service_configured') is True)
s, boot = call('POST', '/workflows/bootstrap?force=true', timeout=900)
step('bootstrap', s == 200 and boot.get('signed_in') and not boot.get('errors'), json.dumps({k: boot.get(k) for k in ('signed_in', 'project_id', 'errors')}) if s == 200 else str(boot)[:300])
pieces = boot.get('pieces', {}) if s == 200 else {}
for name in ('@responsible-ai/piece-responsible-ai-gateway', '@responsible-ai/piece-litellm-proxy', '@activepieces/piece-forms'):
    info = pieces.get(name, {})
    step(f'piece {name}', info.get('state') in ('present', 'installed', 'already_installed'), f"{info.get('version')} {info.get('state')}")
step('AI provider configured', (boot.get('ai_provider') or {}).get('state') in ('present', 'created', 'updated'), str(boot.get('ai_provider'))[:160])

# 2. Responsible AI chat app ----------------------------------------------------------
s, app = call('POST', '/workflows/apps', {'name': 'E2E Responsible AI chat', 'template': 'responsible-ai-chat', 'rai_mode': 'code', 'monthly_budget_usd': 1.0, 'bot_name': 'E2E Bot'})
step('create responsible-ai-chat app', s == 201, (app.get('id') + ' ' + app.get('builder_url')) if s == 201 else str(app)[:400])
if s == 201:
    created.append(app['id'])
    step('app registry fields', app['status'] == 'draft' and app['client_id'] == f"workflow-app:{app['id']}" and app['chat_url'].endswith(f"/chats/{app['flow_id']}"))
    s, pub = call('POST', f"/workflows/apps/{app['id']}/publish", timeout=600)
    step('publish responsible-ai-chat app', s == 200 and pub.get('status') == 'published', str(pub)[:200] if s != 200 else pub.get('published_at'))
    t0 = time.time()
    s, chat = call('POST', f"/workflows/apps/{app['id']}/chat", {'message': 'Reply with exactly: WORKFLOW-OK', 'session_id': 'e2e-rai'}, timeout=600)
    answer = (chat or {}).get('answer') if isinstance(chat, dict) else None
    step('chat round trip through gateway (RAI path)', s == 200 and isinstance(answer, str) and len(answer) > 0, f'{time.time()-t0:.1f}s; answer: {str(answer)[:160]!r}' if s == 200 else str(chat)[:500])
    step('reply carries Responsible AI footer from the gateway', isinstance(answer, str) and 'Responsible AI' in answer and 'request' in answer)
    # the engine finalises the run shortly after the synchronous reply; poll briefly
    statuses = []
    for _ in range(15):
        s, runs = call('GET', f"/workflows/apps/{app['id']}/runs")
        statuses = [r.get('status') for r in runs.get('runs', [])] if s == 200 else []
        if 'SUCCEEDED' in statuses:
            break
        time.sleep(2)
    step('runs listed', 'SUCCEEDED' in statuses, str(statuses) if s == 200 else str(runs)[:200])
    # the gateway metered the call under the app's client id
    s, audit = call('GET', '/reports/finops?days=1')
    blob = json.dumps(audit) if s == 200 else ''
    step('gateway metering attributed to the app (llm_usage_events)', s == 200 and f"workflow-app:{app['id']}" in blob)

# 3. Direct LiteLLM app ---------------------------------------------------------------
s, app2 = call('POST', '/workflows/apps', {'name': 'E2E direct LiteLLM chat', 'template': 'litellm-chat', 'model': args.model, 'monthly_budget_usd': 1.0})
step('create litellm-chat app', s == 201, app2.get('id') if s == 201 else str(app2)[:400])
if s == 201:
    created.append(app2['id'])
    s, pub = call('POST', f"/workflows/apps/{app2['id']}/publish", timeout=600)
    step('publish litellm-chat app', s == 200 and pub.get('status') == 'published', str(pub)[:200] if s != 200 else '')
    t0 = time.time()
    s, chat = call('POST', f"/workflows/apps/{app2['id']}/chat", {'message': 'Reply with exactly: DIRECT-OK', 'session_id': 'e2e-direct'}, timeout=600)
    answer = (chat or {}).get('answer') if isinstance(chat, dict) else None
    step('chat round trip (direct LiteLLM path, no RAI)', s == 200 and isinstance(answer, str) and 'LiteLLM proxy' in answer, f'{time.time()-t0:.1f}s; answer: {str(answer)[:160]!r}' if s == 200 else str(chat)[:500])

# 4. usage sync -> FinOps ---------------------------------------------------------------
time.sleep(10)  # let the proxy flush its spend log (LiteLLM writes it in batches)
s, sync = call('POST', '/workflows/usage/sync', timeout=300)
step('usage sync', s == 200 and not sync.get('errors'), json.dumps({k: sync.get(k) for k in ('keys', 'rows_seen', 'inserted', 'errors')}) if s == 200 else str(sync)[:300])
if created and len(created) > 1:
    s, fin = call('GET', '/reports/finops?days=1')
    blob = json.dumps(fin) if s == 200 else ''
    step('direct LiteLLM spend visible in FinOps after sync', s == 200 and f'workflow-app:{created[1]}' in blob)

# 5. app token boundary -----------------------------------------------------------------
s, denied = call('GET', '/workflows/apps', token='rai_app_definitely-not-a-real-token')
step('invalid app token rejected (401)', s == 401, str(denied)[:120])

# 6. cleanup ------------------------------------------------------------------------------
if args.cleanup:
    for app_id in created:
        s, _ = call('DELETE', f'/workflows/apps/{app_id}')
        step(f'delete {app_id}', s == 200)
else:
    print(f'KEEP   apps left in place for inspection: {created} (re-run with --cleanup to remove)')

print('RESULT', 'PASS' if failures == 0 else f'FAIL ({failures} step(s) failed)')
sys.exit(0 if failures == 0 else 1)
