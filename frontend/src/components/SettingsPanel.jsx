export default function SettingsPanel({ settings, onChange }) {
  const update = (field, value) => onChange({ ...settings, [field]: value })

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
        <input value={settings.model} onChange={(event) => update('model', event.target.value)} />
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
