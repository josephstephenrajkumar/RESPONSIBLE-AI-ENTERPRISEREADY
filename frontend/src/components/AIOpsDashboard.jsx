import { useEffect, useState } from 'react'
import { fetchAiopsReport } from '../api'
import { BarList, BreakdownBars, StatusDot, TrendChart, formatMs, formatNumber, formatPercent } from './charts'

const WINDOWS = [
  { hours: 1, label: '1 h' },
  { hours: 24, label: '24 h' },
  { hours: 168, label: '7 days' },
]

function DependencyCard({ title, status, children }) {
  return (
    <div className="dependency-card">
      <div className="panel-title-row">
        <h4>{title}</h4>
        <StatusDot status={status} />
      </div>
      {children}
    </div>
  )
}

function DependencyHealth({ dependencies, guardrails }) {
  if (!dependencies) return null
  const llm = dependencies.llm_gateway || {}
  const tracing = dependencies.tracing || {}
  const db = dependencies.database || {}
  const validators = dependencies.safety_validators || {}
  return (
    <div className="health-grid">
      <DependencyCard title="LLM gateway (LiteLLM)" status={llm.status}>
        <p className="muted">
          <code>{llm.base_url}</code> · mode <strong>{llm.mode}</strong>
          {llm.reachable ? ` · ${llm.model_count} model(s) · ${formatMs(llm.latency_ms)}` : ` · ${llm.error || 'unreachable'}`}
        </p>
        {llm.reachable && llm.default_model_available === false && (
          <p className="muted warning-text">Default model <code>{llm.default_model}</code> is not served by the proxy.</p>
        )}
        {llm.mode === 'proxy' && llm.application_holds_provider_key && (
          <p className="muted warning-text">
            GROQ_API_KEY is still present in the gateway environment. Remove it so only the proxy holds provider credentials.
          </p>
        )}
      </DependencyCard>
      <DependencyCard title="Tracing (OpenTelemetry)" status={tracing.status}>
        <p className="muted">{tracing.exporter} → <code>{tracing.endpoint}</code>{tracing.reason ? ` · ${tracing.reason}` : ''}</p>
      </DependencyCard>
      <DependencyCard title="Database" status={db.status}>
        <p className="muted">{db.dialect}{db.error ? ` · ${db.error}` : ' · SELECT 1 ok'}</p>
      </DependencyCard>
      <DependencyCard title="Safety validators" status={validators.failing === 0 ? 'ok' : 'error'}>
        <p className="muted">
          Policy version <code>{validators.active_policy_version || 'none'}</code> ·{' '}
          {validators.failing === 0 ? 'all hub validators loaded' : `${validators.failing} validator(s) failing`}
        </p>
      </DependencyCard>
      <DependencyCard title="Guardrails (window)" status={guardrails ? 'ok' : 'neutral'}>
        <p className="muted">
          {formatNumber(guardrails?.chat_requests)} chat request(s) · {formatNumber(guardrails?.blocked)} blocked ·{' '}
          block rate {formatPercent(guardrails?.block_rate)}
        </p>
      </DependencyCard>
      <DependencyCard title="Langfuse" status={dependencies.langfuse?.configured ? 'ok' : 'disabled'}>
        <p className="muted">{dependencies.langfuse?.configured ? 'configured on gateway' : 'not configured on gateway (prefer configuring on the proxy)'}</p>
      </DependencyCard>
    </div>
  )
}

