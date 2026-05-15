import re
import warnings
from functools import lru_cache
from importlib import import_module
from threading import RLock

from app.framework_mode.langfuse_observability import langfuse_observe
from app.policy_governance import active_policies, record_runtime_decision, summarize_policy_test
from app.telemetry import tracer

warnings.filterwarnings(
    'ignore',
    message='Could not obtain an event loop. Falling back to synchronous validation.',
    category=UserWarning,
    module='guardrails.validator_service'
)

try:
    from guardrails import Guard, OnFailAction
    from guardrails.settings import settings as guardrails_settings
    from guardrails.validator_base import Validator, register_validator
    from guardrails.validators import FailResult, PassResult

    guardrails_settings.disable_tracing = True
    if guardrails_settings.rc:
        guardrails_settings.rc.enable_metrics = False
        guardrails_settings.rc.use_remote_inferencing = False

    _guardrails_available = True
except ImportError:
    Guard = None
    OnFailAction = None
    Validator = object
    FailResult = None
    PassResult = None
    register_validator = None
    _guardrails_available = False

_compiled_policy_cache = []
_hub_policy_cache = []
_compiled_policy_version = 'none'
_cache_lock = RLock()

_BUILTIN_HIGH_RISK_PATTERNS = [
    {
        'category': 'dangerous_instructions',
        'label': 'explosives_or_weapons_instructions',
        'pattern': (
            r'\b(?:how\s+to\s+)?(?:make|build|create|assemble|construct|manufacture|'
            r'produce|synthesize|weaponize)\b.{0,80}\b(?:bomb|explosive|ied|'
            r'detonator|grenade|landmine|pipe\s*bomb|molotov)\b'
        ),
    },
    {
        'category': 'dangerous_instructions',
        'label': 'explosives_or_weapons_instructions',
        'pattern': (
            r'\b(?:bomb|explosive|ied|detonator|grenade|landmine|pipe\s*bomb|'
            r'molotov)\b.{0,80}\b(?:recipe|instructions?|guide|steps?|materials?|'
            r'ingredients?|tutorial|blueprint|formula)\b'
        ),
    },
    {
        'category': 'dangerous_instructions',
        'label': 'explosives_or_weapons_instructions',
        'pattern': (
            r'\b(?:tell|show|teach|explain|give)\b.{0,80}\bhow\s+to\b.{0,80}'
            r'\b(?:bomb|explosive|ied|detonator|grenade|landmine|pipe\s*bomb|'
            r'molotov)\b'
        ),
    },
    {
        'category': 'dangerous_instructions',
        'label': 'explosives_or_weapons_instructions',
        'pattern': (
            r'\bhow\s+to\b.{0,80}\b(?:bomb|explosive|ied|detonator|grenade|'
            r'landmine|pipe\s*bomb|molotov)\b'
        ),
    },
]
_BUILTIN_HIGH_RISK_COMPILED = [
    {**item, 'compiled': re.compile(item['pattern'], re.IGNORECASE)}
    for item in _BUILTIN_HIGH_RISK_PATTERNS
]


def _module_name_from_hub_uri(hub_uri):
    validator_id = (hub_uri or '').replace('hub://', '')
    namespace, package = validator_id.split('/', 1)
    return f'{namespace}_grhub_{package}'.replace('-', '_')


def _load_hub_validator_class(item):
    try:
        hub_module = import_module('guardrails.hub')
        if hasattr(hub_module, item['validator_class']):
            return getattr(hub_module, item['validator_class'])
    except Exception:
        pass
    module = import_module(_module_name_from_hub_uri(item['hub_uri']))
    return getattr(module, item['validator_class'])


def _compile_policies():
    compiled = []
    hub_validators = []
    versions = []
    for policy in active_policies():
        compiled_patterns = []
        for item in policy.get('patterns', []):
            flags = 0 if item.get('is_case_sensitive') else re.IGNORECASE
            try:
                compiled_patterns.append(
                    {
                        'pattern': item.get('pattern', ''),
                        'label': item.get('label', ''),
                        'compiled': re.compile(item.get('pattern', ''), flags),
                    }
                )
            except re.error:
                continue
        if compiled_patterns:
            compiled.append({**policy, 'compiled_patterns': compiled_patterns})
            versions.append(f"{policy['id']}:{policy['version']}")
        for hub_validator in policy.get('hub_validators', []):
            hub_validators.append({
                'policy': policy,
                **hub_validator,
            })
            versions.append(f"{policy['id']}:{policy['version']}")
    return compiled, hub_validators, ','.join(sorted(set(versions))) or 'none'


@langfuse_observe(name='policy_reload')
def reload_safety_policies():
    global _compiled_policy_cache, _hub_policy_cache, _compiled_policy_version
    with tracer.start_as_current_span('policy_load'):
        with _cache_lock:
            _compiled_policy_cache, _hub_policy_cache, _compiled_policy_version = _compile_policies()
            _get_guardrails_safety_guard.cache_clear()
    return {
        'loaded_policies': len(_compiled_policy_cache),
        'loaded_hub_validators': len(_hub_policy_cache),
        'policy_version': _compiled_policy_version
    }


def _loaded_policies():
    if not _compiled_policy_cache:
        reload_safety_policies()
    return _compiled_policy_cache


