export default function PolicyApprovalModal({ policy, onClose, onConfirm }) {
  if (!policy) return null

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Approve Policy</h2>
        <p>{policy.name}</p>
        <p className="muted">Approval moves this policy into the approved lifecycle state. Activation is still separate.</p>
        <div className="button-row">
          <button onClick={() => onConfirm(policy)}>Approve</button>
          <button className="ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}
