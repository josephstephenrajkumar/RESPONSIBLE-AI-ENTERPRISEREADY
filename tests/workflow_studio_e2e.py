#!/usr/bin/env python3
"""End-to-end test of the Workflow Studio API against a live gateway (local or AWS).

Builds a Responsible AI chat app step by step through the Studio routes only, exactly as the
portal's builder does, without the engine UI:
  1. catalogue and piece metadata
  2. blank app -> trigger sample data -> add gateway chat step (app's own connection) -> add reply step
  3. step test on the chat step (engine runs it with the trigger sample)
  4. publish -> chat through the gateway -> run detail with step input/output -> versions
  5. router + loop steps can be added (WS-3 shapes) and removed
  6. cleanup
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
ap.add_argument('--keep', action='store_true', help='leave the app in place')
args = ap.parse_args()
BASE = args.base_url.rstrip('/')
failures = 0


def call(method, path, body=None, timeout=300):
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {args.token}'}
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


def op(app_id, kind, request):
    return call('POST', f'/workflows/apps/{app_id}/studio/operations', {'type': kind, 'request': request})


# 1. catalogue ------------------------------------------------------------------------
s, cat = call('GET', '/workflows/studio/pieces')
names = [p['name'] for p in cat.get('pieces', [])] if s == 200 else []
step('curated catalogue', s == 200 and '@responsible-ai/piece-responsible-ai-gateway' in names and '@activepieces/piece-forms' in names, f'{len(names)} pieces')
s, gw = call('GET', '/workflows/studio/pieces/@responsible-ai/piece-responsible-ai-gateway')
step('piece metadata', s == 200 and 'chat' in (gw.get('actions') or {}), f"actions {list((gw.get('actions') or {}).keys()) if s == 200 else gw}")
s, forms = call('GET', '/workflows/studio/pieces/@activepieces/piece-forms')
step('forms metadata', s == 200 and 'return_response' in (forms.get('actions') or {}))

# 2. blank app + steps ------------------------------------------------------------------
s, app = call('POST', '/workflows/apps', {'name': 'Studio E2E chat', 'template': 'blank', 'rai_mode': 'code', 'monthly_budget_usd': 1.0, 'bot_name': 'Studio Bot'})
step('create blank app', s == 201, app.get('id') if s == 201 else str(app)[:300])
if s != 201:
    sys.exit(1)
APP = app['id']
s, flow = call('GET', f'/workflows/apps/{APP}/studio/flow')
step('flow read (trigger only)', s == 200 and [x['name'] for x in flow['steps']] == ['trigger'], str([x['name'] for x in flow.get('steps', [])]))
gateway_conn = next((c for c in flow.get('connections', []) if c['pieceName'] == '@responsible-ai/piece-responsible-ai-gateway'), None)
step('app gateway connection visible', gateway_conn is not None, gateway_conn['externalId'] if gateway_conn else '')

s, r = op(APP, 'SAVE_SAMPLE_DATA', {'stepName': 'trigger', 'payload': {'sessionId': 'studio-e2e', 'message': 'Reply with exactly: STUDIO-OK', 'files': []}, 'type': 'OUTPUT'})
step('trigger sample data saved', s == 200, str(r)[:200] if s != 200 else '')

gw_version = '~' + gw['version']
chat_step = {
    'name': 'step_1', 'displayName': 'Chat (Responsible AI)', 'type': 'PIECE', 'valid': True,
    'settings': {'pieceName': '@responsible-ai/piece-responsible-ai-gateway', 'pieceVersion': gw_version, 'actionName': 'chat',
                 'input': {'auth': f"{{{{connections['{gateway_conn['externalId']}']}}}}", 'message': "{{trigger['output']['message']}}", 'mode': 'code', 'model': '', 'temperature': 0.2, 'maxTokens': 400, 'sessionId': "{{trigger['output']['sessionId']}}", 'agentId': f'workflow-app:{APP}'},
                 'propertySettings': {k: {'type': 'MANUAL'} for k in ('auth', 'message', 'mode', 'model', 'temperature', 'maxTokens', 'sessionId', 'agentId')},
                 'errorHandlingOptions': {'continueOnFailure': {'value': False}, 'retryOnFailure': {'value': False}}},
}
s, r = op(APP, 'ADD_ACTION', {'parentStep': 'trigger', 'stepLocationRelativeToParent': 'AFTER', 'action': chat_step})
step('add chat step', s == 200 and [x['name'] for x in r['steps']] == ['trigger', 'step_1'], str(r)[:300] if s != 200 else '')

# 3. test the chat step ---------------------------------------------------------------------
t0 = time.time()
s, test = call('POST', f'/workflows/apps/{APP}/studio/steps/step_1/test', timeout=300)
answer = ((test or {}).get('output') or {}).get('answer') if isinstance((test or {}).get('output'), dict) else None
step('step test runs the gateway chat', s == 200 and test.get('success') and isinstance(answer, str) and answer, f'{time.time()-t0:.1f}s answer={str(answer)[:60]!r}' if s == 200 else str(test)[:300])

reply_step = {
    'name': 'step_2', 'displayName': 'Respond on UI', 'type': 'PIECE', 'valid': True,
    'settings': {'pieceName': '@activepieces/piece-forms', 'pieceVersion': '~' + forms['version'], 'actionName': 'return_response',
                 'input': {'markdown': "{{step_1['output']['answer']}}\n\n---\n_built in the Studio · {{step_1['output']['metadata']['usage']['served_model']}}_"}, 'propertySettings': {'markdown': {'type': 'MANUAL'}}, 'errorHandlingOptions': {}},
}
s, r = op(APP, 'ADD_ACTION', {'parentStep': 'step_1', 'stepLocationRelativeToParent': 'AFTER', 'action': reply_step})
step('add reply step', s == 200 and [x['name'] for x in r['steps']] == ['trigger', 'step_1', 'step_2'])
s, r = op(APP, 'CHANGE_NAME', {'displayName': 'Studio E2E chat (renamed)'})
step('rename flow', s == 200 and r['version']['displayName'] == 'Studio E2E chat (renamed)')
step('draft valid', bool(r['version'].get('valid')), str(r['version'].get('valid')))

# 4. publish, chat, run detail, versions -------------------------------------------------------
s, pub = call('POST', f'/workflows/apps/{APP}/publish', timeout=600)
step('publish', s == 200 and pub.get('status') == 'published', str(pub)[:200] if s != 200 else '')
t0 = time.time()
s, chat = call('POST', f'/workflows/apps/{APP}/chat', {'message': 'Reply with exactly: STUDIO-OK', 'session_id': 'studio-e2e'}, timeout=600)
ans = (chat or {}).get('answer') if isinstance(chat, dict) else None
step('chat through the gateway', s == 200 and isinstance(ans, str) and 'built in the Studio' in ans, f'{time.time()-t0:.1f}s {str(ans)[:80]!r}' if s == 200 else str(chat)[:300])
run_id = None
for _ in range(15):
    s, runs = call('GET', f'/workflows/apps/{APP}/runs')
    done = [x for x in runs.get('runs', []) if x.get('status') == 'SUCCEEDED'] if s == 200 else []
    if done:
        run_id = done[0]['id']; break
    time.sleep(2)
step('run succeeded', run_id is not None)
if run_id:
    s, detail = call('GET', f'/workflows/apps/{APP}/runs/{run_id}')
    names_in_run = [x['name'] for x in detail.get('steps', [])] if s == 200 else []
    step('run detail has step outputs', s == 200 and 'step_1' in names_in_run and isinstance(next((x for x in detail['steps'] if x['name'] == 'step_1'), {}).get('output'), dict), str(names_in_run))
s, versions = call('GET', f'/workflows/apps/{APP}/studio/versions')
step('versions listed', s == 200 and any(v.get('state') == 'LOCKED' for v in versions.get('versions', [])), str([v.get('state') for v in versions.get('versions', [])]) if s == 200 else str(versions)[:200])

# 5. WS-3 shapes: router + loop + code can be added and removed -----------------------------------
router = {'name': 'step_3', 'displayName': 'Router', 'type': 'ROUTER', 'valid': True, 'settings': {'branches': [{'branchName': 'Short', 'branchType': 'CONDITION', 'conditions': [[{'firstValue': "{{trigger['output']['message']}}", 'secondValue': 'hi', 'operator': 'TEXT_CONTAINS', 'caseSensitive': False}]]}, {'branchName': 'Otherwise', 'branchType': 'FALLBACK'}], 'executionType': 'EXECUTE_FIRST_MATCH'}}
s, r = op(APP, 'ADD_ACTION', {'parentStep': 'step_2', 'stepLocationRelativeToParent': 'AFTER', 'action': router})
step('add router', s == 200 and any(x['name'] == 'step_3' and x['type'] == 'ROUTER' for x in r.get('steps', [])), str(r)[:300] if s != 200 else '')
code = {'name': 'step_4', 'displayName': 'Code', 'type': 'CODE', 'valid': True, 'settings': {'sourceCode': {'code': 'export const code = async (inputs) => { return { ok: true } };', 'packageJson': '{}'}, 'input': {}, 'errorHandlingOptions': {}}}
s, r = op(APP, 'ADD_ACTION', {'parentStep': 'step_3', 'stepLocationRelativeToParent': 'INSIDE_BRANCH', 'branchIndex': 0, 'action': code})
inside = next((x for x in r.get('steps', []) if x['name'] == 'step_4'), {}) if s == 200 else {}
step('add code step inside branch', s == 200 and inside.get('parent') == 'step_3' and inside.get('branch') == 0, str(r)[:300] if s != 200 else '')
loop = {'name': 'step_5', 'displayName': 'Loop', 'type': 'LOOP_ON_ITEMS', 'valid': True, 'settings': {'items': "{{trigger['output']['files']}}"}}
s, r = op(APP, 'ADD_ACTION', {'parentStep': 'step_3', 'stepLocationRelativeToParent': 'AFTER', 'action': loop})
step('add loop', s == 200 and any(x['name'] == 'step_5' and x['type'] == 'LOOP_ON_ITEMS' for x in r.get('steps', [])), str(r)[:300] if s != 200 else '')
s, r = op(APP, 'DELETE_ACTION', {'names': ['step_3', 'step_5']})
step('delete router and loop', s == 200 and [x['name'] for x in r['steps']] == ['trigger', 'step_1', 'step_2'], str([x['name'] for x in r.get('steps', [])]) if s == 200 else str(r)[:200])
s, r = op(APP, 'LOCK_AND_PUBLISH', {})
step('publish is not a studio operation (400)', s == 400)

# 6. cleanup -----------------------------------------------------------------------------------------
if not args.keep:
    s, _ = call('DELETE', f'/workflows/apps/{APP}')
    step('delete app', s == 200)
else:
    print(f'KEEP   app {APP} left in place')
print('RESULT', 'PASS' if failures == 0 else f'FAIL ({failures} step(s) failed)')
sys.exit(0 if failures == 0 else 1)