export default function AIOpsDashboard() {
  const [hours, setHours] = useState(24)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = (window = hours) => {
    setLoading(true)
    setError(null)
    fetchAiopsReport(window)
      .then(setReport)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load(hours)
    const interval = setInterval(() => load(hours), 60000)
    return () => clearInterval(interval)
  }, [hours])

  if (error) {
    return (
      <section className="panel">
        <h2>AIOps Dashboard</h2>
        <p className="muted">Unable to load AIOps report: {error}</p>
      </section>
    )
  }

  if (!report) {
    return (
      <section className="panel">
        <h2>AIOps Dashboard</h2>
        <p className="muted">Loading operational metrics...</p>
      </section>
    )
  }

  const { totals, latency } = report
  const availabilityTone = totals.availability === null ? 'neutral' : totals.availability >= 0.99 ? 'ok' : totals.availability >= 0.95 ? 'warning' : 'error'

  return (
    <section className="panel aiops-dashboard">
      <div className="panel-title-row">
        <div>
          <h2>AIOps Dashboard</h2>
          <p className="muted">
            Health of the LLM path over the last {report.window_hours} hour(s): availability, latency, retries and
            fallbacks as seen by the gateway, plus live dependency checks. Auto-refreshes every minute.
          </p>
        </div>
        <div className="button-row">
          <div className="segmented" role="tablist" aria-label="Window">
            {WINDOWS.map(option => (
              <button
                key={option.hours}
                type="button"
                className={option.hours === hours ? 'active' : 'ghost'}
                onClick={() => setHours(option.hours)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button className="ghost" onClick={() => load()} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button>
        </div>
      </div>

      <h3>Dependencies</h3>
      <DependencyHealth dependencies={report.dependencies} guardrails={report.guardrails} />

      <h3>Service levels</h3>
      <div className="metric-grid">
        <div>
          <span>Availability <StatusDot status={availabilityTone} /></span>
          <strong>{formatPercent(totals.availability, 2)}</strong>
        </div>
        <div><span>Model calls</span><strong>{formatNumber(totals.requests)}</strong></div>
        <div><span>Error rate</span><strong>{formatPercent(totals.error_rate)}</strong></div>
        <div><span>Calls / hour</span><strong>{formatNumber(totals.requests_per_hour)}</strong></div>
        <div><span>p50 latency</span><strong>{formatMs(latency.p50_ms)}</strong></div>
        <div><span>p95 latency</span><strong>{formatMs(latency.p95_ms)}</strong></div>
        <div><span>p99 latency</span><strong>{formatMs(latency.p99_ms)}</strong></div>
        <div><span>Proxy overhead (avg)</span><strong>{formatMs(latency.avg_proxy_overhead_ms)}</strong></div>
        <div><span>Retries</span><strong>{formatNumber(totals.retries)}</strong></div>
        <div><span>Fallbacks</span><strong>{formatNumber(totals.fallbacks)}</strong></div>
        <div><span>Timeouts</span><strong>{formatNumber(totals.timeouts)}</strong></div>
        <div><span>Rate limited (429)</span><strong>{formatNumber(totals.rate_limited)}</strong></div>
      </div>

      <div className="eval-columns">
        <div>
          <h3>p95 latency per hour</h3>
          <TrendChart
            series={report.hourly_series.map(h => ({ ...h, label: new Date(h.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }))}
            dataKey="p95_latency_ms"
            xKey="label"
            label="p95"
            color="#2563eb"
            formatter={formatMs}
          />
        </div>
        <div>
          <h3>Error rate per hour</h3>
          <TrendChart
            series={report.hourly_series.map(h => ({ ...h, label: new Date(h.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }))}
            dataKey="error_rate"
            xKey="label"
            label="error rate"
            color="#dc2626"
            formatter={v => formatPercent(v)}
          />
        </div>
      </div>

      <div className="eval-columns">
        <div>
          <h3>Per model</h3>
          <div className="table-wrap">
            <table className="policy-table finops-table">
              <thead>
                <tr><th>Model</th><th>Calls</th><th>Errors</th><th>p50</th><th>p95</th><th>Retries</th><th>Fallbacks</th></tr>
              </thead>
              <tbody>
                {report.by_model.map(row => (
                  <tr key={row.key}>
                    <td><code>{row.key}</code></td>
                    <td>{formatNumber(row.requests)}</td>
                    <td>{formatNumber(row.errors)} ({formatPercent(row.error_rate)})</td>
                    <td>{formatMs(row.p50_latency_ms)}</td>
                    <td>{formatMs(row.p95_latency_ms)}</td>
                    <td>{formatNumber(row.retries)}</td>
                    <td>{formatNumber(row.fallbacks)}</td>
                  </tr>
                ))}
                {report.by_model.length === 0 && <tr><td colSpan="7" className="muted">No model calls in this window.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h3>Per purpose</h3>
          <BarList rows={report.by_purpose} valueKey="p95_latency_ms" formatter={formatMs} color="#7c3aed" empty="No latency samples yet." />
          <h4>Outcomes</h4>
          <BreakdownBars counts={report.by_status} colors={{ success: '#16a34a', error: '#dc2626', unconfigured: '#d97706' }} />
          <h4>Error types</h4>
          <BreakdownBars counts={report.by_error_type} colors={{}} empty="No errors in this window." />
        </div>
      </div>

      <h3>Recent errors</h3>
      {report.recent_errors.length === 0 ? (
        <p className="muted">No failed model calls in this window.</p>
      ) : (
        <div className="table-wrap">
          <table className="policy-table finops-table">
            <thead>
              <tr><th>Time</th><th>Purpose</th><th>Model</th><th>Error</th><th>HTTP</th><th>Latency</th><th>Request</th></tr>
            </thead>
            <tbody>
              {report.recent_errors.map(event => (
                <tr key={`${event.request_id}-${event.purpose}-${event.timestamp}`}>
                  <td>{new Date(event.timestamp).toLocaleString()}</td>
                  <td>{event.purpose}</td>
                  <td><code>{event.requested_model}</code></td>
                  <td>{event.error_type}</td>
                  <td>{event.http_status ?? '—'}</td>
                  <td>{formatMs(event.latency_ms)}</td>
                  <td><code>{event.request_id.slice(0, 8)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
