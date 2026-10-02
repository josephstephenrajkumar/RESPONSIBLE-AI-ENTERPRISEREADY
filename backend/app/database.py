import calendar
import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, desc, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from app.config import Settings
from app.telemetry import tracer

Base = declarative_base()

engine_kwargs = {}
if Settings.DATABASE_URL.startswith('sqlite'):
    engine_kwargs['connect_args'] = {'check_same_thread': False}

engine = create_engine(Settings.DATABASE_URL, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class PolicyConfig(Base):
    __tablename__ = 'policy_configs'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), unique=True, nullable=False, default='active')
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditEventRecord(Base):
    __tablename__ = 'audit_events'

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(80), unique=True, nullable=False, index=True)
    user_id = Column(String(160), nullable=False, default='anonymous', index=True)
    user_email = Column(String(320), nullable=False, default='')
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    client_id = Column(String(160), nullable=False, default='', index=True)
    agent_id = Column(String(160), nullable=False, default='', index=True)
    session_id = Column(String(160), nullable=False, default='', index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    mode = Column(String(40), nullable=False)
    model = Column(String(160), nullable=False)
    provider = Column(String(80), nullable=False)
    is_cached = Column(Boolean, nullable=False, default=False)
    blocked = Column(Boolean, nullable=False, default=False, index=True)
    risk_level = Column(String(40), nullable=False, default='low', index=True)
    violation_count = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=False, default='')
    responsible_ai = Column(Text, nullable=False, default='{}')


class UserProfile(Base):
    __tablename__ = 'user_profiles'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(160), unique=True, nullable=False, index=True)
    email = Column(String(320), nullable=False, default='')
    username = Column(String(160), nullable=False, default='')
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class GuardrailViolationRecord(Base):
    __tablename__ = 'guardrail_violations'

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(80), nullable=False, index=True)
    user_id = Column(String(160), nullable=False, default='anonymous', index=True)
    user_email = Column(String(320), nullable=False, default='')
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    client_id = Column(String(160), nullable=False, default='', index=True)
    agent_id = Column(String(160), nullable=False, default='', index=True)
    stage = Column(String(40), nullable=False, default='unknown', index=True)
    category = Column(String(120), nullable=False, default='unknown', index=True)
    severity = Column(String(40), nullable=False, default='medium', index=True)
    blocked = Column(Boolean, nullable=False, default=False, index=True)
    policy_version = Column(String(120), nullable=False, default='none')
    matched_patterns = Column(Text, nullable=False, default='[]')
    details = Column(Text, nullable=False, default='{}')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class SafetyPolicy(Base):
    __tablename__ = 'safety_policies'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(160), nullable=False)
    category = Column(String(120), nullable=False, index=True)
    severity = Column(String(40), nullable=False, default='medium')
    description = Column(Text, nullable=False, default='')
    policy_kind = Column(String(40), nullable=False, default='regex', index=True)
    status = Column(String(40), nullable=False, default='draft', index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    source = Column(String(160), nullable=False, default='local')
    approved_by = Column(String(120), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    patterns = relationship('SafetyPolicyPattern', back_populates='policy', cascade='all, delete-orphan')
    hub_validators = relationship('SafetyPolicyHubValidator', back_populates='policy', cascade='all, delete-orphan')


class SafetyPolicyPattern(Base):
    __tablename__ = 'safety_policy_patterns'

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey('safety_policies.id', ondelete='CASCADE'), nullable=False, index=True)
    pattern = Column(Text, nullable=False)
    label = Column(String(160), nullable=False, default='')
    is_case_sensitive = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    policy = relationship('SafetyPolicy', back_populates='patterns')


class SafetyPolicyHubValidator(Base):
    __tablename__ = 'safety_policy_hub_validators'

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey('safety_policies.id', ondelete='CASCADE'), nullable=False, index=True)
    hub_uri = Column(String(240), nullable=False)
    validator_class = Column(String(160), nullable=False)
    install_local_models = Column(Boolean, nullable=False, default=False)
    runtime_params = Column(Text, nullable=False, default='{}')
    metadata_json = Column('metadata', Text, nullable=False, default='{}')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    policy = relationship('SafetyPolicy', back_populates='hub_validators')


