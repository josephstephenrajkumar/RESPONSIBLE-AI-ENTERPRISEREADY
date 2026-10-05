"""MCP server: keys, tool publishing and the JSON-RPC endpoint, with a fake engine."""
import asyncio
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', f"sqlite:///{os.path.join(tempfile.gettempdir(), 'rai-mcp-tests.db')}")
os.environ.setdefault('AUTH_REQUIRED', 'false')
os.environ.setdefault('ACTIVEPIECES_ENABLED', 'true')

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app import mcp_server, workflow_apps, workflow_tokens  # noqa: E402
from app.auth import AuthenticatedUser  # noqa: E402
from app.database import SessionLocal  # noqa: E402

from test_workflow_studio import FakeActivepieces, StudioBase, admin_user, run  # noqa: E402


def make_request(headers=None, body=b'{}'):
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    hdrs.append((b'content-length', str(len(body)).encode()))
    scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'headers': hdrs, 'scheme': 'http', 'server': ('testserver', 80), 'query_string': b''}
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return Request(scope, receive)


def other_user():
    return AuthenticatedUser(user_id='u2', email='other@example.com', username='other', tenant_id='tenant-b', groups=('admin',), claims={})


class McpBase(StudioBase):
    def setUp(self):
        super().setUp()
        mcp_server.ensure_tables()
        with SessionLocal() as session:
            session.query(mcp_server.McpTool).delete(); session.query(mcp_server.McpKey).delete(); session.commit()
        # publish the app on the engine side (status) so the tool is visible
        with SessionLocal() as session:
            row = session.get(workflow_apps.WorkflowApp, self.app['id']); row.status = 'published'; session.commit()


class KeyTests(McpBase):
    def test_issue_authenticate_revoke(self):
        issued = mcp_server.issue_key('Quick integration', 'default', 'admin@example.com')
        self.assertTrue(issued['key'].startswith('rai_mcp_'))
        self.assertEqual(mcp_server.authenticate_key(issued['key'])['tenant_id'], 'default')
        self.assertIsNone(mcp_server.authenticate_key('rai_mcp_nope'))
        self.assertTrue(mcp_server.revoke_key(issued['key_id'], 'default'))
        self.assertIsNone(mcp_server.authenticate_key(issued['key']))
        self.assertFalse(mcp_server.revoke_key(issued['key_id'], 'default'))
        keys = mcp_server.list_keys('default')
        self.assertEqual(keys[0]['key_id'], issued['key_id']); self.assertTrue(keys[0]['revoked'])

    def test_key_from_other_tenant_cannot_revoke(self):
        issued = mcp_server.issue_key('k', 'default', 'a')
        self.assertFalse(mcp_server.revoke_key(issued['key_id'], 'tenant-b'))


class ToolTests(McpBase):
    def test_publish_tool_defaults_and_validation(self):
        out = mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True), admin_user())
        self.assertEqual(out['tool_name'], 'studio_app'); self.assertTrue(out['published'])
        out = mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True, tool_name='Week Planner!', description='Plans weeks'), admin_user())
        self.assertEqual(out['tool_name'], 'week_planner'); self.assertEqual(out['description'], 'Plans weeks')
        with self.assertRaises(HTTPException) as ctx:
            mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True), other_user())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_tool_name_clash_rejected(self):
        second = run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='Second', template='blank'), admin_user()))
        mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True, tool_name='shared'), admin_user())
        with self.assertRaises(HTTPException) as ctx:
            mcp_server.mcp_update_tool(second['id'], mcp_server.ToolUpdate(published=True, tool_name='shared'), admin_user())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unpublished_app_not_listed(self):
        mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True), admin_user())
        with SessionLocal() as session:
            row = session.get(workflow_apps.WorkflowApp, self.app['id']); row.status = 'draft'; session.commit()
        self.assertEqual(mcp_server.published_tools('default'), [])


