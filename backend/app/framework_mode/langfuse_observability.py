from app.config import Settings

try:
    from langfuse import Langfuse
    from langfuse.decorators import observe, langfuse_context
    _langfuse_available = True
except ImportError:
    _langfuse_available = False
    observe = None
    langfuse_context = None
    Langfuse = None

_langfuse_configured = bool(
    Settings.LANGFUSE_PUBLIC_KEY
    and Settings.LANGFUSE_SECRET_KEY
    and Settings.LANGFUSE_HOST
)

if _langfuse_available and _langfuse_configured:
    langfuse_context.configure(
        public_key=Settings.LANGFUSE_PUBLIC_KEY or None,
        secret_key=Settings.LANGFUSE_SECRET_KEY or None,
        host=Settings.LANGFUSE_HOST or None,
        enabled=True
    )

if _langfuse_available and _langfuse_configured:
    langfuse_client = Langfuse(
        public_key=Settings.LANGFUSE_PUBLIC_KEY,
        secret_key=Settings.LANGFUSE_SECRET_KEY,
        host=Settings.LANGFUSE_HOST
    )
else:
    langfuse_client = None


def langfuse_observe(*args, **kwargs):
    if observe and _langfuse_configured:
        return observe(*args, **kwargs)

    def decorator(func):
        return func

    return decorator


def evaluate_observability(message):
    configured = _langfuse_available and _langfuse_configured
    return {
        'observability': 'enabled' if configured else 'disabled',
        'details': 'Langfuse decorator tracing configured' if configured else 'Langfuse not configured',
        'recommendation': (
            'Langfuse decorator traces are sent for framework-mode chat calls'
            if configured
            else 'Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, and LANGFUSE_SECRET_KEY for full observability'
        )
    }


def is_langfuse_configured() -> bool:
    return _langfuse_available and _langfuse_configured


def update_current_llm_trace(request_id: str, input_data: dict, output_data: dict) -> None:
    if not langfuse_context:
        return

    usage = output_data.get('metadata', {}).get('usage', {})
    langfuse_context.update_current_trace(
        name='llm_chat_call',
        input=input_data,
        output={'answer': output_data.get('answer', '')},
        metadata={
            'request_id': request_id,
            'provider': output_data.get('provider'),
            'model': output_data.get('model'),
            'timestamp': output_data.get('timestamp')
        },
        tags=['responsible-ai-chat-agent', input_data.get('mode', 'framework')]
    )
    langfuse_context.update_current_observation(
        name='groq_completion',
        input=input_data,
        output=output_data.get('answer', ''),
        model=output_data.get('model'),
        model_parameters={
            'temperature': input_data.get('temperature'),
            'max_tokens': input_data.get('max_tokens')
        },
        metadata={
            'request_id': request_id,
            'provider': output_data.get('provider'),
            'mode': input_data.get('mode')
        },
        usage={
            'input': usage.get('prompt_tokens', 0),
            'output': usage.get('completion_tokens', 0),
        }
    )


def trace_llm_call(request_id: str, input_data: dict, output_data: dict) -> dict:
    if not is_langfuse_configured():
        return {
            'status': 'disabled',
            'reason': 'Langfuse SDK not configured'
        }

    try:
        langfuse_context.flush()
        return {
            'status': 'sent',
            'trace_id': request_id,
            'service': 'Langfuse decorators'
        }
    except Exception as exc:
        return {
            'status': 'error',
            'error': str(exc)
        }
