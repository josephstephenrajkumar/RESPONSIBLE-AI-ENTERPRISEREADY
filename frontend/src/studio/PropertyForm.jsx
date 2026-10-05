import { useEffect, useState } from 'react'
import { fetchStudioOptions } from '../api'
import { Button, Field } from '../components/ui'
import { DYNAMIC_SELECT_TYPES, STATIC_SELECT_TYPES, TEXT_TYPES, expression, samplePaths } from './flowModel'
import Markdown from './markdown'

// Renders a piece's property map as a form. Values are kept exactly as the engine expects
// (strings may carry {{expressions}}); dynamic dropdowns and dynamic property groups are
// resolved through the gateway's options endpoint.

export function DataPicker({ steps, onInsert }) {
  const [open, setOpen] = useState(false)
  if (!steps?.length) return null
  return (
    <span className="data-picker">
      <button type="button" className="ghost ui-btn-sm" onClick={() => setOpen(o => !o)}>{open ? 'Close' : 'Insert data'}</button>
      {open && (
        <div className="data-picker-menu">
          {steps.map(step => (
            <div key={step.name} className="data-picker-step">
              <div className="data-picker-title"><code>{step.name}</code> {step.displayName}</div>
              <button type="button" className="data-picker-item" onClick={() => { onInsert(expression(step.name)); setOpen(false) }}>whole output</button>
              {samplePaths(step.sample).slice(0, 40).map(item => (
                <button type="button" key={item.path} className="data-picker-item" title={item.preview} onClick={() => { onInsert(expression(step.name, item.path)); setOpen(false) }}>
                  <code>{item.path}</code> <span className="muted">{item.preview}</span>
                </button>
              ))}
              {!step.sample && <div className="muted" style={{ fontSize: '0.72rem', padding: '2px 6px' }}>Test this step to see its fields.</div>}
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

function TextInput({ prop, value, onChange, dataSteps, multiline }) {
  const insert = (expr) => onChange((value ?? '') + expr)
  const common = { value: value ?? '', placeholder: prop.defaultValue !== undefined && prop.defaultValue !== null ? String(prop.defaultValue) : '', onChange: (e) => onChange(e.target.value) }
  return (
    <div className="prop-input-row">
      {multiline ? <textarea rows={4} {...common} /> : <input type="text" inputMode={prop.type === 'NUMBER' ? 'decimal' : undefined} {...common} />}
      <DataPicker steps={dataSteps} onInsert={insert} />
    </div>
  )
}

function ObjectInput({ value, onChange }) {
  const rows = Object.entries(value && typeof value === 'object' && !Array.isArray(value) ? value : {})
  const update = (list) => onChange(Object.fromEntries(list.filter(([k]) => k !== '')))
  return (
    <div className="kv-editor">
      {rows.map(([k, v], i) => (
        <div key={i} className="kv-editor-row">
          <input value={k} placeholder="key" onChange={(e) => { const list = rows.slice(); list[i] = [e.target.value, v]; update(list) }} />
          <input value={typeof v === 'string' ? v : JSON.stringify(v)} placeholder="value" onChange={(e) => { const list = rows.slice(); list[i] = [k, e.target.value]; update(list) }} />
          <button type="button" className="ghost ui-btn-sm" onClick={() => update(rows.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button type="button" className="ghost ui-btn-sm" onClick={() => update([...rows, ['', '']])}>+ Add key</button>
    </div>
  )
}

function ArrayInput({ value, onChange }) {
  const text = Array.isArray(value) ? value.map(v => (typeof v === 'string' ? v : JSON.stringify(v))).join('\n') : (value ?? '')
  return <textarea rows={4} value={text} placeholder="One item per line" onChange={(e) => onChange(e.target.value.split('\n').filter(l => l !== ''))} />
}

function JsonInput({ value, onChange }) {
  const [text, setText] = useState(() => (typeof value === 'string' ? value : value ? JSON.stringify(value, null, 2) : ''))
  const [error, setError] = useState('')
  return (
    <div>
      <textarea rows={6} className="mono" value={text} onChange={(e) => { setText(e.target.value); try { onChange(e.target.value.trim() ? JSON.parse(e.target.value) : undefined); setError('') } catch { onChange(e.target.value); setError('kept as text (not valid JSON yet)') } }} />
      {error && <small className="muted">{error}</small>}
    </div>
  )
}

function DynamicSelect({ appId, context, prop, propKey, value, onChange, multiple }) {
  const [options, setOptions] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = async () => {
    setBusy(true); setError('')
    try {
      const result = await fetchStudioOptions(appId, { piece_name: context.pieceName, piece_version: context.pieceVersion, action_or_trigger_name: context.actionName, property_name: propKey, input: context.input })
      setOptions(result?.options || []); if (result?.disabled && result?.placeholder) setError(result.placeholder)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  useEffect(() => { if (options === null) load() }, [])
  const selected = multiple ? (Array.isArray(value) ? value.map(String) : []) : (value ?? '')
  return (
    <div className="prop-input-row">
      <select multiple={multiple} value={selected} onChange={(e) => onChange(multiple ? Array.from(e.target.selectedOptions).map(o => o.value) : e.target.value)}>
        {!multiple && <option value="">{busy ? 'Loading…' : 'Select…'}</option>}
        {(options || []).map(o => <option key={String(o.value)} value={typeof o.value === 'string' ? o.value : JSON.stringify(o.value)}>{o.label}</option>)}
      </select>
      <button type="button" className="ghost ui-btn-sm" disabled={busy} onClick={load}>{busy ? '…' : 'Reload'}</button>
      {error && <small className="muted">{error}</small>}
    </div>
  )
}

function DynamicProps({ appId, context, prop, propKey, value, onChange, dataSteps }) {
  const [props, setProps] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = async () => {
    setBusy(true); setError('')
    try {
      const result = await fetchStudioOptions(appId, { piece_name: context.pieceName, piece_version: context.pieceVersion, action_or_trigger_name: context.actionName, property_name: propKey, input: context.input })
      setProps(result && typeof result === 'object' && !Array.isArray(result) ? (result.options && !result.options.length && result.placeholder ? {} : result) : {})
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const nested = props && !('options' in props) ? props : {}
  return (
    <div className="dynamic-props">
      <div className="button-row"><button type="button" className="ghost ui-btn-sm" disabled={busy} onClick={load}>{busy ? 'Loading fields…' : (props ? 'Reload fields' : 'Load fields')}</button>{error && <small className="muted">{error}</small>}</div>
      {props && Object.keys(nested).length > 0 && (
        <PropertyForm appId={appId} props={nested} input={value && typeof value === 'object' ? value : {}} onChange={(next) => onChange(next)} context={context} dataSteps={dataSteps} nested variables={variables} />
      )}
      {props && Object.keys(nested).length === 0 && <small className="muted">No extra fields for the current values.</small>}
    </div>
  )
}

export default function PropertyForm({ appId, props, input, onChange, context, dataSteps, nested = false, authSlot = null, variables = {} }) {
  const set = (key, value) => onChange({ ...(input || {}), [key]: value })
  const entries = Object.entries(props || {})
  return (
    <div className={`prop-form ${nested ? 'nested' : ''}`}>
      {authSlot}
      {entries.map(([key, prop]) => {
        if (!prop || typeof prop !== 'object') return null
        const value = input?.[key]
        const label = prop.displayName || key
        if (prop.type === 'MARKDOWN') return <Markdown key={key} text={String(prop.description || prop.value || '')} variables={variables} />
        let control
        if (prop.type === 'CHECKBOX') control = <label className="toggle"><input type="checkbox" checked={Boolean(value)} onChange={(e) => set(key, e.target.checked)} /> {prop.description || ''}</label>
        else if (STATIC_SELECT_TYPES.has(prop.type)) {
          const multi = prop.type === 'STATIC_MULTI_SELECT_DROPDOWN'
          const opts = prop.options?.options || []
          control = <select multiple={multi} value={multi ? (Array.isArray(value) ? value.map(String) : []) : (value ?? '')} onChange={(e) => set(key, multi ? Array.from(e.target.selectedOptions).map(o => o.value) : e.target.value)}>{!multi && <option value="">Select…</option>}{opts.map(o => <option key={String(o.value)} value={typeof o.value === 'string' ? o.value : JSON.stringify(o.value)}>{o.label}</option>)}</select>
        }
        else if (DYNAMIC_SELECT_TYPES.has(prop.type)) control = <DynamicSelect appId={appId} context={context} prop={prop} propKey={key} value={value} onChange={(v) => set(key, v)} multiple={prop.type === 'MULTI_SELECT_DROPDOWN'} />
        else if (prop.type === 'DYNAMIC') control = <DynamicProps appId={appId} context={context} prop={prop} propKey={key} value={value} onChange={(v) => set(key, v)} dataSteps={dataSteps} />
        else if (prop.type === 'OBJECT') control = <ObjectInput value={value} onChange={(v) => set(key, v)} />
        else if (prop.type === 'ARRAY') control = <ArrayInput value={value} onChange={(v) => set(key, v)} />
        else if (prop.type === 'JSON') control = <JsonInput value={value} onChange={(v) => set(key, v)} />
        else if (prop.type === 'LONG_TEXT' || prop.type === 'RICH_TEXT') control = <TextInput prop={prop} value={value} onChange={(v) => set(key, v)} dataSteps={dataSteps} multiline />
        else if (TEXT_TYPES.has(prop.type) || prop.type === 'SECRET_TEXT') control = <TextInput prop={prop} value={value} onChange={(v) => set(key, v)} dataSteps={dataSteps} />
        else control = <TextInput prop={prop} value={typeof value === 'string' ? value : (value ? JSON.stringify(value) : '')} onChange={(v) => set(key, v)} dataSteps={dataSteps} />
        return <Field key={key} label={label} required={prop.required} hint={prop.type !== 'CHECKBOX' ? prop.description : undefined}>{control}</Field>
      })}
      {entries.length === 0 && !authSlot && <p className="muted">This step has no settings.</p>}
    </div>
  )
}