class PolicyAuditEvent(Base):
    __tablename__ = 'policy_audit_events'

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey('safety_policies.id', ondelete='SET NULL'), nullable=True, index=True)
    action = Column(String(80), nullable=False, index=True)
    actor = Column(String(120), nullable=False, default='system')
    event_hash = Column(String(64), nullable=False, index=True)
    details = Column(Text, nullable=False, default='{}')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class RuntimePolicyDecision(Base):
    __tablename__ = 'runtime_policy_decisions'

    id = Column(Integer, primary_key=True, index=True)
    input_hash = Column(String(64), nullable=False, index=True)
    stage = Column(String(40), nullable=False, default='input')
    blocked = Column(Boolean, nullable=False, default=False)
    risk_level = Column(String(40), nullable=False, default='low')
    matched_categories = Column(Text, nullable=False, default='[]')
    matched_patterns = Column(Text, nullable=False, default='[]')
    policy_version = Column(String(120), nullable=False, default='none')
    validator_engine = Column(String(120), nullable=False, default='regex_fallback')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class LLMUsageEventRecord(Base):
    """One row per model call made through app.llm_client.

    A single /chat request can produce several rows (the answer plus the Ragas
    and TruLens judge calls), linked by request_id and distinguished by purpose.
    This table is the local system of record for the FinOps (cost, tokens) and
    AIOps (latency, errors, retries, fallbacks) dashboards; LiteLLM's own spend
    log is the cross-check.
    """
    __tablename__ = 'llm_usage_events'

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(80), nullable=False, default='', index=True)
    call_id = Column(String(120), nullable=False, default='')
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(String(160), nullable=False, default='anonymous', index=True)
    user_email = Column(String(320), nullable=False, default='')
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    client_id = Column(String(160), nullable=False, default='', index=True)
    agent_id = Column(String(160), nullable=False, default='', index=True)
    session_id = Column(String(160), nullable=False, default='')
    mode = Column(String(40), nullable=False, default='unknown')
    purpose = Column(String(60), nullable=False, default='chat', index=True)
    requested_model = Column(String(160), nullable=False, default='', index=True)
    served_model = Column(String(160), nullable=False, default='')
    provider = Column(String(80), nullable=False, default='')
    gateway_mode = Column(String(20), nullable=False, default='proxy')
    api_base = Column(String(320), nullable=False, default='')
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    cost_source = Column(String(20), nullable=False, default='unknown')
    latency_ms = Column(Integer, nullable=False, default=0)
    proxy_overhead_ms = Column(Integer, nullable=True)
    retries = Column(Integer, nullable=False, default=0)
    fallbacks = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default='success', index=True)
    error_type = Column(String(80), nullable=False, default='')
    http_status = Column(Integer, nullable=True)


def default_policy() -> Dict[str, Any]:
    return {
        'provider': 'litellm' if Settings.LLM_GATEWAY_MODE == 'proxy' else 'groq',
        'model': Settings.LLM_DEFAULT_MODEL,
        'allowed_modes': ['code', 'framework'],
        'privacy_filters': ['pii', 'sensitive_data'],
        'audit_retention_days': 30,
        'observability': {
            'opentelemetry': True,
            'jaeger_ui': Settings.JAEGER_UI_URL,
            'langfuse_framework_mode': True
        }
    }


def _loads_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return datetime.utcnow()
    return datetime.utcnow()


def _load_policy_seed() -> Dict[str, Any]:
    if Settings.POLICY_PATH.exists():
        try:
            return json.loads(Settings.POLICY_PATH.read_text())
        except json.JSONDecodeError:
            return default_policy()
    return default_policy()


def _load_audit_seed() -> List[Dict[str, Any]]:
    if not Settings.AUDIT_LOG_PATH.exists():
        return []

    events = []
    for line in Settings.AUDIT_LOG_PATH.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def init_database() -> Dict[str, Any]:
    Settings.POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tracer.start_as_current_span('db.init') as span:
        Base.metadata.create_all(bind=engine)
        if Settings.DATABASE_URL.startswith('sqlite'):
            _ensure_sqlite_columns()
        migrated_audit_events = 0

        with SessionLocal() as session:
            policy = session.query(PolicyConfig).filter_by(name='active').one_or_none()
            if policy is None:
                session.add(PolicyConfig(name='active', payload=json.dumps(_load_policy_seed())))

            for event in _load_audit_seed():
                request_id = event.get('request_id')
                if not request_id:
                    continue
                exists = session.query(AuditEventRecord).filter_by(request_id=request_id).first()
                if exists:
                    continue
                session.add(AuditEventRecord(
                    request_id=request_id,
                    user_id=str(event.get('user_id', 'legacy')),
                    user_email=str(event.get('user_email', '')),
                    tenant_id=str(event.get('tenant_id', 'default')),
                    client_id=str(event.get('client_id', '')),
                    agent_id=str(event.get('agent_id', '')),
                    session_id=str(event.get('session_id', '')),
                    timestamp=_parse_timestamp(event.get('timestamp')),
                    mode=str(event.get('mode', 'code')),
                    model=str(event.get('model', Settings.GROQ_MODEL)),
                    provider=str(event.get('provider', 'unknown')),
                    is_cached=bool(event.get('is_cached', False)),
                    blocked=bool(event.get('blocked', False)),
                    risk_level=str(event.get('risk_level', 'low')),
                    violation_count=int(event.get('violation_count', 0)),
                    summary=str(event.get('summary', '')),
                    responsible_ai=json.dumps(event.get('responsible_ai', {}))
                ))
                migrated_audit_events += 1

            session.commit()

        span.set_attribute('db.system', 'sqlite' if Settings.DATABASE_URL.startswith('sqlite') else 'sqlalchemy')
        span.set_attribute('db.migrated_audit_events', migrated_audit_events)
        return {'status': 'ready', 'migrated_audit_events': migrated_audit_events}