class RpcTests(McpBase):
    def principal(self):
        return mcp_server.McpPrincipal(tenant_id=admin_user().tenant_id, subject='test', via='mcp-key')

    def test_initialize_negotiates_version(self):
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}}))
        self.assertEqual(res['result']['protocolVersion'], '2025-03-26')
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {'protocolVersion': '1999-01-01'}}))
        self.assertEqual(res['result']['protocolVersion'], mcp_server.PROTOCOL_VERSIONS[0])
        self.assertIn('tools', res['result']['capabilities'])

    def test_notifications_have_no_response(self):
        self.assertIsNone(run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'method': 'notifications/initialized'})))

    def test_tools_list_and_call(self):
        mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True, tool_name='planner', description='Plans'), admin_user())
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}))
        tools = res['result']['tools']
        self.assertEqual([t['name'] for t in tools], ['planner']); self.assertEqual(tools[0]['inputSchema']['required'], ['message'])
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'planner', 'arguments': {'message': 'plan my week', 'session_id': 's1'}}}))
        self.assertFalse(res['result']['isError']); self.assertEqual(res['result']['content'][0]['text'], 'echo: plan my week')
        self.assertEqual(res['result']['structuredContent']['session_id'], 's1')
        self.assertEqual(self.ap.calls[-1], ('chat', f"flow_{self.app['id']}", 's1', 'plan my week'))

    def test_tenant_isolation_and_errors(self):
        mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True, tool_name='planner'), admin_user())
        other = mcp_server.McpPrincipal(tenant_id='tenant-b', subject='x', via='mcp-key')
        res = run(mcp_server.handle_message(other, {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/list'}))
        self.assertEqual(res['result']['tools'], [])
        res = run(mcp_server.handle_message(other, {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {'name': 'planner', 'arguments': {'message': 'hi'}}}))
        self.assertTrue(res['result']['isError'])
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': 'planner', 'arguments': {}}}))
        self.assertTrue(res['result']['isError'])
        res = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 8, 'method': 'nope'}))
        self.assertEqual(res['error']['code'], -32601)

    def test_principal_from_key_and_unauthorized(self):
        issued = mcp_server.issue_key('k', 'default', 'a')
        principal = run(mcp_server.mcp_principal(make_request({'Authorization': f"Bearer {issued['key']}"})))
        self.assertEqual(principal.tenant_id, 'default'); self.assertEqual(principal.via, 'mcp-key')
        with self.assertRaises(HTTPException) as ctx:
            run(mcp_server.mcp_principal(make_request({'Authorization': 'Bearer rai_mcp_bad'})))
        self.assertEqual(ctx.exception.status_code, 401); self.assertIn('resource_metadata', ctx.exception.headers['WWW-Authenticate'])


class HardeningTests(McpBase):
    def principal(self):
        return mcp_server.McpPrincipal(tenant_id=admin_user().tenant_id, subject='test', via='mcp-key')

    def test_session_default_is_fresh_per_call(self):
        mcp_server.mcp_update_tool(self.app['id'], mcp_server.ToolUpdate(published=True, tool_name='planner'), admin_user())
        first = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'planner', 'arguments': {'message': 'a'}}}))
        second = run(mcp_server.handle_message(self.principal(), {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'planner', 'arguments': {'message': 'b'}}}))
        s1, s2 = first['result']['structuredContent']['session_id'], second['result']['structuredContent']['session_id']
        self.assertNotEqual(s1, s2); self.assertTrue(s1.startswith('mcp-'))

    def test_workflow_app_token_rejected(self):
        token = workflow_tokens.issue_token(self.app['id'], admin_user().tenant_id)
        with self.assertRaises(HTTPException) as ctx:
            run(mcp_server.mcp_principal(make_request({'Authorization': f'Bearer {token}'})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_body_cap_and_batch_cap(self):
        big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"pad":"' + b'x' * (mcp_server.MAX_BODY_BYTES + 10) + b'"}}'
        res = run(mcp_server.mcp_post(make_request({}, big), self.principal()))
        self.assertEqual(res.status_code, 413)
        batch = ('[' + ','.join('{"jsonrpc":"2.0","id":%d,"method":"ping"}' % i for i in range(mcp_server.MAX_BATCH + 1)) + ']').encode()
        res = run(mcp_server.mcp_post(make_request({}, batch), self.principal()))
        self.assertEqual(res.status_code, 400)
        ok = run(mcp_server.mcp_post(make_request({'MCP-Protocol-Version': '2025-03-26'}, b'{"jsonrpc":"2.0","id":1,"method":"ping"}'), self.principal()))
        self.assertEqual(ok.status_code, 200); self.assertEqual(ok.headers['mcp-protocol-version'], '2025-03-26')


if __name__ == '__main__':
    unittest.main()