def _detect_violations(text):
    text = text or ''
    violations = []
    matched_patterns = []
    with tracer.start_as_current_span('policy_match'):
        builtin_matches = []
        builtin_patterns = []
        for item in _BUILTIN_HIGH_RISK_COMPILED:
            found = [match.group(0) for match in item['compiled'].finditer(text)]
            if found:
                builtin_matches.extend(found)
                builtin_patterns.append(item['pattern'])
        if builtin_matches:
            violations.append(
                {
                    'policy_id': 'builtin-dangerous-instructions',
                    'policy_name': 'Built-in Dangerous Instructions Policy',
                    'category': 'dangerous_instructions',
                    'severity': 'high',
                    'matches': sorted(set(builtin_matches), key=str.lower),
                    'patterns': sorted(set(builtin_patterns)),
                }
            )
            matched_patterns.extend(builtin_patterns)

        for policy in _loaded_policies():
            matches = []
            policy_patterns = []
            for item in policy['compiled_patterns']:
                found = [match.group(0) for match in item['compiled'].finditer(text)]
                if found:
                    matches.extend(found)
                    policy_patterns.append(item['pattern'])
            if matches:
                violations.append(
                    {
                        'policy_id': policy['id'],
                        'policy_name': policy['name'],
                        'category': policy['category'],
                        'severity': policy['severity'],
                        'matches': sorted(set(matches), key=str.lower),
                        'patterns': sorted(set(policy_patterns)),
                    }
                )
                matched_patterns.extend(policy_patterns)
    return violations, sorted(set(matched_patterns))


def _risk_for(violations):
    if any(item['severity'] == 'high' for item in violations):
        return 'high'
    if violations:
        return 'medium'
    return 'low'


if _guardrails_available:
    @register_validator(name='responsible_ai/safety_policy', data_type='string')
    class ResponsibleAISafetyPolicy(Validator):
        def _validate(self, value, metadata):
            violations, _ = _detect_violations(value)
            if violations:
                categories = ', '.join(item['category'] for item in violations)
                return FailResult(
                    errorMessage=f'Unsafe content matched safety policy: {categories}',
                    metadata={'violations': violations}
                )
            return PassResult(metadata={'violations': []})


@lru_cache(maxsize=1)
def _get_guardrails_safety_guard():
    if not _guardrails_available:
        return None, 'guardrails-ai is not installed'
    try:
        guard = Guard()
        guard.configure(allow_metrics_collection=False)
        configured_guard = guard.use(ResponsibleAISafetyPolicy(on_fail=OnFailAction.NOOP))
        setup_errors = []
        for item in _hub_policy_cache:
            try:
                validator_class = _load_hub_validator_class(item)
                runtime_params = dict(item.get('runtime_params') or {})
                runtime_params['on_fail'] = OnFailAction.NOOP
                configured_guard = configured_guard.use(validator_class, **runtime_params)
            except Exception as exc:
                setup_errors.append(f"{item.get('validator_class')}: {exc}")
        return configured_guard, '; '.join(setup_errors) or None
    except Exception as exc:
        return None, str(exc)


@langfuse_observe(name='safety_evaluation')
def evaluate_safety(message, stage='input'):
    message = message or ''
    violations, matched_patterns = _detect_violations(message)
    risk = _risk_for(violations)
    guard, setup_error = _get_guardrails_safety_guard()

    validation_passed = risk == 'low'
    validation_summaries = []
    engine = 'guardrails_ai'

    if guard:
        try:
            with tracer.start_as_current_span('guardrails_validate'):
                outcome = guard.validate(message, metadata={'stage': stage})
            validation_passed = bool(outcome.validation_passed)
            validation_summaries = [
                {
                    'validator_name': summary.validator_name,
                    'validator_status': summary.validator_status,
                    'failure_reason': summary.failure_reason,
                    'property_path': summary.property_path,
                }
                for summary in outcome.validation_summaries
            ]
        except Exception as exc:
            setup_error = str(exc)
            engine = 'guardrails_ai_with_regex_fallback'
    else:
        engine = 'regex_fallback'

    blocked = not validation_passed or risk == 'high'
    categories = [item['category'] for item in violations]
    result = {
        'safety_engine': engine,
        'validator_engine': engine,
        'safety_stage': stage,
        'safety_risk': risk,
        'risk_level': risk,
        'validation_passed': validation_passed,
        'blocked': blocked,
        'violations': categories,
        'matched_categories': categories,
        'matched_patterns': matched_patterns,
        'policy_version': _compiled_policy_version,
        'policy_violations': violations,
        'validation_summaries': validation_summaries,
        'setup_error': setup_error,
        'recommendation': (
            'Block this request and route to human review'
            if blocked
            else 'Guardrails AI safety policy passed'
        )
    }
    record_runtime_decision(
        {
            'message': message,
            'stage': stage,
            'blocked': blocked,
            'risk_level': risk,
            'matched_categories': categories,
            'matched_patterns': matched_patterns,
            'policy_version': _compiled_policy_version,
            'validator_engine': engine,
        }
    )
    return result


@langfuse_observe(name='policy_test')
def test_safety_policy(message):
    return summarize_policy_test(evaluate_safety(message, stage='test'))