def _ensure_sqlite_columns() -> None:
    expected = {
        'safety_policies': {
            'policy_kind': "ALTER TABLE safety_policies ADD COLUMN policy_kind VARCHAR(40) NOT NULL DEFAULT 'regex'",
        },
        'audit_events': {
            'user_id': "ALTER TABLE audit_events ADD COLUMN user_id VARCHAR(160) NOT NULL DEFAULT 'anonymous'",
            'user_email': "ALTER TABLE audit_events ADD COLUMN user_email VARCHAR(320) NOT NULL DEFAULT ''",
            'tenant_id': "ALTER TABLE audit_events ADD COLUMN tenant_id VARCHAR(160) NOT NULL DEFAULT 'default'",
            'client_id': "ALTER TABLE audit_events ADD COLUMN client_id VARCHAR(160) NOT NULL DEFAULT ''",
            'agent_id': "ALTER TABLE audit_events ADD COLUMN agent_id VARCHAR(160) NOT NULL DEFAULT ''",
            'session_id': "ALTER TABLE audit_events ADD COLUMN session_id VARCHAR(160) NOT NULL DEFAULT ''",
            'blocked': "ALTER TABLE audit_events ADD COLUMN blocked BOOLEAN NOT NULL DEFAULT 0",
            'risk_level': "ALTER TABLE audit_events ADD COLUMN risk_level VARCHAR(40) NOT NULL DEFAULT 'low'",
            'violation_count': "ALTER TABLE audit_events ADD COLUMN violation_count INTEGER NOT NULL DEFAULT 0",
        },
    }
    with engine.begin() as connection:
        for table_name, column_statements in expected.items():
            existing_columns = {
                row[1]
                for row in connection.execute(text(f'PRAGMA table_info({table_name})')).fetchall()
            }
            for column_name, statement in column_statements.items():
                if column_name not in existing_columns:
                    connection.execute(text(statement))


def get_policy_payload() -> Dict[str, Any]:
    with tracer.start_as_current_span('db.policy.get'):
        with SessionLocal() as session:
            policy = session.query(PolicyConfig).filter_by(name='active').one_or_none()
            if policy is None:
                return default_policy()
            return _loads_json(policy.payload, default_policy())


def append_audit_event(event: Dict[str, Any]) -> None:
    with tracer.start_as_current_span('audit_insert') as span:
        with SessionLocal() as session:
            record = AuditEventRecord(
                request_id=event['request_id'],
                user_id=str(event.get('user_id', 'anonymous')),
                user_email=str(event.get('user_email', '')),
                tenant_id=str(event.get('tenant_id', 'default')),
                client_id=str(event.get('client_id', '')),
                agent_id=str(event.get('agent_id', '')),
                session_id=str(event.get('session_id', '')),
                timestamp=_parse_timestamp(event.get('timestamp')),
                mode=str(event.get('mode', 'code')),
                model=str(event.get('model', Settings.GROQ_MODEL)),
                provider=str(event.get('provider', 'unknown')),
                is_cached=bool(event.get('is_cached', False)),
                blocked=bool(event.get('blocked', False)),
                risk_level=str(event.get('risk_level', 'low')),
                violation_count=int(event.get('violation_count', 0)),
                summary=str(event.get('summary', '')),
                responsible_ai=json.dumps(event.get('responsible_ai', {}))
            )
            session.add(record)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                raise
        span.set_attribute('audit.request_id', event['request_id'])


def upsert_user_profile(user: Any) -> None:
    with SessionLocal() as session:
        profile = session.query(UserProfile).filter_by(user_id=user.user_id).one_or_none()
        if profile is None:
            profile = UserProfile(user_id=user.user_id)
            session.add(profile)
        profile.email = user.email or profile.email
        profile.username = user.username or profile.username
        profile.tenant_id = user.tenant_id or profile.tenant_id
        profile.last_seen_at = datetime.utcnow()
        session.commit()


def append_guardrail_violations(records: List[Dict[str, Any]]) -> None:
    if not records:
        return
    with SessionLocal() as session:
        for item in records:
            session.add(
                GuardrailViolationRecord(
                    request_id=str(item.get('request_id', '')),
                    user_id=str(item.get('user_id', 'anonymous')),
                    user_email=str(item.get('user_email', '')),
                    tenant_id=str(item.get('tenant_id', 'default')),
                    client_id=str(item.get('client_id', '')),
                    agent_id=str(item.get('agent_id', '')),
                    stage=str(item.get('stage', 'unknown')),
                    category=str(item.get('category', 'unknown')),
                    severity=str(item.get('severity', 'medium')),
                    blocked=bool(item.get('blocked', False)),
                    policy_version=str(item.get('policy_version', 'none')),
                    matched_patterns=json.dumps(item.get('matched_patterns', [])),
                    details=json.dumps(item.get('details', {})),
                )
            )
        session.commit()


def hash_text(value: str) -> str:
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()


