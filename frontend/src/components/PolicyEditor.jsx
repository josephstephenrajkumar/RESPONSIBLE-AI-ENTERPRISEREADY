import { useEffect, useState } from 'react'

const emptyPolicy = {
  name: '',
  category: '',
  severity: 'medium',
  description: '',
  policy_kind: 'regex',
  enabled: true,
  source: 'manual',
  patternsText: '',
  hubUri: '',
  validatorClass: '',
  installLocalModels: false,
  runtimeParamsText: '{}',
  metadataText: '{}'
}

export default function PolicyEditor({ policy, onSubmit, onCancel }) {
  const [form, setForm] = useState(emptyPolicy)

  useEffect(() => {
    if (!policy) {
      setForm(emptyPolicy)
      return
    }
    setForm({
      ...policy,
      patternsText: (policy.patterns || []).map(item => item.pattern).join('\n'),
      hubUri: policy.hub_validators?.[0]?.hub_uri || '',
      validatorClass: policy.hub_validators?.[0]?.validator_class || '',
      installLocalModels: policy.hub_validators?.[0]?.install_local_models || false,
      runtimeParamsText: JSON.stringify(policy.hub_validators?.[0]?.runtime_params || {}, null, 2),
      metadataText: JSON.stringify(policy.hub_validators?.[0]?.metadata || {}, null, 2)
    })
  }, [policy])

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

  const submit = (event) => {
    event.preventDefault()
    const runtimeParams = JSON.parse(form.runtimeParamsText || '{}')
    const metadata = JSON.parse(form.metadataText || '{}')
    onSubmit({
      name: form.name,
      category: form.category,
      severity: form.severity,
      description: form.description,
      policy_kind: form.policy_kind,
      enabled: form.enabled,
      source: form.source,
      patterns: form.patternsText
        .split('\n')
        .map(pattern => pattern.trim())
        .filter(Boolean)
        .map(pattern => ({ pattern })),
      hub_validators: form.policy_kind === 'guardrails_hub'
        ? [{
            hub_uri: form.hubUri,
            validator_class: form.validatorClass,
            install_local_models: form.installLocalModels,
            runtime_params: runtimeParams,
            metadata
          }]
        : []
    })
  }

  return (
    <form className="panel policy-editor" onSubmit={submit}>
      <div className="panel-title-row">
        <h2>{policy ? 'Edit Policy' : 'Create Policy'}</h2>
      </div>
      <div className="form-grid">
        <label className="field">
          <span>Name</span>
          <input value={form.name} onChange={event => update('name', event.target.value)} required />
        </label>
        <label className="field">
          <span>Category</span>
          <input value={form.category} onChange={event => update('category', event.target.value)} required />
        </label>
        <label className="field">
          <span>Severity</span>
          <select value={form.severity} onChange={event => update('severity', event.target.value)}>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
        </label>
        <label className="field">
          <span>Policy Kind</span>
          <select value={form.policy_kind} onChange={event => update('policy_kind', event.target.value)}>
            <option value="regex">regex</option>
            <option value="guardrails_hub">guardrails hub</option>
          </select>
        </label>
        <label className="field">
          <span>Source</span>
          <input value={form.source} onChange={event => update('source', event.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Description</span>
        <textarea value={form.description} onChange={event => update('description', event.target.value)} rows="3" />
      </label>
      {form.policy_kind === 'regex' ? (
        <label className="field">
          <span>Regex Patterns</span>
          <textarea value={form.patternsText} onChange={event => update('patternsText', event.target.value)} rows="6" placeholder="One regex per line" />
        </label>
      ) : (
        <>
          <div className="form-grid">
            <label className="field">
              <span>Hub URI</span>
              <input value={form.hubUri} onChange={event => update('hubUri', event.target.value)} placeholder="hub://guardrails/toxic_language" required />
            </label>
            <label className="field">
              <span>Validator Class</span>
              <input value={form.validatorClass} onChange={event => update('validatorClass', event.target.value)} placeholder="ToxicLanguage" required />
            </label>
          </div>
          <label className="field">
            <span>Runtime Params JSON</span>
            <textarea value={form.runtimeParamsText} onChange={event => update('runtimeParamsText', event.target.value)} rows="5" />
          </label>
          <label className="field">
            <span>Metadata JSON</span>
            <textarea value={form.metadataText} onChange={event => update('metadataText', event.target.value)} rows="4" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={form.installLocalModels} onChange={event => update('installLocalModels', event.target.checked)} />
            <span>Validator installation may require local models</span>
          </label>
        </>
      )}
      <label className="checkbox-row">
        <input type="checkbox" checked={form.enabled} onChange={event => update('enabled', event.target.checked)} />
        <span>Enabled</span>
      </label>
      <div className="button-row">
        <button type="submit">{policy ? 'Save' : 'Create'}</button>
        {policy && <button type="button" className="ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  )
}
