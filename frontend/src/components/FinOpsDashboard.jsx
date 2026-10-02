import { useEffect, useState } from 'react'
import { fetchFinopsReport } from '../api'
import { BarList, BreakdownBars, StatusDot, TrendChart, formatNumber, formatUsd } from './charts'

const WINDOWS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

function BudgetGauge({ budget, currency }) {
  if (!budget) return null
  if (budget.status === 'not_set') {
    return (
      <div className="budget-card">
        <div className="panel-title-row">
          <h3>Monthly budget</h3>
          <StatusDot status="not_set" />
        </div>
        <p className="muted">
          No budget configured. Set <code>FINOPS_MONTHLY_BUDGET_USD</code> on the gateway to track
          month-to-date spend ({formatUsd(budget.month_to_date_cost_usd)}) and the projected month-end
          cost ({formatUsd(budget.projected_month_cost_usd)}) against a target.
        </p>
      </div>
    )
  }
  const utilization = Math.min(1, budget.utilization || 0)
  const projected = Math.min(1.5, budget.projected_utilization || 0)
  return (
    <div className={`budget-card budget-${budget.status}`}>
      <div className="panel-title-row">
        <h3>Monthly budget</h3>
        <StatusDot status={budget.status} />
      </div>
      <div className="budget-track">
        <div className="budget-fill" style={{ width: `${utilization * 100}%` }} />
        <div className="budget-projection" style={{ left: `${Math.min(100, projected * 100)}%` }} title="Projected month-end" />
      </div>
      <div className="budget-figures">
        <span>MTD {formatUsd(budget.month_to_date_cost_usd)} ({Math.round((budget.utilization || 0) * 100)}%)</span>
        <span>Projected {formatUsd(budget.projected_month_cost_usd)} ({Math.round((budget.projected_utilization || 0) * 100)}%)</span>
        <span>Budget {formatUsd(budget.monthly_budget_usd)} {currency}</span>
      </div>
      <p className="muted">
        Day {budget.days_elapsed} of {budget.days_in_month}. Projection is a straight-line extrapolation of
        month-to-date spend.
      </p>
    </div>
  )
}