def get_recent_audit_events(limit: int = 25) -> List[Dict[str, Any]]:
    with tracer.start_as_current_span('db.audit.list') as span:
        safe_limit = max(1, min(limit, 100))
        with SessionLocal() as session:
            records = (
                session.query(AuditEventRecord)
                .order_by(desc(AuditEventRecord.timestamp), desc(AuditEventRecord.id))
                .limit(safe_limit)
                .all()
            )
        span.set_attribute('audit.limit', safe_limit)
        return [
            {
                'request_id': record.request_id,
                'user_id': record.user_id,
                'user_email': record.user_email,
                'tenant_id': record.tenant_id,
                'client_id': record.client_id,
                'agent_id': record.agent_id,
                'session_id': record.session_id,
                'timestamp': record.timestamp.isoformat() + 'Z',
                'mode': record.mode,
                'model': record.model,
                'provider': record.provider,
                'is_cached': record.is_cached,
                'blocked': record.blocked,
                'risk_level': record.risk_level,
                'violation_count': record.violation_count,
                'summary': record.summary,
                'responsible_ai': _loads_json(record.responsible_ai, {})
            }
            for record in records
        ]


def get_user_audit_events(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        safe_limit = max(1, min(limit, 100))
        records = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.user_id == user_id)
            .order_by(desc(AuditEventRecord.timestamp), desc(AuditEventRecord.id))
            .limit(safe_limit)
            .all()
        )
    return [
        {
            'request_id': record.request_id,
            'timestamp': record.timestamp.isoformat() + 'Z',
            'mode': record.mode,
            'model': record.model,
            'provider': record.provider,
            'client_id': record.client_id,
            'agent_id': record.agent_id,
            'session_id': record.session_id,
            'blocked': record.blocked,
            'risk_level': record.risk_level,
            'violation_count': record.violation_count,
            'summary': record.summary,
            'responsible_ai': _loads_json(record.responsible_ai, {}),
        }
        for record in records
    ]


def get_safety_metrics_summary(limit: int = 200) -> Dict[str, Any]:
    """Aggregate Guardrails safety outcomes for the admin dashboard.

    Mirrors get_eval_metrics_summary but for the safety pillar: how many requests
    were blocked, at what risk levels, and which engine actually made the call
    (guardrails_ai vs the regex fallback that runs when validators fail to load).
    """
    with tracer.start_as_current_span('db.safety.summary') as span:
        safe_limit = max(1, min(limit, 500))
        with SessionLocal() as session:
            records = (
                session.query(AuditEventRecord)
                .filter(AuditEventRecord.mode == 'framework')
                .order_by(desc(AuditEventRecord.timestamp), desc(AuditEventRecord.id))
                .limit(safe_limit)
                .all()
            )

        blocked_count = 0
        violation_total = 0
        by_risk: Dict[str, int] = {}
        by_engine: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        daily_buckets: Dict[str, Dict[str, int]] = {}
        recent: List[Dict[str, Any]] = []

        for record in records:
            responsible_ai = _loads_json(record.responsible_ai, {})
            safety = responsible_ai.get('safety', {}) or {}
            day_key = record.timestamp.date().isoformat()
            bucket = daily_buckets.setdefault(day_key, {'requests': 0, 'blocked': 0})
            bucket['requests'] += 1

            if record.blocked:
                blocked_count += 1
                bucket['blocked'] += 1
            violation_total += record.violation_count or 0

            by_risk[record.risk_level or 'unknown'] = by_risk.get(record.risk_level or 'unknown', 0) + 1
            engine = safety.get('safety_engine', 'unknown')
            by_engine[engine] = by_engine.get(engine, 0) + 1
            if safety.get('output_blocked'):
                by_stage['output'] = by_stage.get('output', 0) + 1
            elif record.blocked:
                by_stage['input'] = by_stage.get('input', 0) + 1

            if len(recent) < 50:
                recent.append({
                    'request_id': record.request_id,
                    'timestamp': record.timestamp.isoformat() + 'Z',
                    'blocked': record.blocked,
                    'risk_level': record.risk_level,
                    'violation_count': record.violation_count,
                    'safety_engine': safety.get('safety_engine'),
                    'policy_version': safety.get('policy_version'),
                })

        total = len(records)
        daily_series = [
            {'date': day, 'requests': counts['requests'], 'blocked': counts['blocked']}
            for day, counts in sorted(daily_buckets.items())
        ]

        span.set_attribute('safety.total', total)
        return {
            'total': total,
            'blocked': blocked_count,
            'block_rate': round(blocked_count / total, 3) if total else None,
            'violation_total': violation_total,
            'by_risk': by_risk,
            'by_engine': by_engine,
            'by_stage': by_stage,
            'daily_series': daily_series,
            'recent': recent,
        }


