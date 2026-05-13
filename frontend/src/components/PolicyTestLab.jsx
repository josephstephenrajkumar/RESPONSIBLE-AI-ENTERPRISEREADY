import { useState } from 'react'

export default function PolicyTestLab({ onRun, result, loading }) {
  const [message, setMessage] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    await onRun(message)
  }

  return (
    <section className="panel test-lab">
      <div className="panel-title-row">
        <h2>Policy Test Lab</h2>
      </div>
      <form onSubmit={submit}>
        <textarea value={message} onChange={event => setMessage(event.target.value)} rows="5" placeholder="Enter sample text to evaluate" required />
        <div className="button-row">
          <button type="submit" disabled={loading}>{loading ? 'Testing...' : 'Run Test'}</button>
        </div>
      </form>
      {result && (
        <div className="test-result">
          <div><strong>Blocked:</strong> {String(result.blocked)}</div>
          <div><strong>Risk:</strong> {result.risk_level}</div>
          <div><strong>Categories:</strong> {(result.matched_categories || []).join(', ') || 'none'}</div>
          <div><strong>Patterns:</strong> {(result.matched_patterns || []).join(', ') || 'none'}</div>
          <div><strong>Policy Version:</strong> {result.policy_version}</div>
          <div><strong>Validator Engine:</strong> {result.validator_engine}</div>
          <div>
            <strong>Matched Policy Detail:</strong>{' '}
            {(result.policy_violations || [])
              .map(item => `${item.category} (${item.severity}) -> ${(item.patterns || []).join(', ')}`)
              .join(' | ') || 'none'}
          </div>
        </div>
      )}
    </section>
  )
}
