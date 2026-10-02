// Small dependency-free chart primitives shared by the operational dashboards.
// Deliberately simple SVG: the dashboards aggregate a few hundred points at
// most, and the existing Evaluation/Guardrails dashboards use the same style.

export function formatUsd(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'n/a'
  if (value === 0) return '$0'
  if (Math.abs(value) < 0.01) return `$${value.toFixed(digits)}`
  return `$${value.toFixed(2)}`
}

export function formatNumber(value) {
  if (value === null || value === undefined) return 'n/a'
  return Number(value).toLocaleString()
}

export function formatMs(value) {
  if (value === null || value === undefined) return 'n/a'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined) return 'n/a'
  return `${(value * 100).toFixed(digits)}%`
}

export function TrendChart({ series, dataKey, label, color, xKey = 'date', formatter = v => v }) {
  const points = (series || []).filter(point => point[dataKey] !== null && point[dataKey] !== undefined)
  if (points.length < 2) {
    return <p className="muted">Not enough data yet to chart {label}.</p>
  }

  const width = 360
  const height = 100
  const padding = 10
  const values = points.map(point => point[dataKey])
  const min = Math.min(...values, 0)
  const max = Math.max(...values)
  const range = max - min || 1

  const coords = points.map((point, index) => {
    const x = padding + (index / (points.length - 1)) * (width - padding * 2)
    const y = height - padding - ((point[dataKey] - min) / range) * (height - padding * 2)
    return { x, y, point }
  })

  const last = coords[coords.length - 1]
  return (
    <div className="trend-chart">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${label} trend`}>
        <polyline points={coords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')} fill="none" stroke={color} strokeWidth="2" />
        {coords.map((c, index) => (
          <circle key={index} cx={c.x} cy={c.y} r="2.5" fill={color}>
            <title>{`${c.point[xKey]}: ${formatter(c.point[dataKey])}`}</title>
          </circle>
        ))}
      </svg>
      <div className="trend-chart-legend">
        <span>{points[0][xKey]}</span>
        <strong style={{ color }}>{label}: {formatter(last.point[dataKey])}</strong>
        <span>{last.point[xKey]}</span>
      </div>
    </div>
  )
}

export function BarList({ rows, valueKey, labelKey = 'key', formatter = v => v, color = '#2563eb', empty = 'No data yet.' }) {
  const entries = (rows || []).filter(row => row[valueKey] > 0)
  if (entries.length === 0) {
    return <p className="muted">{empty}</p>
  }
  const max = Math.max(...entries.map(row => row[valueKey]))
  return (
    <div className="eval-breakdown">
      {entries.map(row => (
        <div key={row[labelKey]} className="eval-breakdown-row bar-list-row">
          <span className="eval-breakdown-label" title={row[labelKey]}>{row[labelKey]}</span>
          <div className="eval-breakdown-track">
            <div className="eval-breakdown-fill" style={{ width: `${(row[valueKey] / max) * 100}%`, background: color }} />
          </div>
          <span className="eval-breakdown-count">{formatter(row[valueKey])}</span>
        </div>
      ))}
    </div>
  )
}

export function BreakdownBars({ counts, colors = {}, empty = 'No data yet.' }) {
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
            <div className="eval-breakdown-fill" style={{ width: `${(count / total) * 100}%`, background: colors[key] || '#94a3b8' }} />
          </div>
          <span className="eval-breakdown-count">{count}</span>
        </div>
      ))}
    </div>
  )
}

export function StatusDot({ status }) {
  const tone = status === 'ok' || status === 'enabled' || status === true
    ? 'ok'
    : status === 'warning' || status === 'degraded'
      ? 'warn'
      : status === 'not_set' || status === 'disabled' || status === null || status === undefined
        ? 'neutral'
        : 'error'
  return <span className={`status-dot ${tone}`} aria-label={String(status)} />
}