def get_eval_metrics_summary(limit: int = 200) -> Dict[str, Any]:
    with tracer.start_as_current_span('db.evaluations.summary') as span:
        safe_limit = max(1, min(limit, 500))
        with SessionLocal() as session:
            records = (
                session.query(AuditEventRecord)
                .filter(AuditEventRecord.mode == 'framework')
                .order_by(desc(AuditEventRecord.timestamp), desc(AuditEventRecord.id))
                .limit(safe_limit)
                .all()
            )

        fairness_scores: List[float] = []
        explainability_scores: List[float] = []
        fairness_engine_counts: Dict[str, int] = {}
        explainability_engine_counts: Dict[str, int] = {}
        fairness_risk_counts: Dict[str, int] = {}
        explanation_level_counts: Dict[str, int] = {}
        daily_buckets: Dict[str, Dict[str, List[float]]] = {}
        recent: List[Dict[str, Any]] = []

        for record in records:
            responsible_ai = _loads_json(record.responsible_ai, {})
            fairness = responsible_ai.get('fairness', {}) or {}
            explainability = responsible_ai.get('explainability', {}) or {}
            day_key = record.timestamp.date().isoformat()
            bucket = daily_buckets.setdefault(day_key, {'fairness': [], 'explainability': []})

            fairness_engine_counts[fairness.get('evaluator_engine', 'unknown')] = (
                fairness_engine_counts.get(fairness.get('evaluator_engine', 'unknown'), 0) + 1
            )
            fairness_risk_counts[fairness.get('fairness_risk', 'unknown')] = (
                fairness_risk_counts.get(fairness.get('fairness_risk', 'unknown'), 0) + 1
            )
            if isinstance(fairness.get('fairness_score'), (int, float)):
                fairness_scores.append(float(fairness['fairness_score']))
                bucket['fairness'].append(float(fairness['fairness_score']))

            explainability_engine_counts[explainability.get('evaluator_engine', 'unknown')] = (
                explainability_engine_counts.get(explainability.get('evaluator_engine', 'unknown'), 0) + 1
            )
            explanation_level_counts[explainability.get('explanation_level', 'unknown')] = (
                explanation_level_counts.get(explainability.get('explanation_level', 'unknown'), 0) + 1
            )
            if isinstance(explainability.get('explainability_score'), (int, float)):
                explainability_scores.append(float(explainability['explainability_score']))
                bucket['explainability'].append(float(explainability['explainability_score']))

            if len(recent) < 50:
                recent.append({
                    'request_id': record.request_id,
                    'timestamp': record.timestamp.isoformat() + 'Z',
                    'fairness_score': fairness.get('fairness_score'),
                    'fairness_risk': fairness.get('fairness_risk'),
                    'explainability_score': explainability.get('explainability_score'),
                    'explanation_level': explainability.get('explanation_level'),
                })

        def _avg(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 3) if values else None

        daily_series = [
            {
                'date': day,
                'avg_fairness_score': _avg(scores['fairness']),
                'fairness_sample_count': len(scores['fairness']),
                'avg_explainability_score': _avg(scores['explainability']),
                'explainability_sample_count': len(scores['explainability']),
            }
            for day, scores in sorted(daily_buckets.items())
        ]

        span.set_attribute('evaluations.total', len(records))
        return {
            'total': len(records),
            'fairness': {
                'avg_score': _avg(fairness_scores),
                'scored_count': len(fairness_scores),
                'by_engine': fairness_engine_counts,
                'by_risk': fairness_risk_counts,
            },
            'explainability': {
                'avg_score': _avg(explainability_scores),
                'scored_count': len(explainability_scores),
                'by_engine': explainability_engine_counts,
                'by_level': explanation_level_counts,
            },
            'daily_series': daily_series,
            'recent': recent,
        }


