import { useEffect, useState } from 'react'
import { fetchSafetyReport, fetchGuardrailReport } from '../api'

function BreakdownBars({ counts, colors, empty = 'No data yet.' }) {
  const entries = Object.entries(counts || {}).filter(([, count]) => count > 0)
  const total = entries.reduce((sum, [, count]) => sum + count, 0)
  if (total === 0) {
    return <p className="muted">{empty}</p>
  }
  return (
    <div className="eval-breakdown">
      {entries.map(([key, count]) => (
        <div key={key} className="eval-breakdown-row">
          <span className="eval-breakdown-label">{key}</span>
          <div className="eval-breakdown-track">
            <div
              className="eval-breakdown-fill"
              style={{ width: `${(count / total) * 100}%`, background: colors[key] || '#94a3b8' }}
            />
          </div>
          <span className="eval-breakdown-count">{count}</span>
        </div>
      ))}
    </div>
  )
}

export default function GuardrailsDashboard() {
  const [safety, setSafety] = useState(null)
  const [violations, setViolations] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    setError(null)
    Promise.all([fetchSafetyReport(), fetchGuardrailReport()])
      .then(([safetyData, violationData]) => {
        setSafety(safetyData)
        setViolations(violationData)
      })
      .catch(err => setError(err.message))
  }

  useEffect(() => {
    load()
  }, [])

  if (error) {
    return (
      <section className="panel">
        <h2>Guardrails Dashboard</h2>
        <p className="muted">Unable to load safety report: {error}</p>
      </section>
    )
  }

  if (!safety) {
    return (
      <section className="panel">
        <h2>Guardrails Dashboard</h2>
        <p className="muted">Loading safety metrics...</p>
      </section>
    )
  }

  const health = safety.validator_health || []
  const failing = health.length

  return (
    <section className="panel guardrails-dashboard">
      <div className="panel-title-row">
        <h2>Guardrails Dashboard</h2>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>
      <p className="muted">
        Safety enforcement across the last {safety.total} framework-mode chat responses.
        Active policy version: <code>{safety.active_policy_version || 'none'}</code>.
      </p>

      <div className="metric-grid">
        <div><span>Requests evaluated</span><strong>{safety.total}</strong></div>
        <div><span>Blocked</span><strong>{safety.blocked}</strong></div>
        <div><span>Block rate</span><strong>{safety.block_rate === null ? 'n/a' : `${Math.round(safety.block_rate * 100)}%`}</strong></div>
        <div><span>Policy violations</span><strong>{violations?.total ?? safety.violation_total}</strong></div>
      </div>

      <div className="eval-columns">
        <div>
          <h4>Risk distribution</h4>
          <BreakdownBars
            counts={safety.by_risk}
            colors={{ low: '#16a34a', medium: '#d97706', high: '#dc2626', unknown: '#94a3b8' }}
          />
          <h4>Block stage</h4>
          <BreakdownBars
            counts={safety.by_stage}
            colors={{ input: '#2563eb', output: '#7c3aed' }}
            empty="Nothing has been blocked yet."
          />
        </div>
        <div>
          <h4>Safety engine (real vs fallback)</h4>
          <BreakdownBars
            counts={safety.by_engine}
            colors={{
              guardrails_ai: '#16a34a',
              guardrails_ai_with_regex_fallback: '#d97706',
              regex_fallback: '#dc2626',
              unknown: '#94a3b8'
            }}
          />
          <h4>Violations by category</h4>
          <BreakdownBars counts={violations?.by_category} colors={{}} empty="No violations recorded." />
        </div>
      </div>

      <h4>Validator health</h4>
      {failing === 0 ? (
        <p className="muted">All active hub validators loaded successfully.</p>
      ) : (
        <div className="policy-health-banner">
          <strong>{failing} validator{failing === 1 ? '' : 's'} failed to load</strong>
          <ul>
            {health.map(item => (
              <li key={`${item.policy_id}-${item.validator_class}`}>
                <em>{item.validator_class}</em> ({item.policy_name}) — {item.error}
                {item.permanent && ' — policy auto-disabled'}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
