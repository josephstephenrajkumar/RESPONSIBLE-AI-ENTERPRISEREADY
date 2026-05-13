import json
import uuid
from datetime import datetime
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings
from app.database import (
    append_audit_event,
    append_guardrail_violations,
    engine,
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
)
from app.groq_client import groq_client
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
from app.framework_mode.guardrails_safety import reload_safety_policies, test_safety_policy
from app.policy_governance import (
    activate_policy,
    approve_policy,
    create_policy,
    delete_policy,
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
    await groq_client.close()


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'responsible-ai-chat-agent'}


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
    with tracer.start_as_current_span('chat.request') as span:
        upsert_user_profile(user)
        span.set_attribute('chat.mode', request.mode.value)
        span.set_attribute('chat.model', request.model)
        span.set_attribute('chat.temperature', request.temperature)
        span.set_attribute('chat.max_tokens', request.max_tokens)
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
                    'request_id': str(uuid.uuid4()),
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'tokens': 0,
                    'metadata': {'blocked_by': 'guardrails_ai_safety_policy'}
                }

        if response is None:
            with tracer.start_as_current_span('groq_api_call') as groq_span:
                response = await groq_client.send_prompt(
                    llm_message,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    explain=request.explain,
                    verify=request.verify,
                    mode=request.mode.value
                )
                groq_span.set_attribute('llm.provider', response.get('provider', 'unknown'))
                groq_span.set_attribute('llm.model', response.get('model', request.model))
                groq_span.set_attribute('llm.request_id', response.get('request_id', ''))
        answer = response.get('answer', '')

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
                fairness_result = framework_fairness(answer)
            with tracer.start_as_current_span('explainability_check'):
                explainability_result = framework_explainability(answer)
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
                provider=response.get('provider', 'groq'),
                mode=request.mode,
                request_id=response.get('request_id', ''),
                timestamp=(
                    datetime.fromisoformat(response.get('timestamp').replace('Z', '+00:00'))
                    if response.get('timestamp')
                    else datetime.utcnow()
                ),
                user_id=user.user_id,
                client_id=request.client_id,
                agent_id=request.agent_id,
                session_id=request.session_id,
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


@app.get('/policy', response_model=PolicyResponse)
def policy():
    return PolicyResponse(policy=get_policy_payload())


@app.get('/policies')
def policies():
    return {'policies': list_policies()}


@app.post('/policies')
def policies_create(request: SafetyPolicyCreate):
    return {'policy': create_policy(request.dict())}


@app.post('/policies/import/hub')
def policies_import_hub(request: SafetyHubPolicyImport):
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
            actor='hub-import',
        )
    }


@app.get('/policies/hub/validators')
def policies_hub_validators():
    return {'validators': list_hub_validators()}


@app.post('/policies/hub/validators/install')
def policies_hub_validators_install(request: SafetyHubValidatorInstallRequest):
    return install_hub_validator(request.hub_uri, request.install_local_models)


@app.put('/policies/{policy_id}')
def policies_update(policy_id: int, request: SafetyPolicyUpdate):
    try:
        policy = update_policy(policy_id, request.dict(exclude_none=True))
        reload_safety_policies()
        return {'policy': policy}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete('/policies/{policy_id}')
def policies_delete(policy_id: int):
    try:
        result = delete_policy(policy_id)
        reload_safety_policies()
        return result
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/{policy_id}/approve')
def policies_approve(policy_id: int, request: PolicyActionRequest):
    try:
        return {'policy': approve_policy(policy_id, request.actor)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/{policy_id}/activate')
def policies_activate(policy_id: int, request: PolicyActionRequest):
    try:
        result = activate_policy(policy_id, request.actor)
        reload_safety_policies()
        return {'policy': result}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post('/policies/reload')
def policies_reload():
    return reload_safety_policies()


@app.post('/policies/test')
def policies_test(request: PolicyTestRequest):
    return test_safety_policy(request.message)
