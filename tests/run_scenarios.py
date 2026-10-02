#!/usr/bin/env python3
"""Runs the Responsible AI Gateway scenario suite against a live backend.

These are integration scenarios, not unit tests: every case is sent through the
real /chat (or /policies/test) endpoint so the results are persisted as audit
events and show up in the frontend Evaluation Dashboard and admin screens.

Usage:
    python tests/run_scenarios.py                     # against http://localhost:8000
    python tests/run_scenarios.py --base-url URL      # against another gateway
    python tests/run_scenarios.py --only RAGAS        # filter by id/framework
    python tests/run_scenarios.py --json results.json # also write a JSON report

See tests/README.md for what each scenario covers and how to read the results.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import httpx
except ImportError:
    sys.exit(
        'httpx is required. Run this with the backend virtualenv, e.g.\n'
        '    backend/venv/bin/python3 tests/run_scenarios.py'
    )

from scenarios import AGGREGATE_CHECKS, SCENARIOS

PASS = 'PASS'
FAIL = 'FAIL'
DEGRADED = 'DEGRADED'
ERROR = 'ERROR'

# Local ML inference (Presidio/Guardrails hub validators) plus up to three Groq
# calls per request (answer + ragas judge + trulens judge) makes these slow.
REQUEST_TIMEOUT = 300.0

# Scenario checks whose failure means "the framework fell back" rather than
# "the gateway is broken" - reported separately so a provider outage does not
# masquerade as a code defect.
_FALLBACK_MARKERS = ('not fallback', 'engine used')


def _colour(text, code):
    return f'\033[{code}m{text}\033[0m' if sys.stdout.isatty() else text


def _status_label(status):
    return {
        PASS: _colour(PASS, '32'),
        FAIL: _colour(FAIL, '31'),
        DEGRADED: _colour(DEGRADED, '33'),
        ERROR: _colour(ERROR, '31'),
    }[status]


def _evaluate(checks, payload):
    results = []
    for description, predicate in checks:
        try:
            ok = bool(predicate(payload))
        except Exception as exc:
            ok = False
            description = f'{description} (check raised {type(exc).__name__}: {exc})'
        results.append((description, ok))
    return results


def _overall_status(check_results):
    failed = [description for description, ok in check_results if not ok]
    if not failed:
        return PASS
    if all(any(marker in description for marker in _FALLBACK_MARKERS) for description in failed):
        return DEGRADED
    return FAIL


def run_scenario(client, base_url, scenario):
    started = time.time()
    try:
        if scenario['endpoint'] == 'chat':
            response = client.post(
                f'{base_url}/chat',
                json={
                    'message': scenario['prompt'],
                    'mode': 'framework',
                    'temperature': 0.2,
                    'max_tokens': 300,
                    'client_id': 'test-suite',
                    'agent_id': scenario['id'],
                    'session_id': 'scenario-run',
                },
                timeout=REQUEST_TIMEOUT,
            )
        else:
            response = client.post(
                f'{base_url}/policies/test',
                json={'message': scenario['prompt']},
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            'id': scenario['id'],
            'framework': scenario['framework'],
            'name': scenario['name'],
            'status': ERROR,
            'duration_s': round(time.time() - started, 1),
            'checks': [(f'request failed: {type(exc).__name__}: {exc}', False)],
            'response': None,
        }

    check_results = _evaluate(scenario['expect'], payload)
    return {
        'id': scenario['id'],
        'framework': scenario['framework'],
        'name': scenario['name'],
        'status': _overall_status(check_results),
        'duration_s': round(time.time() - started, 1),
        'checks': check_results,
        'response': payload,
    }


def run_aggregate_check(client, base_url, check):
    started = time.time()
    try:
        response = client.get(f'{base_url}{check["path"]}', timeout=60.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            'id': check['id'],
            'framework': check['framework'],
            'name': check['name'],
            'status': ERROR,
            'duration_s': round(time.time() - started, 1),
            'checks': [(f'request failed: {type(exc).__name__}: {exc}', False)],
            'response': None,
        }

    check_results = _evaluate(check['expect'], payload)
    return {
        'id': check['id'],
        'framework': check['framework'],
        'name': check['name'],
        'status': _overall_status(check_results),
        'duration_s': round(time.time() - started, 1),
        'checks': check_results,
        'response': payload,
    }


def print_result(result):
    print(f'\n[{_status_label(result["status"])}] {result["id"]} ({result["framework"]}) - {result["duration_s"]}s')
    print(f'        {result["name"]}')
    for description, ok in result['checks']:
        print(f'          {"PASS" if ok else "FAIL"}  {description}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', default='http://localhost:8000', help='Gateway base URL')
    parser.add_argument('--only', default='', help='Run only scenarios whose id or framework contains this string')
    parser.add_argument('--token', default='local-dev-token', help='Bearer token for authenticated endpoints')
    parser.add_argument('--json', dest='json_path', default='', help='Write a JSON report to this path')
    args = parser.parse_args()

    base_url = args.base_url.rstrip('/')
    selected = [
        scenario for scenario in SCENARIOS
        if args.only.lower() in scenario['id'].lower() or args.only.lower() in scenario['framework'].lower()
    ]

    print('=' * 78)
    print('Responsible AI Gateway - scenario suite')
    print(f'Gateway   : {base_url}')
    print(f'Started   : {datetime.now().isoformat(timespec="seconds")}')
    print(f'Scenarios : {len(selected)} of {len(SCENARIOS)}')
    print('=' * 78)

    headers = {'Authorization': f'Bearer {args.token}'}
    results = []

    with httpx.Client(headers=headers) as client:
        try:
            health = client.get(f'{base_url}/health', timeout=10.0)
            health.raise_for_status()
        except Exception as exc:
            sys.exit(
                f'\nGateway is not reachable at {base_url} ({exc}).\n'
                'Start it first:  cd backend && ./venv/bin/python3 -m uvicorn app.main:app --port 8000'
            )

        for scenario in selected:
            result = run_scenario(client, base_url, scenario)
            results.append(result)
            print_result(result)

        if len(selected) == len(SCENARIOS):
            print('\n' + '-' * 78)
            print('Aggregate / dashboard-facing checks')
            print('-' * 78)
            for check in AGGREGATE_CHECKS:
                result = run_aggregate_check(client, base_url, check)
                results.append(result)
                print_result(result)

    counts = {status: sum(1 for r in results if r['status'] == status) for status in (PASS, DEGRADED, FAIL, ERROR)}
    print('\n' + '=' * 78)
    print(f'Summary: {counts[PASS]} passed, {counts[DEGRADED]} degraded, {counts[FAIL]} failed, {counts[ERROR]} errored')
    print('=' * 78)
    if counts[DEGRADED]:
        print(
            'DEGRADED means a framework fell back to its heuristic path (usually the\n'
            'judge LLM or a validator was unavailable) rather than the gateway failing.'
        )
    print(
        '\nResults are persisted as audit events. To see them in the UI:\n'
        '  - Admin screen -> Evaluation Dashboard : Ragas/TruLens scores and trends\n'
        '  - Admin screen -> Governance Dashboard : policy counts and violations\n'
        '  - Chat screen                          : per-message responsible-AI panel'
    )

    if args.json_path:
        report = {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'base_url': base_url,
            'summary': counts,
            'results': [
                {k: v for k, v in result.items() if k != 'response'} | {'checks': [
                    {'check': description, 'passed': ok} for description, ok in result['checks']
                ]}
                for result in results
            ],
        }
        Path(args.json_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'\nJSON report written to {args.json_path}')

    return 1 if (counts[FAIL] or counts[ERROR]) else 0


if __name__ == '__main__':
    sys.exit(main())
