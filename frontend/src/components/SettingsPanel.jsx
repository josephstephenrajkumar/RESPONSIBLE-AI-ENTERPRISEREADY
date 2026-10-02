import { useEffect, useState } from 'react'
import { fetchGatewayModels } from '../api'

export default function SettingsPanel({ settings, onChange }) {
  const update = (field, value) => onChange({ ...settings, [field]: value })
  const [models, setModels] = useState(null)
  const [gatewayNote, setGatewayNote] = useState('')

  // The model list is whatever the LiteLLM proxy currently serves (filtered by
  // the gateway allowlist), so operators can add or re-route models in
  // litellm/config.yaml without a frontend change.
  useEffect(() => {
    fetchGatewayModels()
      .then(data => {
        setModels(data.models || [])
        setGatewayNote(`${data.gateway_mode === 'proxy' ? 'LiteLLM proxy' : 'direct provider'} · judge: ${data.judge_model}`)
      })
      .catch(err => {
        setModels([])
        setGatewayNote(`Model list unavailable: ${err.message}`)
      })
  }, [])

  const hasList = Array.isArray(models) && models.length > 0
  const currentInList = hasList && models.includes(settings.model)

  return (
    <div className="panel">
      <h2>Chat Settings</h2>
      <div className="field">
        <label>Mode</label>
        <select value={settings.mode} onChange={(event) => update('mode', event.target.value)}>
          <option value="code">Code</option>
          <option value="framework">Framework</option>
        </select>
      </div>
      <div className="field">
        <label>Model</label>
        {hasList ? (
          <select value={currentInList ? settings.model : ''} onChange={(event) => update('model', event.target.value)}>
            {!currentInList && <option value="">{settings.model ? `${settings.model} (not served)` : 'Gateway default'}</option>}
            {models.map(model => <option key={model} value={model}>{model}</option>)}
          </select>
        ) : (
          <input value={settings.model} onChange={(event) => update('model', event.target.value)} />
        )}
        {gatewayNote && <span className="muted field-note">{gatewayNote}</span>}
      </div>
      <div className="field">
        <label>Temperature</label>
        <input type="range" min="0" max="1" step="0.1" value={settings.temperature} onChange={(event) => update('temperature', parseFloat(event.target.value))} />
        <span>{settings.temperature}</span>
      </div>
      <div className="field">
        <label>Max Tokens</label>
        <input type="number" min="50" max="2000" value={settings.max_tokens} onChange={(event) => update('max_tokens', parseInt(event.target.value, 10))} />
      </div>
      <div className="field checkbox">
        <label><input type="checkbox" checked={settings.explain} onChange={(event) => update('explain', event.target.checked)} /> Explain</label>
      </div>
      <div className="field checkbox">
        <label><input type="checkbox" checked={settings.verify} onChange={(event) => update('verify', event.target.checked)} /> Verify</label>
      </div>
    </div>
  )
}
