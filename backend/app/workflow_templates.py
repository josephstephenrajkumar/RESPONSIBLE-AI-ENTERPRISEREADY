"""Flow templates for workflow apps, expressed as Activepieces trigger trees.

Shapes follow packages/core/execution/src/lib/flows (PieceTrigger, PieceAction,
ImportFlowRequest) in Activepieces 0.92. Piece versions are resolved from the live
catalogue at creation time and pinned with a tilde range.
"""
from __future__ import annotations

from typing import Any, Dict

FORMS_PIECE = '@activepieces/piece-forms'
GATEWAY_PIECE = '@responsible-ai/piece-responsible-ai-gateway'
LITELLM_PIECE = '@responsible-ai/piece-litellm-proxy'

TEMPLATES: Dict[str, Dict[str, str]] = {
    'responsible-ai-chat': {
        'label': 'Responsible AI chat',
        'description': 'Chat UI → Responsible AI Gateway chat (privacy, safety, evaluation, metering) → reply. The same chat app as the Chat tab, running as a workflow.',
    },
    'litellm-chat': {
        'label': 'Direct LiteLLM chat',
        'description': "Chat UI → LiteLLM chat completion with the app's virtual key → reply. Budgeted and metered by the proxy; no Responsible AI processing.",
    },
    'blank': {
        'label': 'Blank (Chat UI trigger only)',
        'description': 'Chat UI trigger with no steps; build the rest in the Activepieces builder.',
    },
}


def _manual(keys) -> Dict[str, Dict[str, str]]:
    return {key: {'type': 'MANUAL'} for key in keys}


def _tilde(version: str) -> str:
    return version if version[:1] in ('~', '^') else f'~{version}'


def chat_trigger(forms_version: str, bot_name: str) -> Dict[str, Any]:
    return {
        'name': 'trigger', 'displayName': 'Chat UI', 'type': 'PIECE_TRIGGER', 'valid': True,
        'settings': {
            'pieceName': FORMS_PIECE, 'pieceVersion': _tilde(forms_version), 'triggerName': 'chat_submission',
            'input': {'botName': bot_name}, 'propertySettings': _manual(['botName']),
        },
    }


def respond_step(forms_version: str, markdown: str, name: str = 'step_2') -> Dict[str, Any]:
    return {
        'name': name, 'displayName': 'Respond on UI', 'type': 'PIECE', 'valid': True,
        'settings': {
            'pieceName': FORMS_PIECE, 'pieceVersion': _tilde(forms_version), 'actionName': 'return_response',
            'input': {'markdown': markdown}, 'propertySettings': _manual(['markdown']), 'errorHandlingOptions': {},
        },
    }


def build_trigger(template: str, *, versions: Dict[str, str], connection_gateway: str, connection_litellm: str,
                  app_id: str, bot_name: str, rai_mode: str, model: str) -> Dict[str, Any]:
    """Return the full trigger tree for IMPORT_FLOW."""
    forms_version = versions[FORMS_PIECE]
    trigger = chat_trigger(forms_version, bot_name)
    if template == 'blank':
        return trigger

    if template == 'responsible-ai-chat':
        step = {
            'name': 'step_1', 'displayName': 'Chat (Responsible AI)', 'type': 'PIECE', 'valid': True,
            'settings': {
                'pieceName': GATEWAY_PIECE, 'pieceVersion': _tilde(versions[GATEWAY_PIECE]), 'actionName': 'chat',
                'input': {
                    'auth': f"{{{{connections['{connection_gateway}']}}}}",
                    'message': "{{trigger['message']}}", 'mode': rai_mode, 'model': model or '',
                    'temperature': 0.2, 'maxTokens': 800, 'sessionId': "{{trigger['sessionId']}}", 'agentId': f'workflow-app:{app_id}',
                },
                'propertySettings': _manual(['auth', 'message', 'mode', 'model', 'temperature', 'maxTokens', 'sessionId', 'agentId']),
                'errorHandlingOptions': {'continueOnFailure': {'value': False}, 'retryOnFailure': {'value': False}},
            },
        }
        markdown = ("{{step_1['answer']}}\n\n---\n"
                    "_{{step_1['metadata']['usage']['served_model']}} · {{step_1['metadata']['usage']['total_tokens']}} tokens · "
                    "Responsible AI {{step_1['metadata']['mode']}} mode · request {{step_1['metadata']['request_id']}}_")
        step['nextAction'] = respond_step(forms_version, markdown)
        trigger['nextAction'] = step
        return trigger

    if template == 'litellm-chat':
        step = {
            'name': 'step_1', 'displayName': 'Chat completion (LiteLLM)', 'type': 'PIECE', 'valid': True,
            'settings': {
                'pieceName': LITELLM_PIECE, 'pieceVersion': _tilde(versions[LITELLM_PIECE]), 'actionName': 'chat_completion',
                'input': {
                    'auth': f"{{{{connections['{connection_litellm}']}}}}",
                    'model': model, 'systemPrompt': 'You are a concise, helpful assistant.',
                    'prompt': "{{trigger['message']}}", 'temperature': 0.2, 'maxTokens': 800, 'jsonOutput': False,
                    'appId': app_id, 'user': "{{trigger['sessionId']}}",
                },
                'propertySettings': _manual(['auth', 'model', 'systemPrompt', 'prompt', 'temperature', 'maxTokens', 'jsonOutput', 'appId', 'user']),
                'errorHandlingOptions': {'continueOnFailure': {'value': False}, 'retryOnFailure': {'value': False}},
            },
        }
        markdown = "{{step_1['content']}}\n\n---\n_{{step_1['model']}} via LiteLLM proxy · no Responsible AI processing_"
        step['nextAction'] = respond_step(forms_version, markdown)
        trigger['nextAction'] = step
        return trigger

    raise ValueError(f'unknown template {template!r}')
