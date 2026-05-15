import importlib
import html
import os
from pathlib import Path
import re
import shutil
import site
import subprocess
import sys
import time
from typing import Any, Dict, List

import httpx

from app.config import Settings
from app.telemetry import tracer


HUB_PAGE_URL = 'https://guardrailsai.com/hub'
HUB_DETAIL_URL = 'https://guardrailsai.com/hub/validator/{namespace}/{validator}'
_catalog_cache: dict[str, Any] = {'loaded_at': 0.0, 'validators': None, 'source': 'fallback'}

RECOMMENDED_HUB_VALIDATORS = [
    {
        'hub_uri': 'hub://guardrails/prompt_injection_detector',
        'validator_class': 'PromptInjectionDetector',
        'name': 'Prompt Injection Detector',
        'category': 'jailbreaking',
        'severity': 'high',
        'description': 'Detects prompt-injection attempts via a secondary LLM validator.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'Protect agents and tool-using workflows'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/detect_jailbreak',
        'validator_class': 'DetectJailbreak',
        'name': 'Detect Jailbreak',
        'category': 'jailbreaking',
        'severity': 'high',
        'description': 'Detects attempts to circumvent safeguards in model conditioning.',
        'runtime_params': {'threshold': 0.9},
        'metadata': {'recommended': True, 'why': 'Runtime safety'},
        'requires_model': True,
    },
    {
        'hub_uri': 'hub://guardrails/grounded_ai_hallucination',
        'validator_class': 'GroundedAIHallucination',
        'name': 'Grounded AI Hallucination',
        'category': 'factuality',
        'severity': 'high',
        'description': 'Detects hallucinated text against grounding context.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'RAG verification and trustworthiness'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/bias_check',
        'validator_class': 'BiasCheck',
        'name': 'Bias Check',
        'category': 'fairness',
        'severity': 'high',
        'description': 'Checks generated text for demographic bias.',
        'runtime_params': {'threshold': 0.9},
        'metadata': {'recommended': True, 'why': 'Responsible AI fairness pillar'},
        'requires_model': True,
    },
    {
        'hub_uri': 'hub://guardrails/valid_json',
        'validator_class': 'ValidJson',
        'name': 'Valid JSON',
        'category': 'formatting',
        'severity': 'medium',
        'description': 'Ensures generated output is parseable as valid JSON.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'API reliability'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/toxic_language',
        'validator_class': 'ToxicLanguage',
        'name': 'Toxic Language',
        'category': 'toxicity',
        'severity': 'high',
        'description': 'Detects toxic or abusive language using a Guardrails Hub validator.',
        'runtime_params': {'threshold': 0.5, 'validation_method': 'sentence'},
        'metadata': {'recommended': True, 'why': 'User-facing safety'},
        'requires_model': True,
    },
    {
        'hub_uri': 'hub://guardrails/toxic_language_llm',
        'validator_class': 'ToxicLanguageLLM',
        'name': 'Toxic Language LLM',
        'category': 'toxicity',
        'severity': 'high',
        'description': 'Detects toxic language across multiple toxicity categories using an LLM.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'Toxicity and hate speech'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/detect_pii',
        'validator_class': 'DetectPII',
        'name': 'Detect PII',
        'category': 'privacy',
        'severity': 'high',
        'description': 'Detects personally identifiable information with a Guardrails Hub validator.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'Privacy compliance'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/guardrails_pii',
        'validator_class': 'GuardrailsPII',
        'name': 'Guardrails PII',
        'category': 'privacy',
        'severity': 'high',
        'description': 'Detects personally identifiable information in text.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'PII detection and redaction'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/secrets_present',
        'validator_class': 'SecretsPresent',
        'name': 'Secrets Present',
        'category': 'secrets',
        'severity': 'high',
        'description': 'Detects exposed secrets such as credentials or tokens.',
        'runtime_params': {},
        'metadata': {'recommended': True, 'why': 'Prevent credential leaks'},
        'requires_model': False,
    },
    {
        'hub_uri': 'hub://guardrails/nsfw_text',
        'validator_class': 'NSFWText',
        'name': 'NSFW Text',
        'category': 'content_safety',
        'severity': 'medium',
        'description': 'Detects NSFW text using a Guardrails Hub validator.',
        'runtime_params': {'threshold': 0.8, 'validation_method': 'sentence'},
        'metadata': {'recommended': True, 'why': 'Content safety'},
        'requires_model': True,
    },
]


def _class_is_importable(validator_class: str) -> bool:
    _ensure_user_site()
    try:
        hub_module = importlib.import_module('guardrails.hub')
        if hasattr(hub_module, validator_class):
            return True
    except Exception:
        pass

    for item in get_hub_validator_catalog():
        if item['validator_class'] != validator_class:
            continue
        try:
            module = importlib.import_module(_module_name_from_hub_uri(item['hub_uri']))
            return hasattr(module, validator_class)
        except Exception:
            return False
    return False


def _module_name_from_hub_uri(hub_uri: str) -> str:
    validator_id = hub_uri.replace('hub://', '')
    namespace, package = validator_id.split('/', 1)
    return f'{namespace}_grhub_{package}'.replace('-', '_')


