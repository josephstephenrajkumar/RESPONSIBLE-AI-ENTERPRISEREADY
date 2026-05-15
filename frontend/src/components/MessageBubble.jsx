export default function MessageBubble({ role, text, responsibleAI, isError = false }) {
  const className = `${role === 'assistant' ? 'bubble assistant' : 'bubble user'}${isError ? ' error' : ''}`
  const privacy = responsibleAI?.privacy || {}
  const safety = responsibleAI?.safety || {}
  const fairness = responsibleAI?.fairness || {}
  const explainability = responsibleAI?.explainability || {}
  const verifiability = responsibleAI?.verifiability || {}
  const transparency = responsibleAI?.transparency || {}
  const governance = responsibleAI?.governance || {}
  const controllability = responsibleAI?.controllability || {}

  const hasStructuredEvaluation = 
    privacy.privacy_risk !== undefined ||
    safety.safety_risk !== undefined ||
    fairness.fairness_risk !== undefined ||
    explainability.explanation_provided !== undefined ||
    verifiability.verifiability_score !== undefined ||
    transparency.transparency_level !== undefined

  return (
    <div className={className}>
      <div className="bubble-role">{role}</div>
      <div>{text}</div>
      {responsibleAI && (
        <div className="responsible-ai-evaluation">
          <h4>Responsible AI Evaluation:</h4>
          {hasStructuredEvaluation ? (
            <div className="evaluation-details">
              <div className="evaluation-item">
                <strong>🔒 Privacy:</strong> {privacy.privacy_risk ?? privacy.privacy_engine ?? 'unknown'}
                {(privacy.detected_sensitive_terms || []).length > 0 && 
                  ` (${(privacy.detected_sensitive_terms || []).join(', ')})`}
              </div>
              <div className="evaluation-item">
                <strong>🛡️ Safety:</strong> {safety.safety_risk ?? safety.safety_engine ?? 'unknown'}
                {(safety.violations || []).length > 0 && 
                  ` (${(safety.violations || []).join(', ')})`}
              </div>
              <div className="evaluation-item">
                <strong>⚖️ Fairness:</strong> {fairness.fairness_risk ?? fairness.bias_score ?? 'unknown'}
                {(fairness.protected_attributes_examined || []).length > 0 && 
                  ` (${(fairness.protected_attributes_examined || []).join(', ')})`}
                {(fairness.biased_language_detected || []).length > 0 && 
                  ` - Biased: ${(fairness.biased_language_detected || []).join(', ')}`}
              </div>
              <div className="evaluation-item">
                <strong>📖 Explainability:</strong> {explainability.explanation_provided !== undefined ? (explainability.explanation_provided ? 'Yes' : 'No') : 'unknown'}
              </div>
              <div className="evaluation-item">
                <strong>✅ Verifiability:</strong> {verifiability.verifiability_score ?? 'unknown'}
                ({verifiability.citations_found ?? 0} citations)
              </div>
              <div className="evaluation-item">
                <strong>👁️ Transparency:</strong> {transparency.transparency_level ?? 'unknown'}
              </div>
              <div className="evaluation-item">
                <strong>🏛️ Governance:</strong> {governance.governance_concern ?? 'unknown'}
              </div>
              <div className="evaluation-item">
                <strong>🎛️ Controllability:</strong> {(controllability.controllability_properties || []).join(', ') || 'unknown'}
              </div>
            </div>
          ) : (
            <pre className="evaluation-fallback">{JSON.stringify(responsibleAI, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  )
}
