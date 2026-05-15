import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parent / '.env'
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

class Settings:
    PROJECT_NAME = 'Responsible AI Enterprise Gateway'
    API_PREFIX = '/api'
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
    GROQ_API_URL = os.getenv('GROQ_API_URL', 'https://api.groq.com/openai/v1')
    GROQ_TIMEOUT_SECONDS = float(os.getenv('GROQ_TIMEOUT_SECONDS', '25'))
    GROQ_MAX_CONNECTIONS = int(os.getenv('GROQ_MAX_CONNECTIONS', '100'))
    GROQ_MAX_KEEPALIVE_CONNECTIONS = int(os.getenv('GROQ_MAX_KEEPALIVE_CONNECTIONS', '20'))
    LANGFUSE_PUBLIC_KEY = os.getenv('LANGFUSE_PUBLIC_KEY', '')
    LANGFUSE_SECRET_KEY = os.getenv('LANGFUSE_SECRET_KEY', '')
    LANGFUSE_HOST = os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com')
    PRESIDIO_SPACY_MODEL = os.getenv('PRESIDIO_SPACY_MODEL', 'en_core_web_sm')
    GUARDRAILS_TOKEN = os.getenv('GUARDRAILS_TOKEN', '')
    AUTH_REQUIRED = os.getenv('AUTH_REQUIRED', 'false').lower() == 'true'
    COGNITO_REGION = os.getenv('COGNITO_REGION', '')
    COGNITO_USER_POOL_ID = os.getenv('COGNITO_USER_POOL_ID', '')
    COGNITO_APP_CLIENT_ID = os.getenv('COGNITO_APP_CLIENT_ID', '')
    COGNITO_DOMAIN = os.getenv('COGNITO_DOMAIN', '')
    COGNITO_ISSUER = os.getenv(
        'COGNITO_ISSUER',
        f'https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}'
        if COGNITO_REGION and COGNITO_USER_POOL_ID
        else ''
    )
    LOCAL_DEV_USER_ID = os.getenv('LOCAL_DEV_USER_ID', 'local-dev-user')
    LOCAL_DEV_USER_EMAIL = os.getenv('LOCAL_DEV_USER_EMAIL', 'local@example.com')
    OTEL_SERVICE_NAME = os.getenv('OTEL_SERVICE_NAME', 'responsible-ai-chat-agent')
    JAEGER_HOST = os.getenv('JAEGER_HOST', 'localhost')
    JAEGER_PORT = int(os.getenv('JAEGER_PORT', '6831'))
    JAEGER_ENDPOINT = os.getenv('JAEGER_ENDPOINT', '')
    JAEGER_UI_URL = os.getenv('JAEGER_UI_URL', 'http://localhost:16686')
    OTEL_EXPORTER = os.getenv('OTEL_EXPORTER', 'otlp_http_to_jaeger')
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = os.getenv(
        'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT',
        f'http://{JAEGER_HOST}:4318/v1/traces'
    )
    DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'storage' / 'responsible_ai.db'}")
    FRONTEND_ORIGINS = [
        'http://localhost:5173',
        'http://localhost:5174',
        'http://localhost:5175',
        'http://127.0.0.1:5173',
        'http://127.0.0.1:5174',
        'http://127.0.0.1:5175'
    ]
    EXTRA_FRONTEND_ORIGINS = [
        item.strip()
        for item in os.getenv('FRONTEND_ORIGINS', '').split(',')
        if item.strip()
    ]
    FRONTEND_ORIGINS = FRONTEND_ORIGINS + EXTRA_FRONTEND_ORIGINS
    POLICY_PATH = BASE_DIR / 'storage' / 'policy_config.json'
    AUDIT_LOG_PATH = BASE_DIR / 'storage' / 'audit_log.jsonl'
