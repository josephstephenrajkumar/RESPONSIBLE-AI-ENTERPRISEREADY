"""Unit tests for the Workflow Studio API (engine replaced by fakes). Run from backend/:
    ./venv/bin/python -m unittest tests.test_workflow_studio -v
"""
import asyncio
import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ['LLM_GATEWAY_MODE'] = 'proxy'
os.environ['ACTIVEPIECES_SERVICE_PASSWORD'] = 'unit-test-password'  # secret-scan:allow unit-test placeholder

from fastapi import HTTPException  # noqa: E402

from app import auth, database, workflow_apps, workflow_studio, workflow_templates, workflow_tokens  # noqa: E402
from app.activepieces_client import ActivepiecesError  # noqa: E402
from tests.test_workflow_apps import FakeActivepieces, FakeLiteLLM, admin_user  # noqa: E402


def run(coro):
    return asyncio.run(coro)


TRIGGER = {
    'name': 'trigger', 'displayName': 'Chat UI', 'type': 'PIECE_TRIGGER', 'valid': True,
    'settings': {'pieceName': '@activepieces/piece-forms', 'pieceVersion': '~0.5.0', 'triggerName': 'chat_submission', 'input': {'botName': 'Bot'}, 'propertySettings': {}},
    'nextAction': {
        'name': 'step_1', 'displayName': 'Router', 'type': 'ROUTER', 'valid': True,
        'settings': {'branches': [{'branchName': 'Yes', 'branchType': 'CONDITION', 'conditions': [[]]}, {'branchName': 'Otherwise', 'branchType': 'FALLBACK'}], 'executionType': 'EXECUTE_FIRST_MATCH', 'input': {}, 'propertySettings': {}},
        'children': [
            {'name': 'step_2', 'displayName': 'Chat', 'type': 'PIECE', 'valid': True, 'settings': {'pieceName': '@responsible-ai/piece-responsible-ai-gateway', 'pieceVersion': '~0.1.1', 'actionName': 'chat', 'input': {'message': "{{trigger['message']}}"}, 'propertySettings': {}}},
            None,
        ],
        'nextAction': {'name': 'step_3', 'displayName': 'Respond', 'type': 'PIECE', 'valid': False, 'settings': {'pieceName': '@activepieces/piece-forms', 'pieceVersion': '~0.5.0', 'actionName': 'return_response', 'input': {}, 'propertySettings': {}}},
    },
}


class FakeStudioEngine(FakeActivepieces):
    def __init__(self):
        super().__init__()
        self.catalogue = [
            {'name': '@responsible-ai/piece-responsible-ai-gateway', 'displayName': 'Responsible AI Gateway', 'version': '0.1.1', 'actions': 2, 'triggers': 0},
            {'name': '@activepieces/piece-http', 'displayName': 'HTTP', 'version': '0.12.1', 'actions': 2, 'triggers': 0},
            {'name': '@activepieces/piece-forms', 'displayName': 'Human Input', 'version': '0.5.0', 'actions': 1, 'triggers': 2},
            {'name': '@activepieces/piece-not-curated', 'displayName': 'Not curated', 'version': '1.0.0', 'actions': 1, 'triggers': 0},
        ]
        self.connections = []
        self.operations = []
        self.runs = {'run_1': {'id': 'run_1', 'flowId': None, 'status': 'FAILED', 'failedStepName': 'step_2',
                               'steps': {'trigger': {'status': 'SUCCEEDED', 'type': 'PIECE_TRIGGER', 'input': {}, 'output': {'message': 'hi'}},
                                         'step_2': {'status': 'FAILED', 'type': 'PIECE', 'input': {'message': 'hi'}, 'errorMessage': 'HTTP 500'}}}}

    async def list_pieces(self, search=''):
        return self.catalogue

    async def get_piece(self, name):
        if name == '@activepieces/piece-slack':
            return {'name': name, 'version': '0.21.0', 'auth': [{'type': 'OAUTH2', 'authUrl': 'https://slack.com/oauth/v2/authorize?user_scope=x', 'tokenUrl': 'https://slack.com/api/oauth.v2.access', 'scope': ['chat:write', 'channels:read']}]}
        return self.pieces.get(name) or next((p for p in self.catalogue if p['name'] == name), None)

    async def get_flow(self, flow_id):
        return {'id': flow_id, 'status': 'DISABLED', 'publishedVersionId': None, 'version': {'id': 'ver_1', 'displayName': 'Draft', 'state': 'DRAFT', 'valid': False, 'trigger': TRIGGER}}

    async def apply_operation(self, flow_id, operation, request):
        self.operations.append((operation, request))
        return {'id': flow_id}

    async def list_connections(self, piece_name=None, limit=100):
        return self.connections

    async def upsert_connection(self, body):
        conn = {'id': f"conn_{len(self.connections)+1}", **{k: body[k] for k in ('externalId', 'displayName', 'pieceName', 'type')}, 'status': 'ACTIVE', 'value': body['value']}
        self.connections.append(conn)
        return conn

    async def piece_options(self, body):
        return {'options': [{'label': body['propertyName'], 'value': 'opt_1'}], 'disabled': False}

    async def step_run(self, flow_version_id, step_name):
        # The engine returns the queued TESTING run; the result lands on the run record.
        self.runs['sr_1'] = {'id': 'sr_1', 'flowId': None, 'status': 'SUCCEEDED', 'duration': 12,
                             'steps': {'trigger': {'status': 'SUCCEEDED', 'output': {'message': 'hi'}}, step_name: {'type': 'PIECE', 'status': 'SUCCEEDED', 'input': {'message': 'hi'}, 'output': {'answer': 'ok'}}}}
        return {'id': 'sr_1', 'status': 'QUEUED'}

    async def get_run(self, run_id):
        run = self.runs.get(run_id)
        if run and run['flowId'] is None:
            run['flowId'] = f"flow_{self.flow_external}"
        return run

    async def retry_run(self, run_id, strategy):
        return {'id': 'run_2', 'status': 'QUEUED'}

    async def list_flow_versions(self, flow_id, limit=20):
        return [{'id': 'ver_1', 'displayName': 'Draft', 'state': 'DRAFT', 'valid': False}, {'id': 'ver_0', 'displayName': 'v1', 'state': 'LOCKED', 'valid': True}]


