import json
import uuid
from datetime import datetime
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.auth import (
    AuthenticatedUser,
    auth_runtime_config,
    get_current_user,
    require_aiops_viewer,
    require_finops_viewer,
    require_policy_manager,
    user_can_manage_policies,
    user_can_view_aiops,
    user_can_view_finops,
)
from app.config import Settings
from app.database import (
    append_audit_event,
    append_guardrail_violations,
    engine,
    get_aiops_summary,
    get_audit_block_stats,
    get_eval_metrics_summary,
    get_finops_summary,
    get_safety_metrics_summary,
    get_guardrail_report,
    get_policy_payload,
    get_recent_audit_events,
    get_user_audit_events,
    init_database,
    upsert_user_profile,
)
from app.guardrails_hub_catalog import install_hub_validator, list_hub_validators
from app.schemas import (
    AuditEvent,
    ChatRequest,
    ChatResponse,
    MetadataResponse,
    PolicyActionRequest,
    PolicyResponse,
    PolicyTestRequest,
    ResponsibleAIResponse,
    SafetyHubValidatorInstallRequest,
    SafetyPolicyCreate,
    SafetyHubPolicyImport,
    SafetyPolicyUpdate,
    UsageMetadata,
)
from app.llm_client import bind_request_context, llm_client, reset_request_context
from app.responsible_ai import (
    evaluate_privacy as code_privacy,
    evaluate_safety as code_safety,
    evaluate_fairness as code_fairness,
    evaluate_explainability as code_explainability,
    evaluate_verifiability as code_verifiability,
    evaluate_transparency as code_transparency,
    evaluate_governance as code_governance,
    evaluate_controllability as code_controllability
)
from app.framework_mode import (
    evaluate_observability,
    trace_llm_call,
    evaluate_privacy as framework_privacy,
    evaluate_safety as framework_safety,
    evaluate_explainability as framework_explainability,
    evaluate_fairness as framework_fairness
)
from app.framework_mode.guardrails_safety import (
    get_active_policy_version,
    get_validator_health,
    reload_safety_policies,
    test_safety_policy,
)
from app.framework_mode.langfuse_observability import is_langfuse_configured
from app.policy_governance import (
    activate_policy,
    approve_policy,
    create_policy,
    delete_policy,
    get_auto_disable_reasons,
    list_policies,
    update_policy,
)
from app.telemetry import get_tracing_status, instrument_sqlalchemy, setup_tracing, tracer

app = FastAPI(title=Settings.PROJECT_NAME, version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=Settings.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'],
    allow_headers=['Content-Type', 'Authorization', 'Accept', 'Origin'],
    expose_headers=['*'],
    max_age=3600
)


@app.on_event('startup')
def startup_event():
    setup_tracing(app)
    instrument_sqlalchemy(engine)
    init_database()
    reload_safety_policies()


@app.on_event('shutdown')
async def shutdown_event():
    await llm_client.close()


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'responsible-ai-chat-agent'}


@app.get('/gateway/health')
async def gateway_health(user: AuthenticatedUser = Depends(get_current_user)):
    """Live check of the LLM egress path (LiteLLM proxy reachability and models)."""
    return await llm_client.health()


@app.get('/gateway/models')
async def gateway_models(user: AuthenticatedUser = Depends(get_current_user)):
    try:
        models = await llm_client.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'LLM gateway is not reachable: {exc}') from exc
    if Settings.LLM_ALLOWED_MODELS:
        models = [model for model in models if model in Settings.LLM_ALLOWED_MODELS]
    return {
        'default_model': llm_client.default_model,
        'judge_model': llm_client.judge_model,
        'models': models,
        'gateway_mode': llm_client.mode,
    }


@app.get('/')
def root():
    return {
        'service': 'responsible-ai-chat-agent',
        'status': 'ok',
        'links': {
            'health': '/health',
            'observability': '/observability',
            'policy': '/policy',
            'audit': '/audit',
            'docs': '/docs'
        }
    }


@app.get('/observability')
def observability():
    return get_tracing_status()


