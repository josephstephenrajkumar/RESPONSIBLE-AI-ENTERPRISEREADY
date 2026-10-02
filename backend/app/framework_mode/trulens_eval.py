import asyncio

from app.config import Settings

try:
    from trulens.core.feedback.endpoint import Endpoint
    from trulens.feedback.llm_provider import LLMProvider

    _trulens_available = True
except ImportError:
    Endpoint = None
    LLMProvider = object
    _trulens_available = False


EXPLAINABILITY_SYSTEM_PROMPT = (
    'You are grading how well an AI assistant response explains its reasoning to a '
    'reader. Score the response from 0 (no rationale, unexplained assertions) to 10 '
    '(clear, well-structured explanation of how the conclusion was reached). '
    'Respond with only a JSON object: {"score": <0-10 integer>, "reason": "<one sentence>"}.'
)


def _evaluate_explainability_fallback(answer):
    return {
        'explanation_provided': bool(answer),
        'explanation_level': 'high-level',
        'explainability_score': None,
        'evaluator_engine': 'heuristic_fallback',
        'recommendation': 'Evaluate rationale quality with model cards'
    }


if _trulens_available:
    class _GatewayExplainabilityProvider(LLMProvider):
        """Minimal TruLens LLMProvider that routes the judge call through the
        gateway's single LLM client (LiteLLM proxy), so explainability scoring
        uses no provider secret of its own and is metered like every other call."""

        def __init__(self):
            # Endpoint.retries defaults to 3 (4 attempts, exponential backoff),
            # tuned for offline batch scoring. A live /chat request needs a
            # much smaller retry budget; the proxy already retries upstream.
            super().__init__(
                name='llm-gateway',
                model_engine=Settings.LLM_JUDGE_MODEL,
                endpoint=Endpoint(name='llm-gateway', retries=1)
            )

        def _create_chat_completion(self, prompt=None, messages=None, response_format=None, **kwargs):
            # Deferred import: app.llm_client imports app.framework_mode, which
            # loads this module during package init. Importing at module scope
            # here would be circular.
            from app.llm_client import llm_client

            payload_messages = messages or [{'role': 'user', 'content': prompt or ''}]
            result = llm_client.complete_sync(
                payload_messages,
                model=Settings.LLM_JUDGE_MODEL,
                temperature=kwargs.get('temperature', 0.0),
                max_tokens=200,
                purpose='judge_explainability',
            )
            if result.get('status') != 'success':
                raise RuntimeError(result.get('answer') or 'judge call failed')
            return result.get('answer', '')


def _run_trulens_score(answer):
    provider = _GatewayExplainabilityProvider()
    raw_score = provider.generate_score(
        system_prompt=EXPLAINABILITY_SYSTEM_PROMPT,
        user_prompt=answer or '',
        min_score_val=0,
        max_score_val=10,
    )
    return float(raw_score)


async def evaluate_explainability(answer):
    if not _trulens_available:
        return _evaluate_explainability_fallback(answer)

    try:
        # Hard backstop in addition to Endpoint(retries=1): never let a live
        # /chat request hang on the judge LLM regardless of internal retries.
        explainability_score = await asyncio.wait_for(
            asyncio.to_thread(_run_trulens_score, answer), timeout=20
        )
        if explainability_score < 0:
            raise ValueError('TruLens could not parse a valid score from the model response')
        return {
            'explanation_provided': bool(answer),
            'explanation_level': 'high' if explainability_score >= 0.66 else ('medium' if explainability_score >= 0.33 else 'low'),
            'explainability_score': explainability_score,
            'evaluator_engine': 'trulens',
            'recommendation': 'TruLens LLM-graded explanation-quality feedback'
        }
    except Exception:
        return _evaluate_explainability_fallback(answer)