class StudioBase(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        workflow_apps.ensure_tables()
        with database.SessionLocal() as session:
            for model in (workflow_apps.WorkflowApp, workflow_apps.WorkflowSetting, workflow_tokens.WorkflowAppToken):
                session.query(model).delete()
            session.commit()
        self.ap = FakeStudioEngine()
        self.llm = FakeLiteLLM()
        self._patches = [mock.patch.object(workflow_apps, 'activepieces', self.ap), mock.patch.object(workflow_apps, 'litellm_admin', self.llm),
                         mock.patch.object(workflow_studio, 'activepieces', self.ap)]
        for p in self._patches:
            p.start()
        self.app = run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='Studio app', template='blank'), admin_user()))
        self.ap.flow_external = self.app['id']

    def tearDown(self):
        for p in self._patches:
            p.stop()


class CatalogueTests(StudioBase):
    def test_curated_catalogue_order_and_filter(self):
        result = run(workflow_studio.studio_pieces('', admin_user()))
        names = [p['name'] for p in result['pieces']]
        self.assertEqual(names[0], '@responsible-ai/piece-responsible-ai-gateway')
        self.assertNotIn('@activepieces/piece-not-curated', names)
        self.assertIn('@activepieces/piece-http', names)
        result = run(workflow_studio.studio_pieces('http', admin_user()))
        self.assertEqual([p['name'] for p in result['pieces']], ['@activepieces/piece-http'])

    def test_catalogue_can_be_managed(self):
        workflow_studio.studio_catalogue_update(workflow_studio.CatalogueUpdate(pieces=['@activepieces/piece-not-curated']), admin_user())
        result = run(workflow_studio.studio_pieces('', admin_user()))
        self.assertEqual([p['name'] for p in result['pieces']], ['@activepieces/piece-not-curated'])
        self.assertEqual(workflow_studio.studio_catalogue(admin_user())['pieces'], ['@activepieces/piece-not-curated'])


class FlowTests(StudioBase):
    def test_flow_payload_flattens_router_branches(self):
        payload = run(workflow_studio.studio_flow(self.app['id'], admin_user()))
        steps = payload['steps']
        self.assertEqual([s['name'] for s in steps], ['trigger', 'step_1', 'step_2', 'step_3'])
        router = steps[1]; child = steps[2]; after = steps[3]
        self.assertEqual(router['type'], 'ROUTER'); self.assertEqual(len(router['branches']), 2)
        self.assertEqual((child['parent'], child['branch'], child['depth']), ('step_1', 0, 1))
        self.assertEqual((after['parent'], after['depth']), (None, 0))
        self.assertEqual(payload['version']['id'], 'ver_1')
        self.assertEqual(payload['connections'], [])  # fakes have no engine connections for this app

    def test_operations_are_allow_listed_and_applied(self):
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_studio.studio_operation(self.app['id'], workflow_studio.OperationRequest(type='LOCK_AND_PUBLISH', request={}), admin_user()))
        self.assertEqual(ctx.exception.status_code, 400)
        result = run(workflow_studio.studio_operation(self.app['id'], workflow_studio.OperationRequest(type='CHANGE_NAME', request={'displayName': 'Renamed'}), admin_user()))
        self.assertEqual(self.ap.operations[-1], ('CHANGE_NAME', {'displayName': 'Renamed'}))
        self.assertIn('steps', result)

    def test_tenant_boundary(self):
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_studio.studio_flow(self.app['id'], admin_user('other-tenant')))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_dynamic_options_use_the_draft_version(self):
        result = run(workflow_studio.studio_options(self.app['id'], workflow_studio.OptionsRequest(piece_name='@activepieces/piece-ai', piece_version='~0.11.0', action_or_trigger_name='askAi', property_name='model', input={'provider': 'custom'}), admin_user()))
        self.assertEqual(result['options'][0]['value'], 'opt_1')

    def test_versions_listed(self):
        result = run(workflow_studio.studio_versions(self.app['id'], admin_user()))
        self.assertEqual([v['state'] for v in result['versions']], ['DRAFT', 'LOCKED'])