def _guardrails_command() -> str | None:
    return shutil.which('guardrails') or str(Path(sys.executable).with_name('guardrails'))


def _ensure_user_site() -> str:
    user_site = site.getusersitepackages()
    Path(user_site).mkdir(parents=True, exist_ok=True)
    if user_site not in sys.path:
        sys.path.insert(0, user_site)
    return user_site


def _class_name_from_slug(slug: str) -> str:
    overrides = {
        'detect_pii': 'DetectPII',
        'guardrails_pii': 'GuardrailsPII',
        'llm_rag_evaluator': 'LLMRAGEvaluator',
        'nsfw_text': 'NSFWText',
        'qa_relevance_llm_eval': 'QARelevanceLLMEval',
        'toxic_language_llm': 'ToxicLanguageLLM',
        'valid_json': 'ValidJson',
        'valid_sql': 'ValidSQL',
        'valid_url': 'ValidURL',
    }
    if slug in overrides:
        return overrides[slug]
    return ''.join(part.capitalize() for part in slug.replace('-', '_').split('_') if part)


def _name_from_slug(slug: str) -> str:
    return ' '.join(part.upper() if part in {'api', 'csv', 'html', 'json', 'llm', 'nsfw', 'pii', 'qa', 'rag', 'sql', 'url'} else part.capitalize() for part in slug.split('_'))


def _category_from_slug(slug: str) -> str:
    if any(term in slug for term in ['jailbreak', 'injection', 'unusual_prompt']):
        return 'jailbreaking'
    if any(term in slug for term in ['pii', 'secret']):
        return 'privacy'
    if any(term in slug for term in ['toxic', 'nsfw', 'profanity', 'sensitive']):
        return 'content_safety'
    if any(term in slug for term in ['bias', 'fair']):
        return 'fairness'
    if any(term in slug for term in ['hallucination', 'provenance', 'grounded', 'rag', 'relevance', 'factual']):
        return 'factuality'
    if any(term in slug for term in ['json', 'schema', 'valid_', 'openapi']):
        return 'formatting'
    return 'guardrails_hub'


def _severity_from_category(category: str) -> str:
    return 'high' if category in {'jailbreaking', 'privacy', 'content_safety', 'fairness', 'factuality'} else 'medium'


def _validator_from_hub_link(namespace: str, slug: str) -> Dict[str, Any]:
    category = _category_from_slug(slug)
    return {
        'hub_uri': f'hub://{namespace}/{slug}',
        'validator_class': _class_name_from_slug(slug),
        'name': _name_from_slug(slug),
        'category': category,
        'severity': _severity_from_category(category),
        'description': 'Guardrails Hub validator discovered from the live Hub catalog.',
        'runtime_params': {},
        'metadata': {'hub_source': 'live'},
        'requires_model': False,
    }


