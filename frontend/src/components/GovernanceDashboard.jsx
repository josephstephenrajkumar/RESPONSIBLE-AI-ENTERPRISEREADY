export default function GovernanceDashboard({ policies, reloadInfo, onReload }) {
  const summary = policies.reduce((acc, policy) => {
    acc.total += 1
    acc[policy.status] = (acc[policy.status] || 0) + 1
    if (policy.enabled) acc.enabled += 1
    return acc
  }, { total: 0, enabled: 0 })

  return (
    <section className="panel governance-dashboard">
      <div className="panel-title-row">
        <h2>Governance Dashboard</h2>
        <button className="ghost" onClick={onReload}>Reload Runtime</button>
      </div>
      <div className="metric-grid">
        <div><span>Total</span><strong>{summary.total}</strong></div>
        <div><span>Enabled</span><strong>{summary.enabled}</strong></div>
        <div><span>Approved</span><strong>{summary.approved || 0}</strong></div>
        <div><span>Active</span><strong>{summary.active || 0}</strong></div>
      </div>
      {reloadInfo && <p className="muted">Runtime loaded {reloadInfo.loaded_policies} policies, version {reloadInfo.policy_version}.</p>}
    </section>
  )
}