class ConnectionTests(StudioBase):
    def test_custom_auth_and_secret_connections(self):
        created = run(workflow_studio.studio_connection_create(self.app['id'], workflow_studio.ConnectionCreate(piece_name='@activepieces/piece-http', display_name='My API', auth_type='CUSTOM_AUTH', props={'key': 'v'}), admin_user()))
        self.assertTrue(created['externalId'].startswith(self.app['id'] + '-http-'))
        self.assertEqual(created['reference'], f"{{{{connections['{created['externalId']}']}}}}")
        created2 = run(workflow_studio.studio_connection_create(self.app['id'], workflow_studio.ConnectionCreate(piece_name='@activepieces/piece-x', display_name='Token', auth_type='SECRET_TEXT', secret_text='abc'), admin_user()))
        self.assertEqual(self.ap.connections[-1]['value'], {'type': 'SECRET_TEXT', 'secret_text': 'abc'})
        listed = run(workflow_studio.studio_connections(self.app['id'], admin_user()))['connections']
        self.assertEqual({c['id'] for c in listed}, {'conn_1', 'conn_2'})
        with self.assertRaises(HTTPException):
            run(workflow_studio.studio_connection_create(self.app['id'], workflow_studio.ConnectionCreate(piece_name='x', display_name='bad', auth_type='CUSTOM_AUTH'), admin_user()))

    def test_oauth2_authorization_url_and_connection(self):
        url = run(workflow_studio.studio_oauth_url(self.app['id'], workflow_studio.OAuthUrlRequest(piece_name='@activepieces/piece-slack', client_id='cid', redirect_url='https://portal.example/oauth/callback'), admin_user()))
        self.assertIn('client_id=cid', url['authorization_url']); self.assertIn('state=', url['authorization_url']); self.assertIn('chat%3Awrite', url['authorization_url'])
        created = run(workflow_studio.studio_connection_create(self.app['id'], workflow_studio.ConnectionCreate(piece_name='@activepieces/piece-slack', display_name='Slack', auth_type='OAUTH2', oauth2={'client_id': 'cid', 'client_secret': 'cs', 'code': 'abc', 'redirect_url': 'https://portal.example/oauth/callback', 'scope': 'chat:write'}), admin_user()))
        self.assertEqual(self.ap.connections[-1]['value']['type'], 'OAUTH2'); self.assertEqual(self.ap.connections[-1]['value']['code'], 'abc')
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_studio.studio_connection_create(self.app['id'], workflow_studio.ConnectionCreate(piece_name='@activepieces/piece-slack', display_name='Slack', auth_type='OAUTH2', oauth2={'client_id': 'cid'}), admin_user()))
        self.assertEqual(ctx.exception.status_code, 400)


class RunAndTestTests(StudioBase):
    def test_step_test_returns_output(self):
        result = run(workflow_studio.studio_test_step(self.app['id'], 'step_2', admin_user()))
        self.assertTrue(result['success']); self.assertEqual(result['output'], {'answer': 'ok'}); self.assertEqual(result['run_id'], 'sr_1'); self.assertTrue(result['settled'])

    def test_run_detail_and_retry(self):
        detail = run(workflow_studio.studio_run(self.app['id'], 'run_1', admin_user()))
        self.assertEqual(detail['status'], 'FAILED'); self.assertEqual(detail['failed_step'], 'step_2')
        self.assertEqual([s['name'] for s in detail['steps']], ['trigger', 'step_2'])
        self.assertEqual(detail['steps'][1]['error'], 'HTTP 500')
        retried = run(workflow_studio.studio_retry_run(self.app['id'], 'run_1', 'FROM_FAILED_STEP', admin_user()))
        self.assertEqual(retried['status'], 'QUEUED')
        with self.assertRaises(HTTPException):
            run(workflow_studio.studio_run(self.app['id'], 'missing', admin_user()))


if __name__ == '__main__':
    unittest.main()