def _merge_catalog_items(*catalogs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: dict[str, Dict[str, Any]] = {}
    for catalog in catalogs:
        for item in catalog:
            hub_uri = item.get('hub_uri')
            if not hub_uri:
                continue
            merged[hub_uri] = {**merged.get(hub_uri, {}), **item}
    return sorted(merged.values(), key=lambda item: (not item.get('metadata', {}).get('recommended'), item.get('name', '')))


def _hydrate_validator_detail(client: httpx.Client, item: Dict[str, Any]) -> Dict[str, Any]:
    namespace, slug = item['hub_uri'].replace('hub://', '').split('/', 1)
    try:
        response = client.get(HUB_DETAIL_URL.format(namespace=namespace, validator=slug))
        response.raise_for_status()
    except Exception:
        return item

    text = html.unescape(response.text)
    class_match = re.search(r'from\s+guardrails\.hub\s+import\s+([A-Za-z_][A-Za-z0-9_]*)', text)
    install_match = re.search(r'guardrails\s+hub\s+install\s+(hub://[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', text)
    description_match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', text)
    title_match = re.search(r'<title>([^<|]+)', text)

    hydrated = dict(item)
    if class_match:
        hydrated['validator_class'] = class_match.group(1)
    if install_match:
        hydrated['hub_uri'] = install_match.group(1)
    if description_match:
        hydrated['description'] = description_match.group(1).strip()
    if title_match:
        hydrated['name'] = title_match.group(1).replace('- Validator Details', '').strip()
    hydrated['metadata'] = {**hydrated.get('metadata', {}), 'hub_source': 'live_detail'}
    return hydrated


def _fetch_live_hub_catalog() -> List[Dict[str, Any]]:
    with httpx.Client(timeout=8.0, follow_redirects=True) as client:
        response = client.get(HUB_PAGE_URL)
        response.raise_for_status()
        pairs = sorted(set(re.findall(r'href="/hub/hub/validator/([^"/]+)/([^"#?]+)"', response.text)))
        discovered = [_validator_from_hub_link(namespace, slug) for namespace, slug in pairs]
        recommended_uris = {item['hub_uri'] for item in RECOMMENDED_HUB_VALIDATORS}
        hydrated = [
            _hydrate_validator_detail(client, item)
            for item in discovered
            if item['hub_uri'] in recommended_uris
        ]
        return _merge_catalog_items(discovered, hydrated)


def get_hub_validator_catalog(force_refresh: bool = False) -> List[Dict[str, Any]]:
    cache_age = time.time() - float(_catalog_cache.get('loaded_at') or 0.0)
    cached = _catalog_cache.get('validators')
    if cached is not None and not force_refresh and cache_age < 900:
        return cached

    try:
        live_catalog = _fetch_live_hub_catalog()
        catalog = _merge_catalog_items(live_catalog, RECOMMENDED_HUB_VALIDATORS)
        _catalog_cache.update({'loaded_at': time.time(), 'validators': catalog, 'source': 'live'})
        return catalog
    except Exception:
        catalog = _merge_catalog_items(RECOMMENDED_HUB_VALIDATORS)
        _catalog_cache.update({'loaded_at': time.time(), 'validators': catalog, 'source': 'fallback'})
        return catalog


def list_hub_validators() -> List[Dict[str, Any]]:
    with tracer.start_as_current_span('guardrails_hub.catalog'):
        catalog = get_hub_validator_catalog()
        return [
            {
                **item,
                'installed': _class_is_importable(item['validator_class']),
                'token_required': True,
                'token_configured': bool(Settings.GUARDRAILS_TOKEN),
            }
            for item in catalog
        ]


def _configure_guardrails_token() -> None:
    if not Settings.GUARDRAILS_TOKEN:
        return

    home = Path.home()
    rc_path = home / '.guardrailsrc'
    rc_path.write_text(
        '\n'.join([
            'id=responsible-ai-enterprise-ready',
            f'token={Settings.GUARDRAILS_TOKEN}',
            'enable_metrics=false',
            'use_remote_inferencing=false',
        ]),
        encoding='utf-8',
    )
    rc_path.chmod(0o600)


def _friendly_install_error(stderr: str) -> str:
    text = stderr or ''
    if '401' in text or 'Unauthorized' in text or 'token is invalid' in text:
        return (
            'Guardrails Hub requires a valid Guardrails Hub token to install validators. '
            'Set GUARDRAILS_TOKEN from https://guardrailsai.com/hub/keys, then redeploy the backend.'
        )
    return text[-2000:] or 'Install failed.'


def install_hub_validator(hub_uri: str, install_local_models: bool = False) -> Dict[str, Any]:
    catalog_item = next((item for item in get_hub_validator_catalog() if item['hub_uri'] == hub_uri), None)
    if catalog_item is None:
        if not hub_uri.startswith('hub://') or '/' not in hub_uri.replace('hub://', ''):
            return {'status': 'error', 'hub_uri': hub_uri, 'error': 'Validator is not a valid Guardrails Hub URI'}
        slug = hub_uri.rsplit('/', 1)[-1]
        catalog_item = _validator_from_hub_link(hub_uri.replace('hub://', '').split('/', 1)[0], slug)

    if not Settings.GUARDRAILS_TOKEN:
        return {
            'status': 'token_required',
            'hub_uri': hub_uri,
            'installed': False,
            'error': (
                'Guardrails Hub validator installation requires a Guardrails Hub token. '
                'Create one at https://guardrailsai.com/hub/keys and set GUARDRAILS_TOKEN in the backend environment.'
            ),
        }

    command = _guardrails_command()
    if not command:
        return {'status': 'error', 'hub_uri': hub_uri, 'error': 'guardrails CLI is not available in PATH'}

    args = [command, 'hub', 'install', hub_uri]
    args.append('--install-local-models' if install_local_models else '--no-install-local-models')

    with tracer.start_as_current_span('guardrails_hub.install') as span:
        span.set_attribute('guardrails.hub_uri', hub_uri)
        venv_bin = str(Path(sys.executable).parent)
        user_site = _ensure_user_site()
        python_path = os.pathsep.join(
            path for path in [user_site, os.environ.get('PYTHONPATH', '')] if path
        )
        install_env = {
            **os.environ,
            'PATH': venv_bin + os.pathsep + os.environ.get('PATH', ''),
            'VIRTUAL_ENV': sys.prefix,
            'GUARDRAILS_INSTALLER': 'pip',
            'PIP_USER': '1',
            'PYTHONPATH': python_path,
        }
        try:
            _configure_guardrails_token()
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                env=install_env,
            )
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'hub_uri': hub_uri, 'error': 'Installation timed out'}
        except Exception as exc:
            return {'status': 'error', 'hub_uri': hub_uri, 'error': str(exc)}

    importlib.invalidate_caches()
    installed = _class_is_importable(catalog_item['validator_class'])
    return {
        'status': 'installed' if completed.returncode == 0 and installed else 'error',
        'hub_uri': hub_uri,
        'validator_class': catalog_item['validator_class'],
        'installed': installed,
        'returncode': completed.returncode,
        'stdout': completed.stdout[-2000:],
        'stderr': completed.stderr[-2000:],
        'error': None if completed.returncode == 0 and installed else _friendly_install_error(completed.stderr),
    }
