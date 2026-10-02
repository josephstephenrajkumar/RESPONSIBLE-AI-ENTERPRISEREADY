"""Fallback token pricing used only when the LiteLLM proxy does not return a cost.

LiteLLM is the system of record for cost: it computes `x-litellm-response-cost`
from its maintained price map on every response. This table exists so that
(a) direct-mode calls and (b) proxy responses missing the header still produce
an *estimate* for the FinOps dashboard, clearly labelled `cost_source=estimated`.

Prices are USD per one million tokens and are approximate list prices. Keep this
table small; add a model here only when it is routed in litellm/config.yaml.
"""

from typing import Optional, Tuple

# model name (as requested through the gateway) -> (input $/1M tokens, output $/1M tokens)
_PRICE_PER_MILLION = {
    'llama-3.3-70b-versatile': (0.59, 0.79),
    'llama-3.1-8b-instant': (0.05, 0.08),
    'openai/gpt-oss-120b': (0.15, 0.60),
    'openai/gpt-oss-20b': (0.075, 0.30),
    'llama3-70b-8192': (0.59, 0.79),
    'llama3-8b-8192': (0.05, 0.08),
    'mixtral-8x7b-32768': (0.24, 0.24),
    'gemma2-9b-it': (0.20, 0.20),
    'gpt-4o-mini': (0.15, 0.60),
    'gpt-4o': (2.50, 10.00),
    'claude-3-5-haiku-20241022': (0.80, 4.00),
}

# Model-group aliases defined in litellm/config.yaml resolve to a concrete model
# for estimation purposes when the proxy did not tell us which one it served.
_ALIASES = {
    'chat-default': 'openai/gpt-oss-120b',
    'judge-fast': 'openai/gpt-oss-20b',
}


def _lookup(model: str) -> Optional[Tuple[float, float]]:
    if not model:
        return None
    name = _ALIASES.get(model.strip(), model.strip())
    if name in _PRICE_PER_MILLION:
        return _PRICE_PER_MILLION[name]
    # LiteLLM served-model ids may carry a provider prefix such as `groq/`;
    # strip prefixes one at a time so `groq/openai/gpt-oss-120b` resolves.
    while '/' in name:
        name = name.split('/', 1)[1]
        name = _ALIASES.get(name, name)
        if name in _PRICE_PER_MILLION:
            return _PRICE_PER_MILLION[name]
    return None


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """Return an estimated USD cost, or None when the model is not in the table."""
    prices = _lookup(model)
    if prices is None:
        return None
    input_price, output_price = prices
    cost = (prompt_tokens or 0) / 1_000_000 * input_price + (completion_tokens or 0) / 1_000_000 * output_price
    return round(cost, 8)
