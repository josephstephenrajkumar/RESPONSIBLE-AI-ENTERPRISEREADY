import { useEffect, useState } from 'react'
import { fetchObservability } from '../api'

export default function TracingStatus() {
  const [tracingInfo, setTracingInfo] = useState(null)

  useEffect(() => {
    const checkTracing = async () => {
      try {
        const data = await fetchObservability()
        setTracingInfo({
          status: data.status,
          consoleUrl: data.console_url || data.jaeger_ui || 'http://localhost:16686',
          exporter: data.exporter,
          endpoint: data.endpoint,
          sqlalchemyInstrumented: data.sqlalchemy_instrumented
        })
      } catch (err) {
        setTracingInfo({ status: 'unavailable', error: err.message })
      }
    }
    checkTracing()
    const interval = setInterval(checkTracing, 30000)
    return () => clearInterval(interval)
  }, [])

  if (!tracingInfo) return <div className="tracing-badge loading">📊 Tracing...</div>

  if (tracingInfo.status === 'unavailable') {
    return <div className="tracing-badge error">📊 Tracing Unavailable</div>
  }

  if (tracingInfo.status !== 'enabled') {
    return <div className="tracing-badge error">📊 OpenTelemetry Disabled</div>
  }

  const isLocalJaeger = tracingInfo.consoleUrl?.includes('localhost') || tracingInfo.consoleUrl?.includes('127.0.0.1')
  if (isLocalJaeger) {
    return (
      <div
        className="tracing-badge enabled"
        title="OpenTelemetry is enabled, but the Jaeger UI URL is local to the backend/dev machine."
      >
        📊 OpenTelemetry Enabled
      </div>
    )
  }

  return (
    <a
      href={tracingInfo.consoleUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="tracing-badge enabled"
      title={`${tracingInfo.exporter || 'OpenTelemetry'} endpoint: ${tracingInfo.endpoint || 'not configured'}`}
    >
      📊 OpenTelemetry Enabled
    </a>
  )
}
