import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import joinedload

from app.database import (
    PolicyAuditEvent,
    RuntimePolicyDecision,
    SafetyPolicy,
    SafetyPolicyHubValidator,
    SafetyPolicyPattern,
    SessionLocal,
    hash_text,
)
from app.telemetry import tracer

POLICY_STATUSES = {'draft', 'review', 'approved', 'active', 'deprecated'}


def _serialize_policy(policy: SafetyPolicy) -> Dict[str, Any]:
    return {
        'id': policy.id,
        'name': policy.name,
        'category': policy.category,
        'severity': policy.severity,
        'description': policy.description,
        'policy_kind': policy.policy_kind,
        'status': policy.status,
        'enabled': policy.enabled,
        'version': policy.version,
        'source': policy.source,
        'approved_by': policy.approved_by,
        'approved_at': policy.approved_at.isoformat() + 'Z' if policy.approved_at else None,
        'activated_at': policy.activated_at.isoformat() + 'Z' if policy.activated_at else None,
        'created_at': policy.created_at.isoformat() + 'Z',
        'updated_at': policy.updated_at.isoformat() + 'Z',
        'patterns': [
            {
                'id': item.id,
                'pattern': item.pattern,
                'label': item.label,
                'is_case_sensitive': item.is_case_sensitive,
            }
            for item in policy.patterns
        ],
        'hub_validators': [
            {
                'id': item.id,
                'hub_uri': item.hub_uri,
                'validator_class': item.validator_class,
                'install_local_models': item.install_local_models,
                'runtime_params': _loads_json(item.runtime_params, {}),
                'metadata': _loads_json(item.metadata_json, {}),
            }
            for item in policy.hub_validators
        ],
    }


def _loads_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _audit(session, policy_id: int | None, action: str, actor: str, details: Dict[str, Any]) -> None:
    with tracer.start_as_current_span('audit_insert'):
        session.add(
            PolicyAuditEvent(
                policy_id=policy_id,
                action=action,
                actor=actor or 'system',
                event_hash=hash_text(json.dumps(details, sort_keys=True)),
                details=json.dumps(details, sort_keys=True),
            )
        )


def _replace_patterns(policy: SafetyPolicy, payload: Dict[str, Any]) -> None:
    patterns = payload.get('patterns', [])
    policy.patterns.clear()
    for pattern in patterns:
        if isinstance(pattern, str):
            pattern = {'pattern': pattern}
        policy.patterns.append(
            SafetyPolicyPattern(
                pattern=str(pattern.get('pattern', '')).strip(),
                label=str(pattern.get('label', '')).strip(),
                is_case_sensitive=bool(pattern.get('is_case_sensitive', False)),
            )
        )


def _replace_hub_validators(policy: SafetyPolicy, payload: Dict[str, Any]) -> None:
    validators = payload.get('hub_validators', [])
    policy.hub_validators.clear()
    for validator in validators:
        policy.hub_validators.append(
            SafetyPolicyHubValidator(
                hub_uri=str(validator.get('hub_uri', '')).strip(),
                validator_class=str(validator.get('validator_class', '')).strip(),
                install_local_models=bool(validator.get('install_local_models', False)),
                runtime_params=json.dumps(validator.get('runtime_params', {}), sort_keys=True),
                metadata_json=json.dumps(validator.get('metadata', {}), sort_keys=True),
            )
        )


def list_policies() -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        records = (
            session.query(SafetyPolicy)
            .options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators))
            .order_by(SafetyPolicy.updated_at.desc(), SafetyPolicy.id.desc())
            .all()
        )
        return [_serialize_policy(item) for item in records]


def active_policies() -> List[Dict[str, Any]]:
    with tracer.start_as_current_span('policy_load'):
        with SessionLocal() as session:
            records = (
                session.query(SafetyPolicy)
                .options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators))
                .filter(
                    SafetyPolicy.enabled.is_(True),
                    SafetyPolicy.status == 'active',
                )
                .order_by(SafetyPolicy.id.asc())
                .all()
            )
            return [_serialize_policy(item) for item in records]


def create_policy(payload: Dict[str, Any], actor: str = 'ui') -> Dict[str, Any]:
    hub_validators = payload.get('hub_validators', [])
    if payload.get('policy_kind') == 'guardrails_hub' and hub_validators:
        existing = get_policy_by_hub_uri(str(hub_validators[0].get('hub_uri', '')).strip())
        if existing:
            return {**existing, 'reused_existing': True}

    policy = SafetyPolicy(
        name=str(payload.get('name', '')).strip(),
        category=str(payload.get('category', '')).strip(),
        severity=str(payload.get('severity', 'medium')).strip() or 'medium',
        description=str(payload.get('description', '')).strip(),
        policy_kind=str(payload.get('policy_kind', 'regex')).strip() or 'regex',
        status='draft',
        enabled=bool(payload.get('enabled', True)),
        source=str(payload.get('source', 'manual')).strip() or 'manual',
    )
    _replace_patterns(policy, payload)
    _replace_hub_validators(policy, payload)
    with SessionLocal() as session:
        session.add(policy)
        session.flush()
        _audit(session, policy.id, 'create', actor, {'status': 'draft', 'name': policy.name})
        session.commit()
        session.refresh(policy)
        return _serialize_policy(policy)