def get_guardrail_report(user_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    with SessionLocal() as session:
        query = session.query(GuardrailViolationRecord)
        if user_id:
            query = query.filter(GuardrailViolationRecord.user_id == user_id)
        records = (
            query.order_by(desc(GuardrailViolationRecord.created_at), desc(GuardrailViolationRecord.id))
            .limit(max(1, min(limit, 500)))
            .all()
        )
    by_category: Dict[str, int] = {}
    by_user: Dict[str, int] = {}
    for record in records:
        by_category[record.category] = by_category.get(record.category, 0) + 1
        by_user[record.user_id] = by_user.get(record.user_id, 0) + 1
    return {
        'total': len(records),
        'by_category': by_category,
        'by_user': by_user,
        'violations': [
            {
                'request_id': record.request_id,
                'user_id': record.user_id,
                'user_email': record.user_email,
                'tenant_id': record.tenant_id,
                'client_id': record.client_id,
                'agent_id': record.agent_id,
                'stage': record.stage,
                'category': record.category,
                'severity': record.severity,
                'blocked': record.blocked,
                'policy_version': record.policy_version,
                'matched_patterns': _loads_json(record.matched_patterns, []),
                'details': _loads_json(record.details, {}),
                'created_at': record.created_at.isoformat() + 'Z',
            }
            for record in records
        ],
    }


# ----------------------------------------------------------------------
# LLM usage metering (FinOps / AIOps)
# ----------------------------------------------------------------------

def append_llm_usage_event(event: Dict[str, Any]) -> None:
    with tracer.start_as_current_span('llm_usage_insert') as span:
        with SessionLocal() as session:
            session.add(LLMUsageEventRecord(
                request_id=str(event.get('request_id', '')),
                call_id=str(event.get('call_id', '') or ''),
                timestamp=_parse_timestamp(event.get('timestamp')),
                user_id=str(event.get('user_id') or 'anonymous'),
                user_email=str(event.get('user_email') or ''),
                tenant_id=str(event.get('tenant_id') or 'default'),
                client_id=str(event.get('client_id') or ''),
                agent_id=str(event.get('agent_id') or ''),
                session_id=str(event.get('session_id') or ''),
                mode=str(event.get('mode') or 'unknown'),
                purpose=str(event.get('purpose') or 'chat'),
                requested_model=str(event.get('requested_model') or ''),
                served_model=str(event.get('served_model') or ''),
                provider=str(event.get('provider') or ''),
                gateway_mode=str(event.get('gateway_mode') or 'proxy'),
                api_base=str(event.get('api_base') or '')[:320],
                prompt_tokens=int(event.get('prompt_tokens') or 0),
                completion_tokens=int(event.get('completion_tokens') or 0),
                total_tokens=int(event.get('total_tokens') or 0),
                cost_usd=float(event.get('cost_usd') or 0.0),
                cost_source=str(event.get('cost_source') or 'unknown'),
                latency_ms=int(event.get('latency_ms') or 0),
                proxy_overhead_ms=event.get('proxy_overhead_ms'),
                retries=int(event.get('retries') or 0),
                fallbacks=int(event.get('fallbacks') or 0),
                status=str(event.get('status') or 'success'),
                error_type=str(event.get('error_type') or '')[:80],
                http_status=event.get('http_status'),
            ))
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                raise
        span.set_attribute('llm.purpose', str(event.get('purpose') or 'chat'))
        span.set_attribute('llm.cost_usd', float(event.get('cost_usd') or 0.0))


def _usage_records_since(since: datetime, limit: int = 20000) -> List[LLMUsageEventRecord]:
    with SessionLocal() as session:
        return (
            session.query(LLMUsageEventRecord)
            .filter(LLMUsageEventRecord.timestamp >= since)
            .order_by(desc(LLMUsageEventRecord.timestamp), desc(LLMUsageEventRecord.id))
            .limit(limit)
            .all()
        )


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile / 100 * len(ordered)) - 1))
    return round(ordered[index], 1)


def _usage_event_dict(record: LLMUsageEventRecord) -> Dict[str, Any]:
    return {
        'request_id': record.request_id,
        'call_id': record.call_id,
        'timestamp': record.timestamp.isoformat() + 'Z',
        'user_id': record.user_id,
        'tenant_id': record.tenant_id,
        'client_id': record.client_id,
        'agent_id': record.agent_id,
        'mode': record.mode,
        'purpose': record.purpose,
        'requested_model': record.requested_model,
        'served_model': record.served_model,
        'provider': record.provider,
        'prompt_tokens': record.prompt_tokens,
        'completion_tokens': record.completion_tokens,
        'total_tokens': record.total_tokens,
        'cost_usd': round(record.cost_usd, 6),
        'cost_source': record.cost_source,
        'latency_ms': record.latency_ms,
        'proxy_overhead_ms': record.proxy_overhead_ms,
        'retries': record.retries,
        'fallbacks': record.fallbacks,
        'status': record.status,
        'error_type': record.error_type,
        'http_status': record.http_status,
    }


