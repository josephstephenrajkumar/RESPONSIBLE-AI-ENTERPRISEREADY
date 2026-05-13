import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List

from app.telemetry import tracer


HUB_VALIDATOR_CATALOG = [
    {
        'hub_uri': 'hub://guardrails/toxic_language',
        'validator_class': 'ToxicLanguage',
        'name': 'Toxic Language',
        'category': 'toxicity',
        'severity': 'high',
        'description': 'Detects toxic or abusive language using a Guardrails Hub validator.',
        'runtime_params': {'threshold': 0.5, 'validation_method': 'sentence'},
        'metadata': {},
        'requires_model': True,
    },
    {
        'hub_uri': 'hub://guardrails/detect_pii',
        'validator_class': 'DetectPII',
        'name': 'Detect PII',
        'category': 'privacy',
        'severity': 'high',
        'description': 'Detects personally identifiable information with a Guardrails Hub validator.',
        'runtime_params': {},
        'metadata': {},
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
        'metadata': {},
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
        'metadata': {},
        'requires_model': True,
    },
]


def _class_is_importable(validator_class: str) -> bool:
    try:
        hub_module = importlib.import_module('guardrails.hub')
        if hasattr(hub_module, validator_class):
            return True
    except Exception:
        pass

    for item in HUB_VALIDATOR_CATALOG:
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


def list_hub_validators() -> List[Dict[str, Any]]:
    with tracer.start_as_current_span('guardrails_hub.catalog'):
        return [
            {
                **item,
                'installed': _class_is_importable(item['validator_class']),
            }
            for item in HUB_VALIDATOR_CATALOG
        ]


def install_hub_validator(hub_uri: str, install_local_models: bool = False) -> Dict[str, Any]:
    catalog_item = next((item for item in HUB_VALIDATOR_CATALOG if item['hub_uri'] == hub_uri), None)
    if catalog_item is None:
        return {'status': 'error', 'hub_uri': hub_uri, 'error': 'Validator is not in the approved local catalog'}

    command = _guardrails_command()
    if not command:
        return {'status': 'error', 'hub_uri': hub_uri, 'error': 'guardrails CLI is not available in PATH'}

    args = [command, 'hub', 'install', hub_uri]
    args.append('--install-local-models' if install_local_models else '--no-install-local-models')

    with tracer.start_as_current_span('guardrails_hub.install') as span:
        span.set_attribute('guardrails.hub_uri', hub_uri)
        venv_bin = str(Path(sys.executable).parent)
        install_env = {
            **os.environ,
            'PATH': venv_bin + os.pathsep + os.environ.get('PATH', ''),
            'VIRTUAL_ENV': sys.prefix,
            'GUARDRAILS_INSTALLER': 'pip',
            'PYTHONNOUSERSITE': '1',
        }
        try:
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

    installed = _class_is_importable(catalog_item['validator_class'])
    return {
        'status': 'installed' if completed.returncode == 0 and installed else 'error',
        'hub_uri': hub_uri,
        'validator_class': catalog_item['validator_class'],
        'installed': installed,
        'returncode': completed.returncode,
        'stdout': completed.stdout[-2000:],
        'stderr': completed.stderr[-2000:],
    }