def get_policy_by_hub_uri(hub_uri: str) -> Dict[str, Any] | None:
    if not hub_uri:
        return None
    with SessionLocal() as session:
        policy = (
            session.query(SafetyPolicy)
            .join(SafetyPolicyHubValidator)
            .options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators))
            .filter(SafetyPolicyHubValidator.hub_uri == hub_uri)
            .order_by(SafetyPolicy.status == 'active', SafetyPolicy.updated_at.desc(), SafetyPolicy.id.desc())
            .first()
        )
        return _serialize_policy(policy) if policy else None


def update_policy(policy_id: int, payload: Dict[str, Any], actor: str = 'ui') -> Dict[str, Any]:
    with SessionLocal() as session:
        policy = session.query(SafetyPolicy).options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators)).filter_by(id=policy_id).one()
        previous = _serialize_policy(policy)
        policy.name = str(payload.get('name', policy.name)).strip()
        policy.category = str(payload.get('category', policy.category)).strip()
        policy.severity = str(payload.get('severity', policy.severity)).strip() or policy.severity
        policy.description = str(payload.get('description', policy.description)).strip()
        policy.policy_kind = str(payload.get('policy_kind', policy.policy_kind)).strip() or policy.policy_kind
        policy.enabled = bool(payload.get('enabled', policy.enabled))
        requested_status = str(payload.get('status', policy.status)).strip()
        if requested_status in POLICY_STATUSES and requested_status != 'active':
            policy.status = requested_status
        if 'patterns' in payload:
            _replace_patterns(policy, payload)
        if 'hub_validators' in payload:
            _replace_hub_validators(policy, payload)
        policy.version += 1
        _audit(session, policy.id, 'update', actor, {'before': previous, 'after_status': policy.status})
        session.commit()
        session.refresh(policy)
        return _serialize_policy(policy)


def delete_policy(policy_id: int, actor: str = 'ui') -> Dict[str, Any]:
    with SessionLocal() as session:
        policy = session.query(SafetyPolicy).options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators)).filter_by(id=policy_id).one()
        snapshot = _serialize_policy(policy)
        _audit(session, policy.id, 'delete', actor, {'policy': snapshot})
        session.delete(policy)
        session.commit()
        return {'deleted': True, 'policy_id': policy_id}


def approve_policy(policy_id: int, actor: str = 'ui') -> Dict[str, Any]:
    with SessionLocal() as session:
        policy = session.query(SafetyPolicy).options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators)).filter_by(id=policy_id).one()
        policy.status = 'approved'
        policy.approved_by = actor or 'ui'
        policy.approved_at = datetime.utcnow()
        policy.version += 1
        _audit(session, policy.id, 'approve', actor, {'status': 'approved'})
        session.commit()
        session.refresh(policy)
        return _serialize_policy(policy)


def activate_policy(policy_id: int, actor: str = 'ui') -> Dict[str, Any]:
    with SessionLocal() as session:
        policy = session.query(SafetyPolicy).options(joinedload(SafetyPolicy.patterns), joinedload(SafetyPolicy.hub_validators)).filter_by(id=policy_id).one()
        if policy.status != 'approved':
            raise ValueError('Only approved policies can become active')
        policy.status = 'active'
        policy.enabled = True
        policy.activated_at = datetime.utcnow()
        policy.version += 1
        _audit(session, policy.id, 'activate', actor, {'status': 'active'})
        session.commit()
        session.refresh(policy)
        return _serialize_policy(policy)


def record_runtime_decision(decision: Dict[str, Any]) -> None:
    with SessionLocal() as session:
        session.add(
            RuntimePolicyDecision(
                input_hash=hash_text(decision.get('message', '')),
                stage=str(decision.get('stage', 'input')),
                blocked=bool(decision.get('blocked', False)),
                risk_level=str(decision.get('risk_level', 'low')),
                matched_categories=json.dumps(decision.get('matched_categories', [])),
                matched_patterns=json.dumps(decision.get('matched_patterns', [])),
                policy_version=str(decision.get('policy_version', 'none')),
                validator_engine=str(decision.get('validator_engine', 'regex_fallback')),
            )
        )
        session.commit()


def summarize_policy_test(result: Dict[str, Any]) -> Dict[str, Any]:
    return result
