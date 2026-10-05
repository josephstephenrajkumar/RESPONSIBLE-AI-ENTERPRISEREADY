#!/usr/bin/env python3
"""End-to-end test of MCP publishing against a live gateway (local or AWS).

Publishes a workflow app as an MCP tool, then drives the MCP endpoint the way an external client
(Amazon Quick Suite, Claude, LiteLLM) does: initialize, tools/list, tools/call; checks tenant and
key boundaries; cleans up.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--base-url', default='http://localhost:8000')
ap.add_argument('--token', default='local-dev-token')
args = ap.parse_args()
BASE = args.base_url.rstrip('/')
failures = 0


def call(method, path, body=None, token=None, timeout=300, raw=False):
    headers = {'Accept': 'application/json'}
    if token is not False:
        headers['Authorization'] = f'Bearer {token or args.token}'
    data = None
    if body is not None:
        data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt and not raw else txt), dict(r.headers)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt), dict(e.headers)
        except ValueError:
            return e.code, txt, dict(e.headers)


def step(name, ok, detail=''):
    global failures
    print(('PASS ' if ok else 'FAIL ') + name + (f': {detail}' if detail else ''))
    if not ok:
        failures += 1
    return ok


def rpc(method, params=None, id_=1, token=None):
    body = {'jsonrpc': '2.0', 'id': id_, 'method': method}
    if params is not None:
        body['params'] = params
    return call('POST', '/mcp', body, token=token)


# 1. an app, published -------------------------------------------------------------------------
s, app, _ = call('POST', '/workflows/apps', {'name': 'MCP E2E chat', 'template': 'responsible-ai-chat', 'rai_mode': 'code', 'monthly_budget_usd': 1.0, 'bot_name': 'MCP Bot'})
step('create app', s == 201, app.get('id') if s == 201 else str(app)[:300])
if s != 201:
    sys.exit(1)
APP = app['id']
s, pub, _ = call('POST', f'/workflows/apps/{APP}/publish', timeout=600)
step('publish app', s == 200 and pub.get('status') == 'published', str(pub)[:200] if s != 200 else '')

# 2. publish as MCP tool, issue key ------------------------------------------------------------------
s, info, _ = call('GET', '/workflows/mcp')
step('mcp info', s == 200 and info.get('endpoint', '').endswith('/mcp'), info.get('endpoint') if s == 200 else str(info)[:200])
s, tool, _ = call('PUT', f'/workflows/mcp/tools/{APP}', {'published': True, 'tool_name': 'e2e_chat', 'description': 'E2E governed chat'})
step('publish as tool', s == 200 and tool.get('tool_name') == 'e2e_chat' and tool.get('published'), str(tool)[:200] if s != 200 else '')
s, key, _ = call('POST', '/workflows/mcp/keys', {'name': 'e2e key'})
step('issue key', s == 201 and key.get('key', '').startswith('rai_mcp_'), str(key)[:200] if s != 201 else key.get('key_id'))
KEY = key.get('key')

# 3. MCP protocol with the key --------------------------------------------------------------------------
s, init, hdrs, = rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'e2e', 'version': '1'}}, token=KEY)
step('initialize', s == 200 and init.get('result', {}).get('protocolVersion') == '2025-06-18' and 'tools' in init['result']['capabilities'], str(init)[:200] if s != 200 else init['result']['serverInfo']['name'])
s, _, _ = call('POST', '/mcp', {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, token=KEY)
step('initialized notification accepted (202)', s == 202, str(s))
s, lst, _ = rpc('tools/list', id_=2, token=KEY)
names = [t['name'] for t in lst.get('result', {}).get('tools', [])] if s == 200 else []
step('tools/list shows the tool', 'e2e_chat' in names, str(names))
s, res, _ = rpc('tools/call', {'name': 'e2e_chat', 'arguments': {'message': 'Reply with exactly: MCP-OK'}}, id_=3, token=KEY)
result = res.get('result', {}) if s == 200 else {}
text = (result.get('content') or [{}])[0].get('text', '')
step('tools/call answers through the gateway', s == 200 and not result.get('isError') and 'MCP-OK' in text, text[:80] if s == 200 else str(res)[:300])
step('fresh session id per call', str(result.get('structuredContent', {}).get('session_id', '')).startswith('mcp-'))
s, res2, _ = rpc('tools/call', {'name': 'e2e_chat', 'arguments': {'message': 'Reply with exactly: MCP-OK', 'session_id': 'e2e-session'}}, id_=4, token=KEY)
step('client session id honoured', s == 200 and res2.get('result', {}).get('structuredContent', {}).get('session_id') == 'e2e-session')
s, bad, _ = rpc('tools/call', {'name': 'does_not_exist', 'arguments': {'message': 'x'}}, id_=5, token=KEY)
step('unknown tool is an isError result', s == 200 and bad.get('result', {}).get('isError') is True)
s, meta, _ = call('GET', '/.well-known/oauth-protected-resource', token=False)
step('oauth resource metadata', s == 200 and meta.get('resource', '').endswith('/mcp'), meta.get('resource') if s == 200 else str(meta)[:100])

# 4. boundaries --------------------------------------------------------------------------------------------
s, _, h = rpc('tools/list', id_=6, token='rai_mcp_not_a_key')
step('bad key rejected with 401 + WWW-Authenticate', s == 401 and 'resource_metadata' in (h.get('WWW-Authenticate') or h.get('www-authenticate') or ''), str(s))
s, _, _ = call('POST', f'/workflows/apps/{APP}/status', {'enabled': False})
s, lst, _ = rpc('tools/list', id_=7, token=KEY)
step('disabled app hides its tool', s == 200 and 'e2e_chat' not in [t['name'] for t in lst.get('result', {}).get('tools', [])])
call('POST', f'/workflows/apps/{APP}/status', {'enabled': True})
s, _, _ = call('DELETE', f"/workflows/mcp/keys/{key.get('key_id')}")
step('revoke key', s == 200)
s, _, _ = rpc('tools/list', id_=8, token=KEY)
step('revoked key rejected (401)', s == 401, str(s))

# 5. cleanup -------------------------------------------------------------------------------------------------
s, _, _ = call('DELETE', f'/workflows/apps/{APP}')
step('delete app', s == 200)
s, info, _ = call('GET', '/workflows/mcp')
step('tool row removed with the app', s == 200 and all(t['app_id'] != APP for t in info.get('tools', [])))
print('RESULT', 'PASS' if failures == 0 else f'FAIL ({failures} step(s) failed)')
sys.exit(0 if failures == 0 else 1)
