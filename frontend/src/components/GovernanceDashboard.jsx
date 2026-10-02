export default function GovernanceDashboard({ policies, reloadInfo, onReload }) {
  const summary = policies.reduce((acc, policy) => {
    acc.total += 1
    acc[policy.status] = (acc[policy.status] || 0) + 1
    if (policy.enabled) acc.enabled += 1
    return acc
  }, { total: 0, enabled: 0 })

  const unhealthy = policies.filter(policy => policy.runtime_health)
  const autoDisabled = unhealthy.filter(policy => policy.runtime_health.permanent)

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
      {unhealthy.length > 0 && (
        <div className="policy-health-banner">
          <strong>
            {unhealthy.length} {unhealthy.length === 1 ? 'policy is' : 'policies are'} not enforcing
            {autoDisabled.length > 0 && ` (${autoDisabled.length} auto-disabled)`}
          </strong>
          <ul>
            {unhealthy.map(policy => (
              <li key={policy.id}>
                <em>{policy.name}</em> — {policy.runtime_health.error}
              </li>
            ))}
          </ul>
          <p className="muted">
            A policy whose validator cannot be imported is disabled automatically so the
            registry does not show it as active while it enforces nothing. Install the
            validator, or delete the policy, then use Reload Runtime.
          </p>
        </div>
      )}
      {reloadInfo && <p className="muted">Runtime loaded {reloadInfo.loaded_policies} policies, version {reloadInfo.policy_version}.</p>}
    </section>
  )
}