async def _proxy_jaeger(request: Request, path: str = ''):
    target_path = f'/jaeger/{path}'.rstrip('/')
    target_url = f'http://127.0.0.1:16686{target_path}'
    if request.url.query:
        target_url = f'{target_url}?{request.url.query}'

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            proxied = await client.request(
                request.method,
                target_url,
                headers={'accept': request.headers.get('accept', '*/*')},
                content=await request.body(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f'Jaeger UI is not available: {exc}') from exc

    headers = {
        key: value
        for key, value in proxied.headers.items()
        if key.lower() in {'content-type', 'cache-control', 'location'}
    }
    return Response(content=proxied.content, status_code=proxied.status_code, headers=headers)


@app.api_route('/jaeger', methods=['GET', 'POST'])
async def jaeger_root(request: Request):
    return await _proxy_jaeger(request)


@app.api_route('/jaeger/{path:path}', methods=['GET', 'POST'])
async def jaeger_proxy(path: str, request: Request):
    return await _proxy_jaeger(request, path)


def _risk_level(*results):
    levels = [
        item.get('risk_level') or item.get('safety_risk') or item.get('privacy_risk')
        for item in results
        if isinstance(item, dict)
    ]
    if 'high' in levels:
        return 'high'
    if 'medium' in levels:
        return 'medium'
    return 'low'


def _extract_violation_records(request, user, metadata, safety_result):
    records = []
    if not isinstance(safety_result, dict):
        return records

    stage_payloads = [
        ('input', safety_result.get('policy_violations', []), safety_result.get('blocked', False)),
        (
            'output',
            safety_result.get('output_policy_violations', []),
            safety_result.get('output_blocked', False),
        ),
    ]
    for stage, violations, blocked in stage_payloads:
        for violation in violations or []:
            records.append({
                'request_id': metadata.request_id,
                'user_id': user.user_id,
                'user_email': user.email,
                'tenant_id': user.tenant_id,
                'client_id': request.client_id,
                'agent_id': request.agent_id,
                'stage': stage,
                'category': violation.get('category', 'unknown'),
                'severity': violation.get('severity', 'medium'),
                'blocked': blocked,
                'policy_version': safety_result.get('policy_version', 'none'),
                'matched_patterns': violation.get('patterns', []),
                'details': violation,
            })
    return records


@app.post('/chat', response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    requested_model = llm_client.resolve_model(request.model, 'chat')
    if not llm_client.model_allowed(requested_model):
        raise HTTPException(
            status_code=400,
            detail=f'Model {requested_model!r} is not in the gateway allowlist: {Settings.LLM_ALLOWED_MODELS}',
        )
    request.model = requested_model

    # Bind caller identity once so every model call in this request (answer +
    # judge calls) is metered against the same user/tenant/request.
    gateway_request_id = str(uuid.uuid4())
    context_token = bind_request_context(
        request_id=gateway_request_id,
        user_id=user.user_id,
        user_email=user.email,
        tenant_id=user.tenant_id,
        client_id=request.client_id,
        agent_id=request.agent_id,
        session_id=request.session_id,
        mode=request.mode.value,
    )
    try:
        return await _chat(request, user, gateway_request_id)
    finally:
        reset_request_context(context_token)


async def _chat(request: ChatRequest, user: AuthenticatedUser, gateway_request_id: str) -> ChatResponse:
    with tracer.start_as_current_span('chat.request') as span:
        upsert_user_profile(user)
        span.set_attribute('chat.mode', request.mode.value)
        span.set_attribute('chat.model', request.model)
        span.set_attribute('chat.temperature', request.temperature)
        span.set_attribute('chat.max_tokens', request.max_tokens)
        span.set_attribute('chat.request_id', gateway_request_id)
        span.set_attribute('enduser.id', user.user_id)
        span.set_attribute('tenant.id', user.tenant_id)
        span.set_attribute('client.id', request.client_id)
        span.set_attribute('agent.id', request.agent_id)

        llm_message = request.message
        privacy_result = None
        safety_result = None
        response = None
        if request.mode == 'framework':
            with tracer.start_as_current_span('privacy_input_check'):
                privacy_result = framework_privacy(request.message)
                llm_message = privacy_result.get('redacted_text') or request.message
                span.set_attribute('privacy.input_redacted', privacy_result.get('redacted', False))
                span.set_attribute('privacy.input_findings_count', privacy_result.get('findings_count', 0))

            with tracer.start_as_current_span('safety_input_check') as safety_span:
                safety_result = framework_safety(llm_message, stage='input')
                safety_span.set_attribute('safety.input_blocked', safety_result.get('blocked', False))
                safety_span.set_attribute('safety.input_risk', safety_result.get('safety_risk', 'unknown'))
                safety_span.set_attribute('safety.engine', safety_result.get('safety_engine', 'unknown'))

            if safety_result.get('blocked'):
                response = {
                    'answer': (
                        'I cannot help with that request because it appears to violate '
                        'the application safety policy. Please reframe it toward a lawful, '
                        'defensive, or educational banking use case.'
                    ),
                    'provider': 'guardrails-policy',
                    'model': request.model,
                    'request_id': gateway_request_id,
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'tokens': 0,
                    'status': 'blocked',
                    'metadata': {'blocked_by': 'guardrails_ai_safety_policy'}
                }

        if response is None:
            with tracer.start_as_current_span('llm_gateway_call') as llm_span:
                response = await llm_client.chat(
                    llm_message,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    observe=request.mode == 'framework',
                )
                # Keep one request id across the audit event, the usage rows and
                # the client-visible metadata.
                response['request_id'] = gateway_request_id
                llm_span.set_attribute('llm.gateway_mode', llm_client.mode)
                llm_span.set_attribute('llm.provider', response.get('provider', 'unknown'))
                llm_span.set_attribute('llm.model', response.get('served_model') or request.model)
                llm_span.set_attribute('llm.status', response.get('status', 'unknown'))
                llm_span.set_attribute('llm.total_tokens', response.get('tokens', 0))
                llm_span.set_attribute('llm.cost_usd', response.get('cost_usd') or 0.0)
                llm_span.set_attribute('llm.latency_ms', response.get('latency_ms', 0))
                llm_span.set_attribute('llm.call_id', response.get('call_id', ''))
        answer = response.get('answer', '')
        if response.get('status') == 'success' and not (answer or '').strip():
            # Reasoning models can spend the whole token budget before emitting
            # text. Say so instead of returning an empty answer (which the output
            # checks would otherwise have nothing to evaluate).
            answer = (
                f"The model returned no text (finish_reason={response.get('finish_reason') or 'unknown'}, "
                f"max_tokens={request.max_tokens}). The token budget was used before an answer was produced; "
                'increase max_tokens and try again.'
            )
            response['empty_answer'] = True

        if request.mode == 'framework':
            with tracer.start_as_current_span('privacy_output_check') as output_privacy_span:
                output_privacy_result = framework_privacy(answer)
                if output_privacy_result.get('redacted'):
                    answer = output_privacy_result.get('redacted_text', answer)
                privacy_result.update({
                    'output_privacy_risk': output_privacy_result.get('privacy_risk'),
                    'output_detected_sensitive_terms': output_privacy_result.get('detected_sensitive_terms', []),
                    'output_findings_count': output_privacy_result.get('findings_count', 0),
                    'output_redacted': output_privacy_result.get('redacted', False)
                })
                output_privacy_span.set_attribute('privacy.output_redacted', output_privacy_result.get('redacted', False))
                output_privacy_span.set_attribute('privacy.output_findings_count', output_privacy_result.get('findings_count', 0))
            with tracer.start_as_current_span('observability_check'):
                observability_info = evaluate_observability(llm_message)
            with tracer.start_as_current_span('safety_output_check') as safety_output_span:
                output_safety_result = framework_safety(answer, stage='output')
                if output_safety_result.get('blocked') and response.get('provider') != 'guardrails-policy':
                    answer = (
                        'The generated response was blocked because it violated the '
                        'application safety policy.'
                    )
                safety_result.update({
                    'output_safety_risk': output_safety_result.get('safety_risk'),
                    'output_violations': output_safety_result.get('violations', []),
                    'output_policy_violations': output_safety_result.get('policy_violations', []),
                    'output_blocked': output_safety_result.get('blocked', False)
                })
                safety_output_span.set_attribute('safety.output_blocked', output_safety_result.get('blocked', False))
                safety_output_span.set_attribute('safety.output_risk', output_safety_result.get('safety_risk', 'unknown'))
            with tracer.start_as_current_span('fairness_check'):
                fairness_result = await framework_fairness(answer)
            with tracer.start_as_current_span('explainability_check'):
                explainability_result = await framework_explainability(answer)
            with tracer.start_as_current_span('verifiability_check'):
                verifiability_result = {
                    'verifiability_score': 0.8,
                    'recommendation': 'Use open-source audits when available'
                }
            with tracer.start_as_current_span('transparency_check'):
                transparency_result = {
                    'transparency_level': 'high' if observability_info.get('observability') == 'enabled' else 'partial',
                    'recommendation': observability_info.get('recommendation', 'Capture and expose trace metadata')
                }
            with tracer.start_as_current_span('governance_check'):
                governance_result = {
                    'governance_concern': 'medium',
                    'recommendation': 'Enable policy enforcement with frameworks'
                }
            with tracer.start_as_current_span('controllability_check'):
                controllability_result = {
                    'controllability_properties': ['mode', 'temperature', 'max_tokens'],
                    'recommendation': 'Keep explicit controls'
                }
        else:
            with tracer.start_as_current_span('privacy_check'):
                privacy_result = code_privacy(request.message)
            with tracer.start_as_current_span('safety_check'):
                safety_result = code_safety(request.message)
            with tracer.start_as_current_span('fairness_check'):
                fairness_result = code_fairness(request.message, answer)
            with tracer.start_as_current_span('explainability_check'):
                explainability_result = code_explainability(answer)
            with tracer.start_as_current_span('verifiability_check'):
                verifiability_result = code_verifiability(answer)
            with tracer.start_as_current_span('transparency_check'):
                transparency_result = code_transparency(answer)
            with tracer.start_as_current_span('governance_check'):
                governance_result = code_governance(request.message)
            with tracer.start_as_current_span('controllability_check'):
                controllability_result = code_controllability(request.message)

        responsible_ai = ResponsibleAIResponse(
            privacy=privacy_result,
            safety=safety_result,
            fairness=fairness_result,
            explainability=explainability_result,
            verifiability=verifiability_result,
            transparency=transparency_result,
            governance=governance_result,
            controllability=controllability_result
        )

        if request.mode == 'framework':
            with tracer.start_as_current_span('langfuse_trace_flush'):
                trace_llm_call(
                    response.get('request_id', ''),
                    {
                        'message': llm_message,
                        'original_message_redacted': privacy_result.get('redacted', False),
                        'model': request.model,
                        'temperature': request.temperature,
                        'max_tokens': request.max_tokens,
                        'mode': request.mode.value
                    },
                    {
                        'answer': answer,
                        'provider': response.get('provider', ''),
                        'model': response.get('model', ''),
                        'timestamp': response.get('timestamp', ''),
                        'metadata': response.get('metadata', {})
                    }
                )

        with tracer.start_as_current_span('response_metadata'):
            metadata = MetadataResponse(
                model=request.model,
                provider=response.get('provider', llm_client.provider_label),
                mode=request.mode,
                request_id=response.get('request_id', gateway_request_id),
                timestamp=(
                    datetime.fromisoformat(response.get('timestamp').replace('Z', '+00:00'))
                    if response.get('timestamp')
                    else datetime.utcnow()
                ),
                user_id=user.user_id,
                client_id=request.client_id,
                agent_id=request.agent_id,
                session_id=request.session_id,
                usage=UsageMetadata(
                    gateway=llm_client.provider_label,
                    served_model=response.get('served_model', ''),
                    prompt_tokens=response.get('prompt_tokens', 0),
                    completion_tokens=response.get('completion_tokens', 0),
                    total_tokens=response.get('tokens', 0),
                    cost_usd=response.get('cost_usd'),
                    cost_source=response.get('cost_source', 'none'),
                    latency_ms=response.get('latency_ms', 0),
                    proxy_overhead_ms=response.get('proxy_overhead_ms'),
                    retries=response.get('retries', 0),
                    fallbacks=response.get('fallbacks', 0),
                    status=response.get('status', 'success'),
                    error_type=response.get('error_type', ''),
                    finish_reason=response.get('finish_reason', ''),
                ),
            )

        risk_level = _risk_level(privacy_result, safety_result)
        blocked = bool(
            isinstance(safety_result, dict)
            and (safety_result.get('blocked') or safety_result.get('output_blocked'))
        )
        violation_records = _extract_violation_records(request, user, metadata, safety_result)
        audit = AuditEvent(
            request_id=metadata.request_id,
            timestamp=metadata.timestamp,
            mode=request.mode,
            model=request.model,
            provider=metadata.provider,
            user_id=user.user_id,
            user_email=user.email,
            tenant_id=user.tenant_id,
            client_id=request.client_id,
            agent_id=request.agent_id,
            session_id=request.session_id,
            is_cached=False,
            blocked=blocked,
            risk_level=risk_level,
            violation_count=len(violation_records),
            summary=answer[:120],
            responsible_ai=responsible_ai.dict() if hasattr(responsible_ai, 'dict') else responsible_ai
        )

        append_audit_event(json.loads(audit.json()))
        append_guardrail_violations(violation_records)

        with tracer.start_as_current_span('response_sent') as response_span:
            response_span.set_attribute('chat.request_id', metadata.request_id)
            response_span.set_attribute('chat.provider', metadata.provider)
            return ChatResponse(answer=answer, responsible_ai=responsible_ai, metadata=metadata)


@app.get('/audit')
def audit():
    return {'events': get_recent_audit_events()}


@app.get('/audit/me')
def my_audit(user: AuthenticatedUser = Depends(get_current_user)):
    return {'events': get_user_audit_events(user.user_id)}


@app.get('/reports/guardrails')
def guardrail_reports(user_id: str | None = None, user: AuthenticatedUser = Depends(get_current_user)):
    target_user_id = user_id if 'admin' in user.groups else user.user_id
    return get_guardrail_report(target_user_id)


@app.get('/reports/evaluations')
def evaluation_reports(limit: int = 200, user: AuthenticatedUser = Depends(require_policy_manager)):
    return get_eval_metrics_summary(limit)


@app.get('/reports/safety')
def safety_reports(limit: int = 200, user: AuthenticatedUser = Depends(require_policy_manager)):
    return {
        **get_safety_metrics_summary(limit),
        'validator_health': get_validator_health(),
        'active_policy_version': get_active_policy_version(),
    }


@app.get('/reports/finops')
def finops_report(days: int = 30, user: AuthenticatedUser = Depends(require_finops_viewer)):
    """Spend, tokens, unit economics and budget posture for the FinOps dashboard."""
    summary = get_finops_summary(days, monthly_budget_usd=Settings.FINOPS_MONTHLY_BUDGET_USD)
    summary['currency'] = Settings.FINOPS_CURRENCY
    summary['gateway'] = {
        'mode': llm_client.mode,
        'default_model': llm_client.default_model,
        'judge_model': llm_client.judge_model,
        'cost_system_of_record': 'litellm' if llm_client.mode == 'proxy' else 'estimated',
    }
    return summary


@app.get('/reports/aiops')
async def aiops_report(hours: int = 24, user: AuthenticatedUser = Depends(require_aiops_viewer)):
    """Reliability, latency and dependency health for the AIOps dashboard."""
    summary = get_aiops_summary(hours)
    summary['guardrails'] = get_audit_block_stats(hours)
    summary['dependencies'] = {
        'llm_gateway': await llm_client.health(),
        'tracing': get_tracing_status(),
        'langfuse': {'configured': is_langfuse_configured()},
        'database': _database_health(),
        'safety_validators': {
            'failing': len(get_validator_health()),
            'active_policy_version': get_active_policy_version(),
            'details': get_validator_health(),
        },
    }
    return summary


def _database_health() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'status': 'ok', 'dialect': engine.dialect.name}
    except Exception as exc:
        return {'status': 'error', 'dialect': engine.dialect.name, 'error': str(exc)}


@app.get('/policy', response_model=PolicyResponse)
def policy():
    # The stored policy document is seeded once; the model and provider shown
    # to clients must follow the live gateway configuration, so overlay them.
    payload = get_policy_payload()
    payload['model'] = llm_client.default_model
    payload['provider'] = llm_client.provider_label
    payload['llm_gateway'] = {
        'mode': llm_client.mode,
        'judge_model': llm_client.judge_model,
        'allowed_models': Settings.LLM_ALLOWED_MODELS,
    }
    return PolicyResponse(policy=payload)


@app.get('/auth/config')
def auth_config():
    return auth_runtime_config()


@app.get('/auth/me')
def auth_me(user: AuthenticatedUser = Depends(get_current_user)):
    return {
        'user_id': user.user_id,
        'email': user.email,
        'username': user.username,
        'tenant_id': user.tenant_id,
        'groups': list(user.groups),
        'permissions': {
            'manage_policies': user_can_manage_policies(user),
            'install_hub_validators': user_can_manage_policies(user),
            'activate_policies': user_can_manage_policies(user),
            'view_finops': user_can_view_finops(user),
            'view_aiops': user_can_view_aiops(user),
        },
    }


@app.get('/policies')
def policies(user: AuthenticatedUser = Depends(require_policy_manager)):
    # Live validator errors cover policies that are still enabled but failing to load.
    # Once a policy has been auto-disabled it is no longer compiled, so the audit trail
    # is what keeps its explanation available.
    health_by_policy = {
        item['policy_id']: item
        for item in get_validator_health()
        if item.get('policy_id')
    }
    auto_disabled = get_auto_disable_reasons()

    def _health_for(policy):
        live = health_by_policy.get(policy['id'])
        if live:
            return live
        record = auto_disabled.get(policy['id'])
        if record and not policy['enabled']:
            return {
                'policy_id': policy['id'],
                'policy_name': policy['name'],
                'validator_class': record.get('validator_class'),
                'error': record['reason'],
                'permanent': True,
                'auto_disabled_at': record['disabled_at'],
            }
        return None

    return {
        'policies': [
            {**policy, 'runtime_health': _health_for(policy)}
            for policy in list_policies()
        ]
    }


@app.post('/policies')
def policies_create(
    request: SafetyPolicyCreate,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    return {'policy': create_policy(request.dict(), actor=user.email or user.username or user.user_id)}


@app.post('/policies/import/hub')
def policies_import_hub(
    request: SafetyHubPolicyImport,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    return {
        'policy': create_policy(
            {
                'name': request.name,
                'category': request.category,
                'severity': request.severity,
                'description': request.description,
                'policy_kind': 'guardrails_hub',
                'enabled': True,
                'source': request.source or 'guardrails_hub',
                'hub_validators': [request.hub_validator.dict()],
            },
            actor=user.email or user.username or user.user_id or 'hub-import',
        )
    }


@app.get('/policies/hub/validators')
def policies_hub_validators(user: AuthenticatedUser = Depends(require_policy_manager)):
    return {'validators': list_hub_validators()}


@app.post('/policies/hub/validators/install')
def policies_hub_validators_install(
    request: SafetyHubValidatorInstallRequest,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    return install_hub_validator(request.hub_uri, request.install_local_models)


@app.put('/policies/{policy_id}')
def policies_update(
    policy_id: int,
    request: SafetyPolicyUpdate,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    try:
        policy = update_policy(
            policy_id,
            request.dict(exclude_none=True),
            actor=user.email or user.username or user.user_id,
        )
        reload_safety_policies()
        return {'policy': policy}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete('/policies/{policy_id}')
def policies_delete(
    policy_id: int,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    try:
        result = delete_policy(policy_id, actor=user.email or user.username or user.user_id)
        reload_safety_policies()
        return result
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/{policy_id}/approve')
def policies_approve(
    policy_id: int,
    request: PolicyActionRequest,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    try:
        actor = request.actor or user.email or user.username or user.user_id
        return {'policy': approve_policy(policy_id, actor)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/{policy_id}/activate')
def policies_activate(
    policy_id: int,
    request: PolicyActionRequest,
    user: AuthenticatedUser = Depends(require_policy_manager),
):
    try:
        actor = request.actor or user.email or user.username or user.user_id
        result = activate_policy(policy_id, actor)
        reload_safety_policies()
        return {'policy': result}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/reload')
def policies_reload(user: AuthenticatedUser = Depends(require_policy_manager)):
    return reload_safety_policies()


@app.post('/policies/test')
def policies_test(request: PolicyTestRequest):
    return test_safety_policy(request.message)
