import contextlib

from fastapi import FastAPI
from app.config import Settings

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _otel_available = True
except ImportError:
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    HTTPXClientInstrumentor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    _otel_available = False

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    _sqlalchemy_instrumentation_available = True
except ImportError:
    SQLAlchemyInstrumentor = None
    _sqlalchemy_instrumentation_available = False

_tracing_status = {
    'status': 'not_started',
    'service': Settings.OTEL_SERVICE_NAME,
    'exporter': Settings.OTEL_EXPORTER,
    'endpoint': Settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    'jaeger_ui': Settings.JAEGER_UI_URL,
    'console_url': Settings.JAEGER_UI_URL,
    'sqlalchemy_instrumented': False
}
_tracing_initialized = False


class _NoOpTracer:
    def start_as_current_span(self, *args, **kwargs):
        return contextlib.nullcontext(_NoOpSpan())


class _NoOpSpan:
    def set_attribute(self, *args, **kwargs):
        return None


tracer = trace.get_tracer(__name__) if _otel_available else _NoOpTracer()


def setup_tracing(app: FastAPI) -> dict:
    global _tracing_initialized

    if _tracing_initialized:
        return _tracing_status

    if not _otel_available:
        _tracing_status.update({'status': 'disabled', 'reason': 'OpenTelemetry OTLP exporter packages are not installed'})
        return _tracing_status

    if not Settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:
        _tracing_status.update({'status': 'disabled', 'reason': 'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT must be configured'})
        return _tracing_status

    resource = Resource.create({'service.name': Settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    try:
        trace.set_tracer_provider(provider)
    except Exception:
        pass

    exporter = OTLPSpanExporter(endpoint=Settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT)

    provider.add_span_processor(BatchSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    _tracing_initialized = True
    _tracing_status.update({
        'status': 'enabled',
        'exporter': Settings.OTEL_EXPORTER,
        'endpoint': Settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
        'jaeger_ui': Settings.JAEGER_UI_URL,
        'console_url': Settings.JAEGER_UI_URL,
        'sqlalchemy_instrumented': False
    })
    return _tracing_status


def instrument_sqlalchemy(engine) -> dict:
    if not _otel_available or not _sqlalchemy_instrumentation_available:
        _tracing_status['sqlalchemy_instrumented'] = False
        _tracing_status['sqlalchemy_instrumentation_note'] = (
            'Install opentelemetry-instrumentation-sqlalchemy for automatic SQLAlchemy spans'
        )
        return _tracing_status

    try:
        SQLAlchemyInstrumentor().instrument(engine=engine)
        _tracing_status['sqlalchemy_instrumented'] = True
    except Exception as exc:
        _tracing_status['sqlalchemy_instrumented'] = False
        _tracing_status['sqlalchemy_instrumentation_error'] = str(exc)
    return _tracing_status


def get_tracing_status() -> dict:
    return dict(_tracing_status)