def get_finops_summary(days: int = 30, monthly_budget_usd: float = 0.0) -> Dict[str, Any]:
    """Spend, token and unit-economics view for the FinOps dashboard.

    Aggregates llm_usage_events over the trailing window and, independently,
    month-to-date so the budget gauge is calendar-aligned regardless of the
    window the operator picked.
    """
    with tracer.start_as_current_span('db.finops.summary') as span:
        safe_days = max(1, min(days, 365))
        now = datetime.utcnow()
        window_start = now - timedelta(days=safe_days)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        records = _usage_records_since(min(window_start, month_start))

        def _bucket() -> Dict[str, Any]:
            return {'requests': 0, 'cost_usd': 0.0, 'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

        totals = _bucket()
        totals.update({'success': 0, 'errors': 0})
        by_model: Dict[str, Dict[str, Any]] = {}
        by_tenant: Dict[str, Dict[str, Any]] = {}
        by_user: Dict[str, Dict[str, Any]] = {}
        by_purpose: Dict[str, Dict[str, Any]] = {}
        by_client: Dict[str, Dict[str, Any]] = {}
        by_cost_source: Dict[str, int] = {}
        daily: Dict[str, Dict[str, Any]] = {}
        mtd_cost = 0.0
        mtd_requests = 0
        recent: List[Dict[str, Any]] = []

        def _add(target: Dict[str, Dict[str, Any]], key: str, record: LLMUsageEventRecord) -> None:
            bucket = target.setdefault(key or 'unknown', _bucket())
            bucket['requests'] += 1
            bucket['cost_usd'] += record.cost_usd
            bucket['prompt_tokens'] += record.prompt_tokens
            bucket['completion_tokens'] += record.completion_tokens
            bucket['total_tokens'] += record.total_tokens

        for record in records:
            if record.timestamp >= month_start:
                mtd_cost += record.cost_usd
                mtd_requests += 1
            if record.timestamp < window_start:
                continue

            totals['requests'] += 1
            totals['cost_usd'] += record.cost_usd
            totals['prompt_tokens'] += record.prompt_tokens
            totals['completion_tokens'] += record.completion_tokens
            totals['total_tokens'] += record.total_tokens
            if record.status == 'success':
                totals['success'] += 1
            else:
                totals['errors'] += 1

            _add(by_model, record.served_model or record.requested_model, record)
            _add(by_tenant, record.tenant_id, record)
            _add(by_user, record.user_email or record.user_id, record)
            _add(by_purpose, record.purpose, record)
            _add(by_client, record.client_id or 'unspecified', record)
            by_cost_source[record.cost_source] = by_cost_source.get(record.cost_source, 0) + 1

            day_key = record.timestamp.date().isoformat()
            day = daily.setdefault(day_key, {'date': day_key, 'cost_usd': 0.0, 'requests': 0, 'total_tokens': 0})
            day['cost_usd'] += record.cost_usd
            day['requests'] += 1
            day['total_tokens'] += record.total_tokens

            if len(recent) < 25:
                recent.append(_usage_event_dict(record))

        def _finish(target: Dict[str, Dict[str, Any]], top: Optional[int] = None) -> List[Dict[str, Any]]:
            rows = [
                {
                    'key': key,
                    **bucket,
                    'cost_usd': round(bucket['cost_usd'], 6),
                    'avg_cost_per_request': round(bucket['cost_usd'] / bucket['requests'], 6) if bucket['requests'] else 0.0,
                }
                for key, bucket in target.items()
            ]
            rows.sort(key=lambda row: row['cost_usd'], reverse=True)
            return rows[:top] if top else rows

        days_in_month = calendar.monthrange(now.year, now.month)[1]
        days_elapsed = max(1, (now - month_start).days + 1)
        projected = mtd_cost / days_elapsed * days_in_month if mtd_requests else 0.0
        budget: Dict[str, Any] = {
            'monthly_budget_usd': monthly_budget_usd,
            'month_to_date_cost_usd': round(mtd_cost, 6),
            'month_to_date_requests': mtd_requests,
            'projected_month_cost_usd': round(projected, 6),
            'days_elapsed': days_elapsed,
            'days_in_month': days_in_month,
        }
        if monthly_budget_usd > 0:
            utilization = mtd_cost / monthly_budget_usd
            projected_utilization = projected / monthly_budget_usd
            budget.update({
                'utilization': round(utilization, 4),
                'projected_utilization': round(projected_utilization, 4),
                'status': 'over' if utilization >= 1 else ('warning' if projected_utilization >= 0.8 else 'ok'),
            })
        else:
            budget['status'] = 'not_set'

        requests_total = totals['requests']
        unit_economics = {
            'avg_cost_per_request_usd': round(totals['cost_usd'] / requests_total, 6) if requests_total else 0.0,
            'avg_tokens_per_request': round(totals['total_tokens'] / requests_total, 1) if requests_total else 0.0,
            'cost_per_1k_tokens_usd': (
                round(totals['cost_usd'] / totals['total_tokens'] * 1000, 6) if totals['total_tokens'] else 0.0
            ),
            'judge_share_of_cost': (
                round(
                    sum(bucket['cost_usd'] for key, bucket in by_purpose.items() if key.startswith('judge'))
                    / totals['cost_usd'],
                    4,
                )
                if totals['cost_usd'] else 0.0
            ),
        }

        span.set_attribute('finops.requests', requests_total)
        return {
            'window_days': safe_days,
            'generated_at': now.isoformat() + 'Z',
            'totals': {**totals, 'cost_usd': round(totals['cost_usd'], 6)},
            'unit_economics': unit_economics,
            'budget': budget,
            'by_model': _finish(by_model),
            'by_tenant': _finish(by_tenant),
            'by_user': _finish(by_user, top=10),
            'by_purpose': _finish(by_purpose),
            'by_client': _finish(by_client, top=10),
            'by_cost_source': by_cost_source,
            'daily_series': [
                {**day, 'cost_usd': round(day['cost_usd'], 6)} for day in sorted(daily.values(), key=lambda d: d['date'])
            ],
            'recent': recent,
        }


def get_aiops_summary(hours: int = 24) -> Dict[str, Any]:
    """Reliability and performance view of the LLM path for the AIOps dashboard."""
    with tracer.start_as_current_span('db.aiops.summary') as span:
        safe_hours = max(1, min(hours, 24 * 30))
        now = datetime.utcnow()
        window_start = now - timedelta(hours=safe_hours)
        records = _usage_records_since(window_start)

        latencies: List[float] = []
        overheads: List[float] = []
        by_status: Dict[str, int] = {}
        by_error_type: Dict[str, int] = {}
        by_model: Dict[str, Dict[str, Any]] = {}
        by_purpose: Dict[str, Dict[str, Any]] = {}
        hourly: Dict[str, Dict[str, Any]] = {}
        retries_total = 0
        fallbacks_total = 0
        timeouts = 0
        rate_limited = 0
        recent_errors: List[Dict[str, Any]] = []

        for record in records:
            by_status[record.status] = by_status.get(record.status, 0) + 1
            retries_total += record.retries
            fallbacks_total += record.fallbacks
            if record.status != 'success':
                by_error_type[record.error_type or 'unknown'] = by_error_type.get(record.error_type or 'unknown', 0) + 1
                if record.error_type == 'Timeout':
                    timeouts += 1
                if record.http_status == 429:
                    rate_limited += 1
                if len(recent_errors) < 20:
                    recent_errors.append(_usage_event_dict(record))
            else:
                latencies.append(record.latency_ms)
                if record.proxy_overhead_ms is not None:
                    overheads.append(record.proxy_overhead_ms)

            model_key = record.served_model or record.requested_model or 'unknown'
            model = by_model.setdefault(model_key, {'requests': 0, 'errors': 0, 'latencies': [], 'retries': 0, 'fallbacks': 0})
            model['requests'] += 1
            model['retries'] += record.retries
            model['fallbacks'] += record.fallbacks
            if record.status == 'success':
                model['latencies'].append(record.latency_ms)
            else:
                model['errors'] += 1

            purpose = by_purpose.setdefault(record.purpose, {'requests': 0, 'errors': 0, 'latencies': []})
            purpose['requests'] += 1
            if record.status == 'success':
                purpose['latencies'].append(record.latency_ms)
            else:
                purpose['errors'] += 1

            hour_key = record.timestamp.replace(minute=0, second=0, microsecond=0).isoformat() + 'Z'
            hour = hourly.setdefault(hour_key, {'hour': hour_key, 'requests': 0, 'errors': 0, 'latencies': [], 'tokens': 0})
            hour['requests'] += 1
            hour['tokens'] += record.total_tokens
            if record.status == 'success':
                hour['latencies'].append(record.latency_ms)
            else:
                hour['errors'] += 1

        total = len(records)
        errors = total - by_status.get('success', 0)

        def _finish_group(target: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            rows = []
            for key, bucket in target.items():
                lat = bucket.pop('latencies', [])
                rows.append({
                    'key': key,
                    **bucket,
                    'error_rate': round(bucket['errors'] / bucket['requests'], 4) if bucket['requests'] else 0.0,
                    'p50_latency_ms': _percentile(lat, 50),
                    'p95_latency_ms': _percentile(lat, 95),
                    'avg_latency_ms': round(sum(lat) / len(lat), 1) if lat else None,
                })
            rows.sort(key=lambda row: row['requests'], reverse=True)
            return rows

        hourly_series = []
        for hour in sorted(hourly.values(), key=lambda h: h['hour']):
            lat = hour.pop('latencies')
            hourly_series.append({
                **hour,
                'error_rate': round(hour['errors'] / hour['requests'], 4) if hour['requests'] else 0.0,
                'p95_latency_ms': _percentile(lat, 95),
                'avg_latency_ms': round(sum(lat) / len(lat), 1) if lat else None,
            })

        span.set_attribute('aiops.requests', total)
        return {
            'window_hours': safe_hours,
            'generated_at': now.isoformat() + 'Z',
            'totals': {
                'requests': total,
                'success': by_status.get('success', 0),
                'errors': errors,
                'error_rate': round(errors / total, 4) if total else 0.0,
                'availability': round(1 - errors / total, 4) if total else None,
                'timeouts': timeouts,
                'rate_limited': rate_limited,
                'retries': retries_total,
                'fallbacks': fallbacks_total,
                'requests_per_hour': round(total / safe_hours, 2),
            },
            'latency': {
                'p50_ms': _percentile(latencies, 50),
                'p95_ms': _percentile(latencies, 95),
                'p99_ms': _percentile(latencies, 99),
                'avg_ms': round(sum(latencies) / len(latencies), 1) if latencies else None,
                'max_ms': max(latencies) if latencies else None,
                'avg_proxy_overhead_ms': round(sum(overheads) / len(overheads), 1) if overheads else None,
                'sample_count': len(latencies),
            },
            'by_status': by_status,
            'by_error_type': by_error_type,
            'by_model': _finish_group(by_model),
            'by_purpose': _finish_group(by_purpose),
            'hourly_series': hourly_series,
            'recent_errors': recent_errors,
        }


def get_audit_block_stats(hours: int = 24) -> Dict[str, Any]:
    """Guardrail outcomes over the same window as the AIOps summary."""
    safe_hours = max(1, min(hours, 24 * 30))
    since = datetime.utcnow() - timedelta(hours=safe_hours)
    with SessionLocal() as session:
        records = (
            session.query(AuditEventRecord.blocked, AuditEventRecord.risk_level, AuditEventRecord.provider)
            .filter(AuditEventRecord.timestamp >= since)
            .all()
        )
    total = len(records)
    blocked = sum(1 for record in records if record.blocked)
    by_provider: Dict[str, int] = {}
    for record in records:
        by_provider[record.provider] = by_provider.get(record.provider, 0) + 1
    return {
        'chat_requests': total,
        'blocked': blocked,
        'block_rate': round(blocked / total, 4) if total else 0.0,
        'by_provider': by_provider,
    }
