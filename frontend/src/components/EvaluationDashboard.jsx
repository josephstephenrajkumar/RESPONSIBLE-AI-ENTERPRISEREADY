import { useEffect, useState } from 'react'
import { fetchEvaluationReport } from '../api'

function TrendChart({ series, dataKey, label, color }) {
  const points = series.filter(point => point[dataKey] !== null && point[dataKey] !== undefined)
  if (points.length < 2) {
    return <p className="muted">Not enough data yet to chart a {label} trend.</p>
  }

  const width = 320
  const height = 90
  const padding = 8
  const values = points.map(point => point[dataKey])
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 1)
  const range = max - min || 1

  const coords = points.map((point, index) => {
    const x = padding + (index / (points.length - 1)) * (width - padding * 2)
    const y = height - padding - ((point[dataKey] - min) / range) * (height - padding * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${label} trend`}>
      <polyline points={coords.join(' ')} fill="none" stroke={color} strokeWidth="2" />
      {coords.map((point, index) => {
        const [x, y] = point.split(',')
        return <circle key={index} cx={x} cy={y} r="2.5" fill={color} />
      })}
    </svg>
  )
}

function BreakdownBars({ counts, colors }) {
  const entries = Object.entries(counts || {}).filter(([, count]) => count > 0)
  const total = entries.reduce((sum, [, count]) => sum + count, 0)
  if (total === 0) {
    return <p className="muted">No data yet.</p>
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

export default function EvaluationDashboard() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    fetchEvaluationReport().then(setReport).catch(err => setError(err.message))
  }

  useEffect(() => {
    load()
  }, [])

  if (error) {
    return (
      <section className="panel">
        <h2>Evaluation Dashboard</h2>
        <p className="muted">Unable to load evaluation report: {error}</p>
      </section>
    )
  }

  if (!report) {
    return (
      <section className="panel">
        <h2>Evaluation Dashboard</h2>
        <p className="muted">Loading evaluation metrics...</p>
      </section>
    )
  }

  return (
    <section className="panel evaluation-dashboard">
      <div className="panel-title-row">
        <h2>Evaluation Dashboard</h2>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>
      <p className="muted">
        Ragas (fairness) and TruLens (explainability) scores from the last {report.total} framework-mode
        chat responses.
      </p>
      <div className="metric-grid">
        <div><span>Avg fairness score</span><strong>{report.fairness.avg_score ?? 'n/a'}</strong></div>
        <div><span>Fairness scored</span><strong>{report.fairness.scored_count}</strong></div>
        <div><span>Avg explainability score</span><strong>{report.explainability.avg_score ?? 'n/a'}</strong></div>
        <div><span>Explainability scored</span><strong>{report.explainability.scored_count}</strong></div>
      </div>

      <div className="eval-columns">
        <div>
          <h3>Fairness trend (Ragas)</h3>
          <TrendChart series={report.daily_series} dataKey="avg_fairness_score" label="fairness" color="#2563eb" />
          <h4>Risk distribution</h4>
          <BreakdownBars
            counts={report.fairness.by_risk}
            colors={{ low: '#16a34a', medium: '#d97706', high: '#dc2626', unknown: '#94a3b8' }}
          />
        </div>
        <div>
          <h3>Explainability trend (TruLens)</h3>
          <TrendChart series={report.daily_series} dataKey="avg_explainability_score" label="explainability" color="#7c3aed" />
          <h4>Explanation level distribution</h4>
          <BreakdownBars
            counts={report.explainability.by_level}
            colors={{ high: '#16a34a', medium: '#d97706', low: '#dc2626', 'high-level': '#2563eb', unknown: '#94a3b8' }}
          />
        </div>
      </div>

      <h4>Evaluator engine (real vs fallback)</h4>
      <div className="eval-columns">
        <BreakdownBars counts={report.fairness.by_engine} colors={{ ragas: '#2563eb', heuristic_fallback: '#94a3b8' }} />
        <BreakdownBars counts={report.explainability.by_engine} colors={{ trulens: '#7c3aed', heuristic_fallback: '#94a3b8' }} />
      </div>
    </section>
  )
}
