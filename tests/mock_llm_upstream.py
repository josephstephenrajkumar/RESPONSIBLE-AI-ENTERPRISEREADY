#!/usr/bin/env python3
"""Minimal OpenAI-compatible upstream for offline / zero-spend testing.

LiteLLM routes to this server when started with litellm/config.mock.yaml
(docker compose -f docker-compose.yml -f docker-compose.mock.yml up -d), so the
whole path  AI Gateway -> LiteLLM proxy -> upstream  can be exercised, including
cost headers, retries and fallbacks, without a provider key or any spend.

Behaviour by model name:
  mock-chat   - answers with a short deterministic reply
  mock-judge  - answers judge prompts (TruLens expects a JSON score)
  mock-fail   - always returns HTTP 503, to exercise LiteLLM retries/fallbacks
  mock-slow   - sleeps 2 s before answering, to exercise latency percentiles

Run:  backend/venv/bin/python tests/mock_llm_upstream.py --port 4010
"""

import argparse
import asyncio
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title='mock-llm-upstream')


def _tokens(text: str) -> int:
    # Rough but deterministic: 4 characters per token.
    return max(1, len(text or '') // 4)


@app.get('/v1/models')
async def models():
    return {'object': 'list', 'data': [{'id': name, 'object': 'model'} for name in ('mock-chat', 'mock-judge', 'mock-fail', 'mock-slow')]}


@app.post('/v1/chat/completions')
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get('model', 'mock-chat')
    messages = body.get('messages') or []
    prompt_text = ' '.join(str(message.get('content', '')) for message in messages)
    last_user = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), '')

    if model.endswith('mock-fail'):
        return JSONResponse(status_code=503, content={'error': {'message': 'mock upstream unavailable', 'type': 'server_error'}})
    if model.endswith('mock-slow'):
        await asyncio.sleep(2)

    if 'score the response' in prompt_text.lower() or model.endswith('mock-judge'):
        # Shape TruLens' generate_score can parse; Ragas AspectCritic has a
        # stricter schema and will fall back to its heuristic (reported as
        # DEGRADED by the scenario suite, which is the honest outcome).
        answer = '{"score": 7, "reason": "The response states its reasoning in clear steps."}'
    else:
        answer = f'[mock-upstream:{model}] Here is a careful, responsible answer to: {str(last_user)[:160]}'

    prompt_tokens = _tokens(prompt_text)
    completion_tokens = min(int(body.get('max_tokens') or 64), _tokens(answer))
    return {
        'id': f'chatcmpl-mock-{uuid.uuid4().hex[:12]}',
        'object': 'chat.completion',
        'created': int(time.time()),
        'model': model,
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': answer}, 'finish_reason': 'stop'}],
        'usage': {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
        },
    }


if __name__ == '__main__':
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=4010)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')