function CostTable({ rows, title, keyLabel }) {
  if (!rows || rows.length === 0) {
    return (
      <div>
        <h4>{title}</h4>
        <p className="muted">No data yet.</p>
      </div>
    )
  }
  return (
    <div>
      <h4>{title}</h4>
      <div className="table-wrap">
        <table className="policy-table finops-table">
          <thead>
            <tr>
              <th>{keyLabel}</th>
              <th>Requests</th>
              <th>Tokens</th>
              <th>Cost</th>
              <th>Avg / request</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.key}>
                <td><code>{row.key}</code></td>
                <td>{formatNumber(row.requests)}</td>
                <td>{formatNumber(row.total_tokens)}</td>
                <td>{formatUsd(row.cost_usd)}</td>
                <td>{formatUsd(row.avg_cost_per_request, 5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function FinOpsDashboard() {
  const [days, setDays] = useState(30)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = (window = days) => {
    setLoading(true)
    setError(null)
    fetchFinopsReport(window)
      .then(setReport)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load(days)
  }, [days])

  if (error) {
    return (
      <section className="panel">
        <h2>FinOps Dashboard</h2>
        <p className="muted">Unable to load FinOps report: {error}</p>
      </section>
    )
  }

  if (!report) {
    return (
      <section className="panel">
        <h2>FinOps Dashboard</h2>
        <p className="muted">Loading spend metrics...</p>
      </section>
    )
  }

  const { totals, unit_economics: unit, budget, gateway } = report
  const estimatedShare = report.by_cost_source?.estimated || 0
  const unknownShare = report.by_cost_source?.unknown || 0

  return (
    <section className="panel finops-dashboard">
      <div className="panel-title-row">
        <div>
          <h2>FinOps Dashboard</h2>
          <p className="muted">
            LLM spend metered by the {gateway?.mode === 'proxy' ? 'LiteLLM proxy' : 'gateway (estimated prices)'} over
            the last {report.window_days} days. Every chat answer and every Ragas/TruLens judge call is counted.
          </p>
        </div>
        <div className="button-row">
          <div className="segmented" role="tablist" aria-label="Window">
            {WINDOWS.map(option => (
              <button
                key={option.days}
                type="button"
                className={option.days === days ? 'active' : 'ghost'}
                onClick={() => setDays(option.days)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button className="ghost" onClick={() => load()} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button>
        </div>
      </div>

      <div className="metric-grid">
        <div><span>Total spend</span><strong>{formatUsd(totals.cost_usd)}</strong></div>
        <div><span>Model calls</span><strong>{formatNumber(totals.requests)}</strong></div>
        <div><span>Total tokens</span><strong>{formatNumber(totals.total_tokens)}</strong></div>
        <div><span>Avg cost / call</span><strong>{formatUsd(unit.avg_cost_per_request_usd, 5)}</strong></div>
        <div><span>Cost / 1k tokens</span><strong>{formatUsd(unit.cost_per_1k_tokens_usd, 5)}</strong></div>
        <div><span>Avg tokens / call</span><strong>{formatNumber(unit.avg_tokens_per_request)}</strong></div>
        <div><span>Judge share of cost</span><strong>{Math.round((unit.judge_share_of_cost || 0) * 100)}%</strong></div>
        <div><span>Failed calls</span><strong>{formatNumber(totals.errors)}</strong></div>
      </div>

      <div className="eval-columns">
        <BudgetGauge budget={budget} currency={report.currency} />
        <div>
          <h3>Daily spend</h3>
          <TrendChart series={report.daily_series} dataKey="cost_usd" label="cost" color="#0f766e" formatter={formatUsd} />
          <h4>Cost source</h4>
          <BreakdownBars
            counts={report.by_cost_source}
            colors={{ litellm: '#0f766e', estimated: '#d97706', unknown: '#dc2626', none: '#94a3b8' }}
          />
          {(estimatedShare > 0 || unknownShare > 0) && (
            <p className="muted">
              <strong>{estimatedShare + unknownShare}</strong> call(s) were priced locally or not at all. Route every
              call through the LiteLLM proxy for metered cost.
            </p>
          )}
        </div>
      </div>

      <div className="eval-columns">
        <div>
          <h3>Spend by model</h3>
          <BarList rows={report.by_model} valueKey="cost_usd" formatter={formatUsd} color="#0f766e" />
        </div>
        <div>
          <h3>Spend by purpose</h3>
          <BarList rows={report.by_purpose} valueKey="cost_usd" formatter={formatUsd} color="#7c3aed" />
          <p className="muted">
            <code>judge_*</code> purposes are the Ragas fairness and TruLens explainability evaluations. Point
            <code> LLM_JUDGE_MODEL</code> at the <code>judge-fast</code> group to reduce them.
          </p>
        </div>
      </div>

      <div className="eval-columns">
        <CostTable rows={report.by_tenant} title="Spend by tenant" keyLabel="Tenant" />
        <CostTable rows={report.by_user} title="Top users" keyLabel="User" />
      </div>
      <CostTable rows={report.by_client} title="Spend by client application" keyLabel="Client" />

      <h3>Recent model calls</h3>
      <div className="table-wrap">
        <table className="policy-table finops-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Purpose</th>
              <th>Model</th>
              <th>Tenant</th>
              <th>Tokens</th>
              <th>Cost</th>
              <th>Source</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {report.recent.map(event => (
              <tr key={`${event.request_id}-${event.purpose}-${event.timestamp}`}>
                <td>{new Date(event.timestamp).toLocaleString()}</td>
                <td>{event.purpose}</td>
                <td><code>{event.served_model || event.requested_model}</code></td>
                <td>{event.tenant_id}</td>
                <td>{formatNumber(event.total_tokens)}</td>
                <td>{formatUsd(event.cost_usd, 6)}</td>
                <td>{event.cost_source}</td>
                <td><span className={`pill status-${event.status === 'success' ? 'draft' : 'active'}`}>{event.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
