export default function PolicyTable({ policies, onEdit, onDisable, onApprove, onActivate, onDelete }) {
  return (
    <section className="panel">
      <div className="panel-title-row">
        <h2>Policy Registry</h2>
      </div>
      <div className="table-wrap">
        <table className="policy-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Category</th>
              <th>Severity</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Patterns</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {policies.map(policy => (
              <tr key={policy.id}>
                <td>{policy.name}</td>
                <td>{policy.category}</td>
                <td><span className={`pill severity-${policy.severity}`}>{policy.severity}</span></td>
                <td>{policy.policy_kind || 'regex'}</td>
                <td><span className={`pill status-${policy.status}`}>{policy.status}</span></td>
                <td>{policy.patterns.length}</td>
                <td className="action-cell">
                  <button className="ghost" onClick={() => onEdit(policy)}>Edit</button>
                  <button className="ghost" onClick={() => onDisable(policy)}>{policy.enabled ? 'Disable' : 'Enable'}</button>
                  <button className="ghost" onClick={() => onApprove(policy)}>Approve</button>
                  <button className="ghost" onClick={() => onActivate(policy)}>Activate</button>
                  <button className="danger" onClick={() => onDelete(policy)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
