from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

class Mode(str, Enum):
    code = 'code'
    framework = 'framework'

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    mode: Mode = Mode.code
    # Empty means "use the gateway's configured default model" (LLM_DEFAULT_MODEL).
    model: str = Field(default='')
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_tokens: int = Field(default=800, ge=1, le=2000)
    explain: bool = Field(default=True)
    verify: bool = Field(default=True)
    client_id: str = ''
    agent_id: str = ''
    session_id: str = ''

class ResponsibleAIResponse(BaseModel):
    privacy: dict = Field(default_factory=dict)
    safety: dict = Field(default_factory=dict)
    fairness: dict = Field(default_factory=dict)
    explainability: dict = Field(default_factory=dict)
    verifiability: dict = Field(default_factory=dict)
    transparency: dict = Field(default_factory=dict)
    governance: dict = Field(default_factory=dict)
    controllability: dict = Field(default_factory=dict)

class UsageMetadata(BaseModel):
    """Per-response metering surfaced to the client for transparency.

    Populated from the LiteLLM proxy response (tokens from the body, cost and
    routing details from x-litellm-* headers). cost_source tells the reader
    whether the figure is LiteLLM's metered cost or a local estimate.
    """
    gateway: str = 'litellm'
    served_model: str = ''
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    cost_source: str = 'unknown'
    latency_ms: int = 0
    proxy_overhead_ms: int | None = None
    retries: int = 0
    fallbacks: int = 0
    status: str = 'success'
    error_type: str = ''


class MetadataResponse(BaseModel):
    model: str
    provider: str
    mode: Mode
    request_id: str
    timestamp: datetime
    user_id: str = ''
    client_id: str = ''
    agent_id: str = ''
    session_id: str = ''
    usage: UsageMetadata = Field(default_factory=UsageMetadata)

class ChatResponse(BaseModel):
    answer: str
    responsible_ai: ResponsibleAIResponse
    metadata: MetadataResponse

class AuditEvent(BaseModel):
    request_id: str
    timestamp: datetime
    mode: Mode
    model: str
    provider: str
    user_id: str = ''
    user_email: str = ''
    tenant_id: str = 'default'
    client_id: str = ''
    agent_id: str = ''
    session_id: str = ''
    is_cached: bool = False
    blocked: bool = False
    risk_level: str = 'low'
    violation_count: int = 0
    summary: str = ''
    responsible_ai: dict = Field(default_factory=dict)

class PolicyResponse(BaseModel):
    policy: dict


class SafetyPolicyPatternInput(BaseModel):
    pattern: str = Field(..., min_length=1)
    label: str = ''
    is_case_sensitive: bool = False


class SafetyHubValidatorInput(BaseModel):
    hub_uri: str = Field(..., min_length=1)
    validator_class: str = Field(..., min_length=1)
    install_local_models: bool = False
    runtime_params: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class SafetyPolicyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    severity: str = Field(default='medium')
    description: str = ''
    policy_kind: str = 'regex'
    enabled: bool = True
    source: str = 'manual'
    patterns: list[SafetyPolicyPatternInput] = Field(default_factory=list)
    hub_validators: list[SafetyHubValidatorInput] = Field(default_factory=list)


class SafetyHubPolicyImport(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(default='guardrails_hub')
    severity: str = Field(default='medium')
    description: str = ''
    source: str = 'guardrails_hub'
    hub_validator: SafetyHubValidatorInput


class SafetyHubValidatorInstallRequest(BaseModel):
    hub_uri: str = Field(..., min_length=1)
    install_local_models: bool = False


class SafetyPolicyUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    severity: str | None = None
    description: str | None = None
    policy_kind: str | None = None
    enabled: bool | None = None
    status: str | None = None
    patterns: list[SafetyPolicyPatternInput] | None = None
    hub_validators: list[SafetyHubValidatorInput] | None = None


class PolicyActionRequest(BaseModel):
    actor: str = 'ui'


class PolicyTestRequest(BaseModel):
    message: str = Field(..., min_length=1)
