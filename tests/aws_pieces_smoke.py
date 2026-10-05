#!/usr/bin/env python3
"""Smoke test of the AWS pieces through the Studio API against a live gateway + engine.

Creates a blank app, creates one connection per AWS piece (task-role identity: region only), adds a
read-only step per piece and runs the engine step test. Passing means the archive is installed, the
connection validated (STS with the task role: proves credential propagation into piece execution)
and the SDK call reached AWS. Resources such as Bedrock agents, OpenSearch domains or a Quick
subscription are not required: empty lists and clear service errors are accepted as described.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--base-url', default='http://localhost:8000')
ap.add_argument('--token', default='local-dev-token')
ap.add_argument('--region', default='ap-southeast-1')
ap.add_argument('--quick-region', default='us-east-1')
ap.add_argument('--keep', action='store_true')
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
            txt = r.read().decode(); return r.status, (json.loads(txt) if txt else None)
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


PIECES = {
    'agents': ('@responsible-ai/piece-aws-bedrock-agents', 'list_agents', {}, {'region': args.region}),
    'flows': ('@responsible-ai/piece-aws-bedrock-flows', 'list_flows', {}, {'region': args.region}),
    'opensearch': ('@responsible-ai/piece-aws-opensearch', 'raw_request', {'method': 'GET', 'path': '/_cluster/health'}, {'region': args.region, 'endpoint': 'https://search-does-not-exist.example.invalid', 'service': 'es'}),
    'quick': ('@responsible-ai/piece-aws-quick', 'list_dashboards', {}, {'region': args.quick_region}),
}

for key, (name, _, _, _) in PIECES.items():
    s, meta = call('GET', f'/workflows/studio/pieces/{name}')
    step(f'{key}: piece installed on the engine', s == 200 and meta.get('version'), (meta.get('version') or str(meta)[:160]) if isinstance(meta, dict) else str(meta)[:160])
    PIECES[key] = PIECES[key] + (meta if s == 200 else {},)

s, app = call('POST', '/workflows/apps', {'name': 'AWS pieces smoke', 'template': 'blank', 'rai_mode': 'code', 'monthly_budget_usd': 0.5, 'bot_name': 'smoke'})
step('create blank app', s == 201, app.get('id') if s == 201 else str(app)[:200])
if s != 201:
    sys.exit(1)
APP = app['id']
call('POST', f'/workflows/apps/{APP}/studio/operations', {'type': 'SAVE_SAMPLE_DATA', 'request': {'stepName': 'trigger', 'payload': {'sessionId': 'smoke', 'message': 'hi', 'files': []}, 'type': 'OUTPUT'}})

parent = 'trigger'
for i, (key, (name, action, inputs, conn_props, meta)) in enumerate(PIECES.items(), start=1):
    if not meta:
        continue
    s, conn = call('POST', f'/workflows/apps/{APP}/studio/connections', {'piece_name': name, 'display_name': f'smoke {key}', 'auth_type': 'CUSTOM_AUTH', 'props': conn_props}, timeout=300)
    ok = step(f'{key}: connection validated with the task role', s in (200, 201) and conn.get('externalId'), (conn.get('externalId') or '') if s in (200, 201) else str(conn)[:300])
    if not ok:
        continue
    step_name = f'step_{i}'
    action_def = {'name': step_name, 'displayName': f'{key} {action}', 'type': 'PIECE', 'valid': True,
                  'settings': {'pieceName': name, 'pieceVersion': '~' + meta['version'], 'actionName': action,
                               'input': {'auth': f"{{{{connections['{conn['externalId']}']}}}}", **inputs},
                               'propertySettings': {k: {'type': 'MANUAL'} for k in ['auth', *inputs.keys()]},
                               'errorHandlingOptions': {'continueOnFailure': {'value': False}, 'retryOnFailure': {'value': False}}}}
    s, r = call('POST', f'/workflows/apps/{APP}/studio/operations', {'type': 'ADD_ACTION', 'request': {'parentStep': parent, 'stepLocationRelativeToParent': 'AFTER', 'action': action_def}})
    if not step(f'{key}: step added', s == 200, str(r)[:200] if s != 200 else ''):
        continue
    parent = step_name
    s, t = call('POST', f'/workflows/apps/{APP}/studio/steps/{step_name}/test', timeout=300)
    out, err = (t or {}).get('output'), (t or {}).get('error')
    err_text = json.dumps(err)[:300] if err else ''
    if key in ('agents', 'flows', 'quick'):
        listed = isinstance(out, dict) and any(isinstance(v, list) for v in out.values())
        not_subscribed = key == 'quick' and err_text and any(w in err_text for w in ('UnsupportedUserEdition', 'not signed up', 'NotSignedUp', 'subscription', 'ResourceNotFound', 'AccessDenied'))
        step(f'{key}: {action} reached AWS', s == 200 and (listed or not_subscribed), (f'output={json.dumps(out)[:160]}' if listed else f'error={err_text}') if s == 200 else str(t)[:300])
    else:
        connection_error = err_text and any(w in err_text for w in ('ENOTFOUND', 'getaddrinfo', 'fetch failed', 'ECONNREFUSED', 'certificate'))
        step(f'{key}: {action} signed and sent (bogus endpoint → connection error)', s == 200 and connection_error, f'error={err_text}' if s == 200 else str(t)[:300])

if not args.keep:
    s, _ = call('DELETE', f'/workflows/apps/{APP}')
    step('delete app', s == 200)
print('RESULT', 'PASS' if failures == 0 else f'FAIL ({failures} step(s) failed)')
sys.exit(0 if failures == 0 else 1)
