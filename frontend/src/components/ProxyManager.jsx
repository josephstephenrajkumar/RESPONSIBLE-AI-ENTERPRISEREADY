import { useEffect, useState } from 'react'
import {
  deleteProviderCredential, fetchGatewaySettings, fetchLitellmConfig, fetchModelCatalog, fetchProxyOverview, litellmAdmin,
  rotateLitellmKey, seedLitellmDefaults, storeProviderCredential, toggleModel, toggleProvider, updateGatewaySetting
} from '../api'
import ModelCatalog from './ModelCatalog'
import { StatusDot, formatUsd } from './charts'

// LiteLLM Proxy Manager: one admin surface over the proxy's management API.
// Every call goes through the gateway (`/gateway/admin/litellm/*`, allow-listed,
// audited, admin key swapped in) — the browser never sees the proxy or its key.
// Each section lets an administrator DEFINE and EDIT, not just view.

const SECTIONS = [
  { id: 'overview', label: 'Overview', hint: 'health, counts, callbacks' },
  { id: 'providers', label: 'Providers', hint: 'enable / disable, credentials' },
  { id: 'models', label: 'Models', hint: 'catalogue, edit, default & judge' },
  { id: 'keys', label: 'Keys & Teams', hint: 'budgets, limits, rotation' },
  { id: 'mcp', label: 'MCP Servers', hint: 'register, edit, inspect' },
  { id: 'guardrails', label: 'Guardrails', hint: 'proxy-side, test, toggle' },
  { id: 'routing', label: 'Routing & Settings', hint: 'retries, fallbacks, callbacks, cache' },
  { id: 'spend', label: 'Spend', hint: "LiteLLM's own spend log" },
]

const SECRET_RE = /(KEY|SECRET|TOKEN|PASSWORD)/i

function Notice({ notice }) {
  if (!notice) return null
  return <div className={`notice ${notice.tone || 'ok'}`}>{notice.text}</div>
}
function useNotice() {
  const [notice, setNotice] = useState(null)
  return {
    notice,
    ok: (text) => setNotice({ tone: 'ok', text }),
    warn: (text) => setNotice({ tone: 'warn', text }),
    fail: (err) => setNotice({ tone: 'error', text: typeof err === 'string' ? err : (err?.message || 'Request failed') }),
    clear: () => setNotice(null),
  }
}
function JsonView({ value }) { return <pre className="json-view">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre> }
const csv = (v) => String(v || '').split(',').map(x => x.trim()).filter(Boolean)
const num = (v) => (v === '' || v === null || v === undefined ? undefined : Number(v))
const perMillionToToken = (v) => (v === '' || v === null || v === undefined ? undefined : Number(v) / 1_000_000)

// ---------------------------------------------------------------------------
function Overview() {
  const [data, setData] = useState(null)
  const n = useNotice()
  const load = () => fetchProxyOverview().then(setData).catch(n.fail)
  useEffect(() => { load() }, [])
  if (!data) return <><Notice notice={n.notice} /><p className="muted">Loading proxy overview...</p></>
  const ready = data.readiness?.status === 'healthy'
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Proxy overview</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <Notice notice={n.notice} />
      <div className="kv-grid">
        <div><span>Proxy</span><code>{data.proxy_url}</code></div>
        <div><span>Readiness <StatusDot status={ready ? 'ok' : 'error'} /></span>{data.readiness?.status} · db {data.readiness?.db}</div>
        <div><span>Models served</span>{data.counts?.models ?? 'n/a'}</div>
        <div><span>Stored credentials</span>{data.counts?.credentials ?? 'n/a'}</div>
        <div><span>Virtual keys</span>{data.counts?.keys ?? 'n/a'}</div>
        <div><span>Teams</span>{data.counts?.teams ?? 'n/a'}</div>
        <div><span>MCP servers</span>{data.counts?.mcp_servers ?? 'n/a'}</div>
        <div><span>Guardrails</span>{data.counts?.guardrails ?? 'n/a'}</div>
        <div><span>Callbacks</span>{(data.callbacks || []).map(c => c.name).join(', ') || 'none'}</div>
        <div><span>Default chat model</span><code>{data.settings?.default_model}</code></div>
        <div><span>Judge model</span><code>{data.settings?.judge_model}</code></div>
        <div><span>Enabled providers</span>{(data.providers || []).filter(p => p.enabled).map(p => p.display_name).join(', ') || 'none'}</div>
      </div>
      {data.admin_key_is_master && (
        <div className="notice warn" style={{ marginTop: 12 }}>
          The gateway manages the proxy with the LiteLLM <strong>master key</strong> (dev). Generate a scoped admin key in Keys &amp; Teams and store it in
          <code> litellm_gateway_key</code> / <code>LITELLM_ADMIN_API_KEY</code> before production (TD-25).
        </div>
      )}
      <h4>Spend by model (LiteLLM spend log)</h4>
      {data.spend_by_model?.length ? (
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Model</th><th>Total spend</th></tr></thead>
          <tbody>{data.spend_by_model.map(row => <tr key={row.model}><td><code>{row.model}</code></td><td>{formatUsd(row.total_spend, 6)}</td></tr>)}</tbody></table></div>
      ) : <p className="muted">No spend recorded by the proxy yet.</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function Providers({ canManage }) {
  const [catalog, setCatalog] = useState(null)
  const [keyInput, setKeyInput] = useState({})
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => fetchModelCatalog().then(setCatalog).catch(n.fail)
  useEffect(() => { load() }, [])
  if (!catalog) return <><Notice notice={n.notice} /><p className="muted">Loading providers...</p></>
  const act = async (label, fn) => { setBusy(label); n.clear(); try { await fn(); await load() } catch (err) { n.fail(err) } finally { setBusy('') } }
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Providers</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">
        A provider is usable when the <em>proxy</em> holds a credential for it — mounted by the deployment (<code>env</code>, AWS Secrets Manager via Terraform),
        stored here in LiteLLM's encrypted credential store (<code>litellm</code>), or IAM (<code>iam</code>, Amazon Bedrock). Disabling a provider hides its
        models from the chat selector and makes the gateway reject chat requests for them.
      </p>
      <Notice notice={n.notice} />
      <div className="provider-grid">
        {catalog.providers.map(p => (
          <div key={p.id} className={`provider-card${p.enabled ? '' : ' disabled'}`}>
            <h4>{p.display_name}<span className={`pill ${p.enabled ? 'enabled' : 'disabled'}`}>{p.enabled ? 'enabled' : p.has_credential ? 'disabled by admin' : 'no credential'}</span></h4>
            <p>Credential: {p.credential?.type === 'iam' ? 'IAM task role' : p.credential?.env} · sources: {p.credential_sources.join(', ') || 'none'} · {p.configured_models} model{p.configured_models === 1 ? '' : 's'}</p>
            {p.stored_credential && <p>Stored in LiteLLM DB as <code>{p.stored_credential.name}</code> by {p.stored_credential.created_by || 'unknown'}</p>}
            {p.credential_sources.includes('env') && <p className="muted">Deployment-managed key (Secrets Manager → proxy env). Replace it via Terraform, or store a LiteLLM-DB key below to use for new models.</p>}
            {p.credential?.type === 'api_key' && canManage && (
              <div className="inline-form" style={{ margin: '6px 0' }}>
                <label className="span-2">{p.stored_credential ? 'Replace stored API key' : 'API key (stored in LiteLLM DB, encrypted)'}
                  <input type="password" autoComplete="off" placeholder={`${p.credential.env} value`} value={keyInput[p.id] || ''} onChange={(e) => setKeyInput({ ...keyInput, [p.id]: e.target.value })} />
                </label>
                <button type="button" disabled={!keyInput[p.id] || busy === `cred:${p.id}`} onClick={() => act(`cred:${p.id}`, async () => { await storeProviderCredential(p.id, keyInput[p.id]); setKeyInput({ ...keyInput, [p.id]: '' }); n.ok(`${p.display_name} key stored in the proxy (encrypted). Add a model and test it.`) })}>
                  {busy === `cred:${p.id}` ? 'Storing...' : 'Store in proxy'}
                </button>
                {p.stored_credential && <button type="button" className="danger" disabled={busy === `delcred:${p.id}`} onClick={() => act(`delcred:${p.id}`, () => deleteProviderCredential(p.id))}>Remove stored key</button>}
              </div>
            )}
            <div className="button-row">
              {p.has_credential && canManage && (
                <button type="button" className={p.disabled_by_admin ? '' : 'ghost'} disabled={busy === `toggle:${p.id}`} onClick={() => act(`toggle:${p.id}`, () => toggleProvider(p.id, p.disabled_by_admin ? 'enable' : 'disable'))}>
                  {p.disabled_by_admin ? 'Enable provider' : 'Disable provider'}
                </button>
              )}
              <a className="muted" href={p.docs} target="_blank" rel="noreferrer">model docs ↗</a>
            </div>
            {!p.has_credential && <p className="muted">{p.how_to_enable}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function ModelEditor({ model, onClose, onSaved }) {
  const [form, setForm] = useState({
    model_name: model.model_name || '',
    input_cost_per_million: model.input_cost_per_million ?? '',
    output_cost_per_million: model.output_cost_per_million ?? '',
    description: model.description || '',
    extra: '{}',
  })
  const [busy, setBusy] = useState(false)
  const n = useNotice()
  const save = async () => {
    setBusy(true); n.clear()
    try {
      let extra = {}
      try { extra = JSON.parse(form.extra || '{}') } catch { throw new Error('Extra litellm_params must be valid JSON') }
      const litellm_params = { ...extra }
      if (form.input_cost_per_million !== '') litellm_params.input_cost_per_token = perMillionToToken(form.input_cost_per_million)
      if (form.output_cost_per_million !== '') litellm_params.output_cost_per_token = perMillionToToken(form.output_cost_per_million)
      const body = { model_name: form.model_name || undefined, litellm_params, model_info: { id: model.model_id, description: form.description || undefined } }
      await litellmAdmin('POST', '/model/update', body)
      onSaved(`Updated ${form.model_name}`)
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 'min(640px, 100%)' }} onClick={(e) => e.stopPropagation()}>
        <h3>Edit model <code>{model.model_name}</code></h3>
        <p className="muted">Routes to <code>{model.litellm_model}</code>. Changes go to LiteLLM <code>/model/update</code> and apply immediately.</p>
        <Notice notice={n.notice} />
        <div className="inline-form">
          <label className="span-2">Name in the gateway<input value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} /></label>
          <label>Input price ($/1M tokens)<input type="number" step="0.0001" value={form.input_cost_per_million} onChange={(e) => setForm({ ...form, input_cost_per_million: e.target.value })} /></label>
          <label>Output price ($/1M tokens)<input type="number" step="0.0001" value={form.output_cost_per_million} onChange={(e) => setForm({ ...form, output_cost_per_million: e.target.value })} /></label>
          <label className="span-2">Description<input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
          <label className="span-2">Extra litellm_params (JSON, e.g. {'{"reasoning_effort":"low","max_tokens":1024,"temperature":0.2}'})<textarea value={form.extra} onChange={(e) => setForm({ ...form, extra: e.target.value })} /></label>
        </div>
        <div className="button-row"><button type="button" disabled={busy} onClick={save}>{busy ? 'Saving...' : 'Save'}</button><button type="button" className="ghost" onClick={onClose}>Cancel</button></div>
      </div>
    </div>
  )
}

function Models({ canManage }) {
  const [settings, setSettings] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [editing, setEditing] = useState(null)
  const [allowlist, setAllowlist] = useState('')
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => Promise.all([fetchGatewaySettings(), fetchModelCatalog()]).then(([s, c]) => { setSettings(s); setCatalog(c); setAllowlist((s.overrides['chat.allowed_models'] || []).join(', ')) }).catch(n.fail)
  useEffect(() => { load() }, [])
  const setModelSetting = async (key, value) => {
    setBusy(key); n.clear()
    try { await updateGatewaySetting(key, value === '' ? null : value); n.ok(`${key} ${value ? 'updated' : 'reset to environment default'}`); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const toggle = async (model) => {
    setBusy(`m:${model.model_name}`); n.clear()
    try { await toggleModel(model.model_name, model.disabled_by_admin ? 'enable' : 'disable'); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const names = (catalog?.models || []).map(m => m.model_name)
  return (
    <div className="proxy-section">
      <h3>Default, judge and allowed models</h3>
      <Notice notice={n.notice} />
      {settings && (
        <div className="inline-form">
          <label>Default chat model
            <select disabled={!canManage || busy === 'chat.default_model'} value={settings.overrides['chat.default_model'] || ''} onChange={(e) => setModelSetting('chat.default_model', e.target.value)}>
              <option value="">environment default ({settings.env_defaults.default_model})</option>
              {names.map(nm => <option key={nm} value={nm}>{nm}</option>)}
            </select>
          </label>
          <label>Judge model (Ragas / TruLens)
            <select disabled={!canManage || busy === 'chat.judge_model'} value={settings.overrides['chat.judge_model'] || ''} onChange={(e) => setModelSetting('chat.judge_model', e.target.value)}>
              <option value="">environment default ({settings.env_defaults.judge_model})</option>
              {names.map(nm => <option key={nm} value={nm}>{nm}</option>)}
            </select>
          </label>
          <label className="span-2">Chat allowlist (comma separated; empty = all enabled models)
            <input value={allowlist} disabled={!canManage} onChange={(e) => setAllowlist(e.target.value)} placeholder={names.slice(0, 2).join(', ')} />
          </label>
          <button type="button" disabled={!canManage || busy === 'chat.allowed_models'} onClick={() => setModelSetting('chat.allowed_models', csv(allowlist))}>Save allowlist</button>
          <div><span className="muted">Effective: chat <code>{settings.default_model}</code> · judge <code>{settings.judge_model}</code> · allowlist {settings.allowed_models?.length ? settings.allowed_models.join(', ') : 'none'}</span></div>
        </div>
      )}
      {catalog && (
        <>
          <h3>Enable, disable and edit models</h3>
          <p className="muted">Disabled models stay configured on the proxy but are hidden from the chat selector and rejected by the gateway. Edit changes pricing, alias and model parameters on the proxy (runtime-added models).</p>
          <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Model</th><th>Provider</th><th>Source</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{catalog.models.map(m => (
              <tr key={m.model_id || m.model_name}><td><code>{m.model_name}</code></td><td>{m.provider}</td><td><span className={`pill source-${m.source}`}>{m.source === 'db' ? 'runtime' : 'config.yaml'}</span></td>
                <td><span className={`pill ${m.disabled_by_admin ? 'disabled' : 'enabled'}`}>{m.disabled_by_admin ? 'disabled' : 'enabled'}</span></td>
                <td><div className="action-cell">
                  <button type="button" className="ghost" disabled={!canManage || busy === `m:${m.model_name}`} onClick={() => toggle(m)}>{m.disabled_by_admin ? 'Enable' : 'Disable'}</button>
                  <button type="button" className="ghost" disabled={!canManage || m.source !== 'db'} title={m.source !== 'db' ? 'Models defined in config.yaml are edited in the repository' : ''} onClick={() => setEditing(m)}>Edit</button>
                </div></td></tr>))}</tbody></table></div>
        </>
      )}
      {editing && <ModelEditor model={editing} onClose={() => setEditing(null)} onSaved={(msg) => { setEditing(null); n.ok(msg); load() }} />}
      <ModelCatalog canManage={canManage} />
    </div>
  )
}

// ---------------------------------------------------------------------------
function KeysTeams({ canManage }) {
  const [teams, setTeams] = useState([])
  const [keys, setKeys] = useState([])
  const [models, setModels] = useState([])
  const [teamForm, setTeamForm] = useState({ team_alias: '', max_budget: '', budget_duration: '30d', models: '', rpm_limit: '', tpm_limit: '' })
  const [keyForm, setKeyForm] = useState({ key_alias: '', team_id: '', max_budget: '', budget_duration: '30d', rpm_limit: '', tpm_limit: '', duration: '', models: '' })
  const [editTeam, setEditTeam] = useState(null)
  const [editKey, setEditKey] = useState(null)
  const [generated, setGenerated] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = async () => {
    try {
      const [t, k, m] = await Promise.all([litellmAdmin('GET', '/team/list'), litellmAdmin('GET', '/key/list', undefined, { return_full_object: 'true', page: 1, size: 100 }), fetchModelCatalog()])
      setTeams(Array.isArray(t) ? t : []); setKeys(k.keys || []); setModels(m.models.map(x => x.model_name))
    } catch (err) { n.fail(err) }
  }
  useEffect(() => { load() }, [])
  const run = async (label, fn, okText) => { setBusy(label); n.clear(); try { const r = await fn(); if (okText) n.ok(okText); await load(); return r } catch (err) { n.fail(err) } finally { setBusy('') } }
  const createTeam = () => run('team', () => litellmAdmin('POST', '/team/new', { team_alias: teamForm.team_alias, max_budget: num(teamForm.max_budget), budget_duration: teamForm.budget_duration || undefined, models: csv(teamForm.models), rpm_limit: num(teamForm.rpm_limit), tpm_limit: num(teamForm.tpm_limit) }).then(() => setTeamForm({ team_alias: '', max_budget: '', budget_duration: '30d', models: '', rpm_limit: '', tpm_limit: '' })), `Team ${teamForm.team_alias} created`)
  const saveTeam = () => run('team-edit', () => litellmAdmin('POST', '/team/update', { team_id: editTeam.team_id, team_alias: editTeam.team_alias, max_budget: num(editTeam.max_budget), budget_duration: editTeam.budget_duration || undefined, models: csv(editTeam.models), rpm_limit: num(editTeam.rpm_limit), tpm_limit: num(editTeam.tpm_limit) }).then(() => setEditTeam(null)), 'Team updated')
  const createKey = () => run('key', async () => {
    const result = await litellmAdmin('POST', '/key/generate', { key_alias: keyForm.key_alias, team_id: keyForm.team_id || undefined, max_budget: num(keyForm.max_budget), budget_duration: keyForm.budget_duration || undefined, rpm_limit: num(keyForm.rpm_limit), tpm_limit: num(keyForm.tpm_limit), duration: keyForm.duration || undefined, models: csv(keyForm.models) })
    setGenerated(result)
  }, 'Key generated — copy it now, it is shown once.')
  const saveKey = () => run('key-edit', () => litellmAdmin('POST', '/key/update', { key: editKey.token, key_alias: editKey.key_alias, team_id: editKey.team_id || undefined, max_budget: num(editKey.max_budget), budget_duration: editKey.budget_duration || undefined, rpm_limit: num(editKey.rpm_limit), tpm_limit: num(editKey.tpm_limit), models: csv(editKey.models) }).then(() => setEditKey(null)), 'Key updated')
  const regenerate = (k) => { if (!window.confirm(`Rotate ${k.key_alias || k.token}? A new key with the same scope is issued and the old key stops working immediately.`)) return; run(`regen:${k.token}`, async () => { const r = await rotateLitellmKey(k.token); setGenerated(r) }, 'Key rotated — copy the new value now; the old key is deleted.') }
  const keyAction = (k, action) => { if (action === 'delete' && !window.confirm(`Delete key ${k.key_alias || k.token}?`)) return; run(`${action}:${k.token}`, () => action === 'delete' ? litellmAdmin('POST', '/key/delete', { keys: [k.token] }) : litellmAdmin('POST', `/key/${action}`, { key: k.token })) }
  const deleteTeam = (t) => { if (!window.confirm(`Delete team ${t.team_alias || t.team_id}?`)) return; run(`team:${t.team_id}`, () => litellmAdmin('POST', '/team/delete', { team_ids: [t.team_id] })) }
  const form = (state, set, fields) => (
    <div className="inline-form">
      {fields.map(f => <label key={f.key} className={f.span ? 'span-2' : ''}>{f.label}{f.options
        ? <select value={state[f.key] ?? ''} onChange={(e) => set({ ...state, [f.key]: e.target.value })}>{f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
        : <input type={f.type || 'text'} step={f.step} value={state[f.key] ?? ''} placeholder={f.placeholder} onChange={(e) => set({ ...state, [f.key]: e.target.value })} />}</label>)}
    </div>
  )
  const teamOptions = [{ value: '', label: 'none' }, ...teams.map(t => ({ value: t.team_id, label: t.team_alias || t.team_id }))]
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Teams (tenants) and virtual keys</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">Teams carry a budget, rate limits and model scope per tenant; keys belong to client applications and inherit the team's limits. Budgets are enforced by the proxy (HTTP 429 when exceeded).</p>
      <Notice notice={n.notice} />
      {generated?.key && (
        <div className="notice warn"><strong>Key (shown once):</strong><div className="secret-once">{generated.key}</div>
          Store it in Secrets Manager or hand it to the application owner.<div className="button-row" style={{ marginTop: 8 }}><button type="button" className="ghost" onClick={() => setGenerated(null)}>Dismiss</button></div></div>
      )}
      <h4>Teams</h4>
      {canManage && <>{form(teamForm, setTeamForm, [{ key: 'team_alias', label: 'Team alias', placeholder: 'tenant-acme' }, { key: 'max_budget', label: 'Budget (USD)', type: 'number', step: '0.01' }, { key: 'budget_duration', label: 'Budget duration', placeholder: '30d' }, { key: 'rpm_limit', label: 'RPM limit', type: 'number' }, { key: 'tpm_limit', label: 'TPM limit', type: 'number' }, { key: 'models', label: 'Models (comma separated, empty = all)', span: true, placeholder: models.slice(0, 2).join(', ') }])}
        <div className="button-row" style={{ marginBottom: 12 }}><button type="button" disabled={!teamForm.team_alias || busy === 'team'} onClick={createTeam}>{busy === 'team' ? 'Creating...' : 'Create team'}</button></div></>}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Team</th><th>Budget</th><th>Spend</th><th>Limits</th><th>Models</th><th>Keys</th><th></th></tr></thead>
        <tbody>{teams.map(t => <tr key={t.team_id}><td><code>{t.team_alias || t.team_id}</code></td><td>{t.max_budget != null ? `${formatUsd(t.max_budget)} / ${t.budget_duration || '∞'}` : 'none'}</td><td>{formatUsd(t.spend || 0, 6)}</td><td>{[t.rpm_limit && `${t.rpm_limit} rpm`, t.tpm_limit && `${t.tpm_limit} tpm`].filter(Boolean).join(', ') || '—'}</td><td>{(t.models || []).join(', ') || 'all'}</td><td>{keys.filter(k => k.team_id === t.team_id).length}</td>
          <td>{canManage && <div className="action-cell"><button type="button" className="ghost" onClick={() => setEditTeam({ team_id: t.team_id, team_alias: t.team_alias || '', max_budget: t.max_budget ?? '', budget_duration: t.budget_duration || '', models: (t.models || []).join(', '), rpm_limit: t.rpm_limit ?? '', tpm_limit: t.tpm_limit ?? '' })}>Edit</button><button type="button" className="danger" disabled={busy === `team:${t.team_id}`} onClick={() => deleteTeam(t)}>Delete</button></div>}</td></tr>)}
          {teams.length === 0 && <tr><td colSpan="7" className="muted">No teams yet.</td></tr>}</tbody></table></div>
      {editTeam && <div className="modal-backdrop" onClick={() => setEditTeam(null)}><div className="modal" style={{ width: 'min(640px,100%)' }} onClick={(e) => e.stopPropagation()}><h3>Edit team</h3>
        {form(editTeam, setEditTeam, [{ key: 'team_alias', label: 'Alias' }, { key: 'max_budget', label: 'Budget (USD)', type: 'number', step: '0.01' }, { key: 'budget_duration', label: 'Budget duration' }, { key: 'rpm_limit', label: 'RPM limit', type: 'number' }, { key: 'tpm_limit', label: 'TPM limit', type: 'number' }, { key: 'models', label: 'Models (comma separated)', span: true }])}
        <div className="button-row"><button type="button" disabled={busy === 'team-edit'} onClick={saveTeam}>Save</button><button type="button" className="ghost" onClick={() => setEditTeam(null)}>Cancel</button></div></div></div>}
      <h4>Virtual keys</h4>
      {canManage && <>{form(keyForm, setKeyForm, [{ key: 'key_alias', label: 'Key alias', placeholder: 'acme-web-app' }, { key: 'team_id', label: 'Team', options: teamOptions }, { key: 'max_budget', label: 'Budget (USD)', type: 'number', step: '0.01' }, { key: 'budget_duration', label: 'Budget duration', placeholder: '30d' }, { key: 'rpm_limit', label: 'RPM limit', type: 'number' }, { key: 'tpm_limit', label: 'TPM limit', type: 'number' }, { key: 'duration', label: 'Expires in', placeholder: '90d (empty = never)' }, { key: 'models', label: 'Models (comma separated, empty = all)', span: true }])}
        <div className="button-row" style={{ marginBottom: 12 }}><button type="button" disabled={!keyForm.key_alias || busy === 'key'} onClick={createKey}>{busy === 'key' ? 'Generating...' : 'Generate key'}</button></div></>}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Alias</th><th>Team</th><th>Budget</th><th>Spend</th><th>Limits</th><th>Models</th><th>Expires</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{keys.map(k => <tr key={k.token}><td><code>{k.key_alias || k.token.slice(0, 10) + '…'}</code></td><td>{teams.find(t => t.team_id === k.team_id)?.team_alias || k.team_id || '—'}</td><td>{k.max_budget != null ? `${formatUsd(k.max_budget)} / ${k.budget_duration || '∞'}` : 'none'}</td><td>{formatUsd(k.spend || 0, 6)}</td><td>{[k.rpm_limit && `${k.rpm_limit} rpm`, k.tpm_limit && `${k.tpm_limit} tpm`].filter(Boolean).join(', ') || '—'}</td><td>{(k.models || []).join(', ') || 'all'}</td><td>{k.expires ? new Date(k.expires).toLocaleDateString() : 'never'}</td><td><span className={`pill ${k.blocked ? 'status-active' : 'status-draft'}`}>{k.blocked ? 'blocked' : 'active'}</span></td>
          <td>{canManage && <div className="action-cell">
            <button type="button" className="ghost" onClick={() => setEditKey({ token: k.token, key_alias: k.key_alias || '', team_id: k.team_id || '', max_budget: k.max_budget ?? '', budget_duration: k.budget_duration || '', rpm_limit: k.rpm_limit ?? '', tpm_limit: k.tpm_limit ?? '', models: (k.models || []).join(', ') })}>Edit</button>
            <button type="button" className="ghost" disabled={busy === `regen:${k.token}`} onClick={() => regenerate(k)}>Rotate</button>
            <button type="button" className="ghost" onClick={() => keyAction(k, k.blocked ? 'unblock' : 'block')}>{k.blocked ? 'Unblock' : 'Block'}</button>
            <button type="button" className="danger" disabled={busy === `delete:${k.token}`} onClick={() => keyAction(k, 'delete')}>Delete</button></div>}</td></tr>)}
          {keys.length === 0 && <tr><td colSpan="9" className="muted">No virtual keys yet. The gateway itself uses the master key (TD-25); generate a scoped key for it here.</td></tr>}</tbody></table></div>
      {editKey && <div className="modal-backdrop" onClick={() => setEditKey(null)}><div className="modal" style={{ width: 'min(640px,100%)' }} onClick={(e) => e.stopPropagation()}><h3>Edit key <code>{editKey.key_alias}</code></h3>
        {form(editKey, setEditKey, [{ key: 'key_alias', label: 'Alias' }, { key: 'team_id', label: 'Team', options: teamOptions }, { key: 'max_budget', label: 'Budget (USD)', type: 'number', step: '0.01' }, { key: 'budget_duration', label: 'Budget duration' }, { key: 'rpm_limit', label: 'RPM limit', type: 'number' }, { key: 'tpm_limit', label: 'TPM limit', type: 'number' }, { key: 'models', label: 'Models (comma separated)', span: true }])}
        <div className="button-row"><button type="button" disabled={busy === 'key-edit'} onClick={saveKey}>Save</button><button type="button" className="ghost" onClick={() => setEditKey(null)}>Cancel</button></div></div></div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function McpServers({ canManage }) {
  const [servers, setServers] = useState([])
  const [tools, setTools] = useState({})
  const [health, setHealth] = useState({})
  const empty = { server_name: '', url: '', transport: 'http', auth_type: '', auth_value: '', description: '', allowed_tools: '' }
  const [form, setForm] = useState(empty)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => litellmAdmin('GET', '/v1/mcp/server').then(d => setServers(Array.isArray(d) ? d : [])).catch(n.fail)
  useEffect(() => { load() }, [])
  const nameOk = (v) => /^[A-Za-z0-9_]+$/.test(v || '')
  const payload = (f) => { const b = { server_name: f.server_name, alias: f.server_name, url: f.url, transport: f.transport, description: f.description || undefined, allowed_tools: csv(f.allowed_tools).length ? csv(f.allowed_tools) : undefined }; if (f.auth_type) { b.auth_type = f.auth_type; if (f.auth_value) b.credentials = { auth_value: f.auth_value } } return b }
  const run = async (label, fn, okText) => { setBusy(label); n.clear(); try { await fn(); if (okText) n.ok(okText); await load() } catch (err) { n.fail(err) } finally { setBusy('') } }
  const add = () => { if (!nameOk(form.server_name)) { n.fail('Server name may only contain letters, digits and underscores (LiteLLM uses it as the tool prefix).'); return } run('add', () => litellmAdmin('POST', '/v1/mcp/server', payload(form)).then(() => setForm(empty)), `MCP server ${form.server_name} registered`) }
  const save = () => run('edit', () => litellmAdmin('PUT', '/v1/mcp/server', { server_id: editing.server_id, ...payload(editing) }).then(() => setEditing(null)), 'MCP server updated')
  const inspect = async (s) => { setBusy(`tools:${s.server_id}`); try { const [t, h] = await Promise.all([litellmAdmin('GET', '/v1/mcp/tools', undefined, { server_id: s.server_id }), litellmAdmin('GET', '/v1/mcp/server/health', undefined, { server_id: s.server_id })]); setTools(prev => ({ ...prev, [s.server_id]: t.tools || [] })); setHealth(prev => ({ ...prev, [s.server_id]: Array.isArray(h) ? h[0] : h })) } catch (err) { n.fail(err) } finally { setBusy('') } }
  const remove = (s) => { if (!window.confirm(`Remove MCP server ${s.server_name || s.alias}?`)) return; run(`del:${s.server_id}`, () => litellmAdmin('DELETE', `/v1/mcp/server/${s.server_id}`)) }
  const fields = (state, set) => (
    <div className="inline-form">
      <label>Name (letters, digits, underscores)<input value={state.server_name} onChange={(e) => set({ ...state, server_name: e.target.value })} placeholder="deepwiki" style={state.server_name && !nameOk(state.server_name) ? { borderColor: '#dc2626' } : undefined} /></label>
      <label className="span-2">URL<input value={state.url} onChange={(e) => set({ ...state, url: e.target.value })} placeholder="https://mcp.example.com/mcp" /></label>
      <label>Transport<select value={state.transport} onChange={(e) => set({ ...state, transport: e.target.value })}><option value="http">http (streamable)</option><option value="sse">sse</option></select></label>
      <label>Auth<select value={state.auth_type} onChange={(e) => set({ ...state, auth_type: e.target.value })}><option value="">none</option><option value="api_key">api_key</option><option value="bearer_token">bearer_token</option><option value="basic">basic</option></select></label>
      {state.auth_type && <label>Auth value{editing && state === editing ? ' (leave empty to keep)' : ''}<input type="password" autoComplete="off" value={state.auth_value} onChange={(e) => set({ ...state, auth_value: e.target.value })} /></label>}
      <label className="span-2">Description<input value={state.description} onChange={(e) => set({ ...state, description: e.target.value })} /></label>
      <label className="span-2">Allowed tools (comma separated, empty = all)<input value={state.allowed_tools} onChange={(e) => set({ ...state, allowed_tools: e.target.value })} /></label>
    </div>
  )
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>MCP servers</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">MCP servers registered on the proxy expose their tools to agents through LiteLLM's MCP gateway with the same keys, budgets and logging as model calls. Register, inspect tools and health, restrict allowed tools, edit or remove.</p>
      <Notice notice={n.notice} />
      {canManage && <>{fields(form, setForm)}<div className="button-row" style={{ marginBottom: 12 }}><button type="button" disabled={!form.server_name || !nameOk(form.server_name) || !form.url || busy === 'add'} onClick={add}>{busy === 'add' ? 'Registering...' : 'Register server'}</button></div></>}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Name</th><th>URL</th><th>Transport</th><th>Auth</th><th>Allowed tools</th><th>Health</th><th>Tools</th><th>Actions</th></tr></thead>
        <tbody>{servers.map(s => <tr key={s.server_id}><td><code>{s.server_name || s.alias}</code><div className="muted">{s.description}</div></td><td><code>{s.url}</code></td><td>{s.transport}</td><td>{s.auth_type || 'none'}</td><td>{(s.allowed_tools || []).join(', ') || 'all'}</td>
          <td>{health[s.server_id] ? <span className={`pill ${health[s.server_id].status === 'healthy' ? 'enabled' : 'status-active'}`}>{health[s.server_id].status}</span> : '—'}</td>
          <td>{tools[s.server_id] ? (tools[s.server_id].length ? tools[s.server_id].map(t => <code key={t.name} style={{ display: 'block' }}>{t.name}</code>) : 'none') : '—'}</td>
          <td><div className="action-cell"><button type="button" className="ghost" disabled={busy === `tools:${s.server_id}`} onClick={() => inspect(s)}>{busy === `tools:${s.server_id}` ? 'Checking...' : 'Inspect'}</button>
            {canManage && <button type="button" className="ghost" onClick={() => setEditing({ server_id: s.server_id, server_name: s.server_name || s.alias || '', url: s.url || '', transport: s.transport || 'http', auth_type: s.auth_type || '', auth_value: '', description: s.description || '', allowed_tools: (s.allowed_tools || []).join(', ') })}>Edit</button>}
            {canManage && <button type="button" className="danger" disabled={busy === `del:${s.server_id}`} onClick={() => remove(s)}>Remove</button>}</div></td></tr>)}
          {servers.length === 0 && <tr><td colSpan="8" className="muted">No MCP servers registered.</td></tr>}</tbody></table></div>
      {editing && <div className="modal-backdrop" onClick={() => setEditing(null)}><div className="modal" style={{ width: 'min(720px,100%)' }} onClick={(e) => e.stopPropagation()}><h3>Edit MCP server</h3>{fields(editing, setEditing)}
        <div className="button-row"><button type="button" disabled={busy === 'edit'} onClick={save}>Save</button><button type="button" className="ghost" onClick={() => setEditing(null)}>Cancel</button></div></div></div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function Guardrails({ canManage }) {
  const [list, setList] = useState([])
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({ guardrail_name: '', guardrail: 'presidio', mode: 'pre_call', default_on: true, params: '{}' })
  const [testText, setTestText] = useState({})
  const [testResult, setTestResult] = useState({})
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => Promise.all([litellmAdmin('GET', '/guardrails/list'), litellmAdmin('GET', '/guardrails/ui/add_guardrail_settings')]).then(([l, s]) => { setList(l.guardrails || []); setSettings(s) }).catch(n.fail)
  useEffect(() => { load() }, [])
  const providers = settings?.supported_modes_by_provider ? Object.keys(settings.supported_modes_by_provider) : ['presidio', 'bedrock', 'lakera_v2', 'aporia']
  const run = async (label, fn, okText) => { setBusy(label); n.clear(); try { await fn(); if (okText) n.ok(okText); await load() } catch (err) { n.fail(err) } finally { setBusy('') } }
  const add = () => run('add', async () => {
    let params = {}; try { params = JSON.parse(form.params || '{}') } catch { throw new Error('Params must be valid JSON') }
    await litellmAdmin('POST', '/guardrails', { guardrail: { guardrail_name: form.guardrail_name, litellm_params: { guardrail: form.guardrail, mode: form.mode, default_on: form.default_on, ...params }, guardrail_info: { created_via: 'proxy-manager' } } })
    setForm({ ...form, guardrail_name: '', params: '{}' })
  }, `Guardrail ${form.guardrail_name} added`)
  const toggle = (g) => run(`toggle:${g.guardrail_id}`, () => litellmAdmin('PATCH', `/guardrails/${g.guardrail_id}`, { litellm_params: { ...g.litellm_params, default_on: !g.litellm_params?.default_on } }), `${g.guardrail_name} ${g.litellm_params?.default_on ? 'disabled by default' : 'enabled by default'}`)
  const remove = (g) => { if (!window.confirm(`Delete proxy guardrail ${g.guardrail_name}?`)) return; run(`del:${g.guardrail_id}`, () => litellmAdmin('DELETE', `/guardrails/${g.guardrail_id}`)) }
  const test = async (g) => { setBusy(`test:${g.guardrail_name}`); try { const r = await litellmAdmin('POST', '/guardrails/apply_guardrail', { guardrail_name: g.guardrail_name, text: testText[g.guardrail_name] || 'My card number is 4111 1111 1111 1111 and my email is jane@example.com' }); setTestResult(prev => ({ ...prev, [g.guardrail_name]: r })) } catch (err) { setTestResult(prev => ({ ...prev, [g.guardrail_name]: { error: err.message } })) } finally { setBusy('') } }
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Proxy-side guardrails</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">These run inside LiteLLM for every consumer of the proxy (pre-call, during-call or post-call). They complement this application's Guardrails AI policies on the Configuration tab, which carry the approval lifecycle. Toggle <em>default on</em>, test with sample text, or delete.</p>
      <Notice notice={n.notice} />
      {canManage && (
        <div className="inline-form">
          <label>Name<input value={form.guardrail_name} onChange={(e) => setForm({ ...form, guardrail_name: e.target.value })} placeholder="pii_pre_call" /></label>
          <label>Type<select value={form.guardrail} onChange={(e) => setForm({ ...form, guardrail: e.target.value })}>{providers.map(p => <option key={p} value={p}>{p}</option>)}</select></label>
          <label>Mode<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>{(settings?.supported_modes || ['pre_call', 'during_call', 'post_call']).map(m => <option key={m} value={m}>{m}</option>)}</select></label>
          <label className="toggle"><input type="checkbox" checked={form.default_on} onChange={(e) => setForm({ ...form, default_on: e.target.checked })} /> default on</label>
          <label className="span-2">Type-specific params (JSON, e.g. {'{"guardrailIdentifier":"...","guardrailVersion":"DRAFT"}'} for Bedrock)<textarea value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} /></label>
          <button type="button" disabled={!form.guardrail_name || busy === 'add'} onClick={add}>{busy === 'add' ? 'Adding...' : 'Add guardrail'}</button>
        </div>
      )}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Name</th><th>Type</th><th>Mode</th><th>Default on</th><th>Defined in</th><th>Test</th><th>Actions</th></tr></thead>
        <tbody>{list.map(g => <tr key={g.guardrail_id || g.guardrail_name}><td><code>{g.guardrail_name}</code></td><td>{g.litellm_params?.guardrail}</td><td>{Array.isArray(g.litellm_params?.mode) ? g.litellm_params.mode.join(', ') : g.litellm_params?.mode}</td>
          <td>{canManage && g.guardrail_id ? <button type="button" className={g.litellm_params?.default_on ? '' : 'ghost'} disabled={busy === `toggle:${g.guardrail_id}`} onClick={() => toggle(g)}>{g.litellm_params?.default_on ? 'on' : 'off'}</button> : String(g.litellm_params?.default_on ?? '')}</td>
          <td>{g.guardrail_definition_location || 'db'}</td>
          <td><div className="inline-form" style={{ margin: 0, gridTemplateColumns: '1fr auto' }}><input value={testText[g.guardrail_name] ?? ''} placeholder="sample text" onChange={(e) => setTestText({ ...testText, [g.guardrail_name]: e.target.value })} /><button type="button" className="ghost" disabled={busy === `test:${g.guardrail_name}`} onClick={() => test(g)}>Test</button></div>{testResult[g.guardrail_name] && <JsonView value={testResult[g.guardrail_name]} />}</td>
          <td>{canManage && g.guardrail_id && <button type="button" className="danger" disabled={busy === `del:${g.guardrail_id}`} onClick={() => remove(g)}>Delete</button>}</td></tr>)}
          {list.length === 0 && <tr><td colSpan="7" className="muted">No proxy-side guardrails configured.</td></tr>}</tbody></table></div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function FieldInput({ field, value, onChange }) {
  const t = field.field_type
  if (field.field_options?.length) return <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}><option value="">—</option>{field.field_options.map(o => <option key={o} value={o}>{o}</option>)}</select>
  if (t === 'Boolean') return <select value={value === true || value === 'true' ? 'true' : value === false || value === 'false' ? 'false' : ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === 'true')}><option value="">—</option><option value="true">true</option><option value="false">false</option></select>
  if (t === 'Integer' || t === 'Float') return <input type="number" step={t === 'Float' ? '0.01' : '1'} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  if (t === 'List') return <input value={Array.isArray(value) ? value.join(', ') : (value ?? '')} placeholder="comma separated" onChange={(e) => onChange(csv(e.target.value))} />
  return <input type={SECRET_RE.test(field.field_name) ? 'password' : 'text'} autoComplete="off" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
}

function Routing({ canManage }) {
  const [cfg, setCfg] = useState(null)
  const [router, setRouter] = useState({})
  const [fallbacks, setFallbacks] = useState('')
  const [lite, setLite] = useState({ drop_params: '', request_timeout: '' })
  const [cbName, setCbName] = useState('')
  const [cbVars, setCbVars] = useState({})
  const [cbFailure, setCbFailure] = useState(false)
  const [cache, setCache] = useState({})
  const [general, setGeneral] = useState({})
  const [yaml, setYaml] = useState('')
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = async () => {
    try {
      const [c, y] = await Promise.all([fetchLitellmConfig(), litellmAdmin('GET', '/config/yaml').catch(() => '')])
      setCfg(c)
      const r = c.router_settings || {}
      setRouter({ num_retries: r.num_retries ?? '', timeout: r.timeout ?? '', allowed_fails: r.allowed_fails ?? '', cooldown_time: r.cooldown_time ?? '', routing_strategy: r.routing_strategy || 'simple-shuffle', retry_after: r.retry_after ?? '' })
      setFallbacks(JSON.stringify(r.fallbacks || [], null, 1))
      setLite({ drop_params: String(c.defaults?.litellm_settings?.drop_params ?? ''), request_timeout: c.defaults?.litellm_settings?.request_timeout ?? '' })
      setCache({ ...(c.cache?.current_values || {}) })
      setGeneral(Object.fromEntries((c.general_settings_fields || []).map(f => [f.field_name, f.field_value])))
      setYaml(typeof y === 'string' ? y : (y?.data || y?.raw || JSON.stringify(y, null, 2)))
    } catch (err) { n.fail(err) }
  }
  useEffect(() => { load() }, [])
  const run = async (label, fn, okText) => { setBusy(label); n.clear(); try { const r = await fn(); n.ok(okText || `Done: ${JSON.stringify(r).slice(0, 140)}`); await load(); return r } catch (err) { n.fail(err) } finally { setBusy('') } }
  const saveRouter = () => run('router', async () => {
    let fb; try { fb = JSON.parse(fallbacks || '[]') } catch { throw new Error('Fallbacks must be a JSON list like [{"model-a": ["model-b"]}]') }
    const body = { router_settings: { num_retries: num(router.num_retries), timeout: num(router.timeout), allowed_fails: num(router.allowed_fails), cooldown_time: num(router.cooldown_time), routing_strategy: router.routing_strategy, retry_after: num(router.retry_after), fallbacks: fb } }
    Object.keys(body.router_settings).forEach(k => body.router_settings[k] === undefined && delete body.router_settings[k])
    return litellmAdmin('POST', '/config/update', body)
  }, 'Router settings saved on the proxy (persisted in its database)')
  const saveLite = () => run('lite', () => litellmAdmin('POST', '/config/update', { litellm_settings: { ...(lite.drop_params !== '' ? { drop_params: lite.drop_params === 'true' } : {}), ...(lite.request_timeout !== '' ? { request_timeout: Number(lite.request_timeout) } : {}) } }), 'LiteLLM settings saved')
  const addCallback = () => run('cb', () => litellmAdmin('POST', '/config/update', { litellm_settings: cbFailure ? { success_callback: [cbName], failure_callback: [cbName] } : { success_callback: [cbName] }, environment_variables: Object.fromEntries(Object.entries(cbVars).filter(([, v]) => v)) }).then(() => { setCbName(''); setCbVars({}) }), `Callback ${cbName} enabled`)
  const removeCallback = (name) => run(`cb-del:${name}`, () => litellmAdmin('POST', '/config/callback/delete', { callback_name: name }), `Callback ${name} removed`)
  const cacheBody = () => ({ cache_settings: { type: 'redis', ...Object.fromEntries(Object.entries(cache).filter(([, v]) => v !== '' && v !== null && v !== undefined)) } })
  const saveCache = () => run('cache', () => litellmAdmin('POST', '/cache/settings', cacheBody()), 'Cache settings saved; check Ping')
  const testCache = () => run('cache-test', () => litellmAdmin('POST', '/cache/settings/test', cacheBody()))
  const pingCache = () => run('cache-ping', () => litellmAdmin('GET', '/cache/ping'))
  const flushCache = () => { if (!window.confirm('Flush the entire response cache?')) return; run('cache-flush', () => litellmAdmin('POST', '/cache/flushall'), 'Cache flushed') }
  const saveGeneral = (field) => run(`gen:${field.field_name}`, () => litellmAdmin('POST', '/config/field/update', { field_name: field.field_name, field_value: general[field.field_name], config_type: 'general_settings' }), `${field.field_name} saved`)
  const reseed = () => { if (!window.confirm('Re-apply the shipped runtime defaults? Current router/litellm settings on the proxy will be overwritten.')) return; run('seed', () => seedLitellmDefaults(true), 'Defaults re-applied') }
  if (!cfg) return <><Notice notice={n.notice} /><p className="muted">Loading proxy configuration...</p></>
  const callbacks = cfg.callbacks || []
  const available = Object.entries(cfg.available_callbacks || {})
  const selected = available.find(([k]) => k === cbName)?.[1]
  const editableGeneral = (cfg.general_settings_fields || []).filter(f => f.editable !== false && !f.premium_field)
  const tabs = [...new Set(editableGeneral.map(f => f.field_tab || 'general'))]
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Routing, callbacks, cache and settings</h3><div className="button-row"><button className="ghost" onClick={load}>Refresh</button>{canManage && <button className="ghost" disabled={busy === 'seed'} onClick={reseed}>Re-apply shipped defaults</button>}</div></div>
      <Notice notice={n.notice} />
      <p className="muted">
        <code>litellm/config.yaml</code> is bootstrap-only (models, keys, database, platform OTel callback). Everything below is stored in the proxy database by LiteLLM
        (<code>POST /config/update</code>, <code>/cache/settings</code>, <code>/config/field/update</code>), survives restarts, and was seeded from
        <code> backend/app/litellm_runtime_defaults.json</code>{cfg.seeded ? '' : ' (not yet seeded — save or re-apply defaults)'}.
      </p>

      <h4>Router settings</h4>
      <div className="inline-form">
        <label>Retries<input type="number" value={router.num_retries} disabled={!canManage} onChange={(e) => setRouter({ ...router, num_retries: e.target.value })} /></label>
        <label>Timeout (s)<input type="number" value={router.timeout} disabled={!canManage} onChange={(e) => setRouter({ ...router, timeout: e.target.value })} /></label>
        <label>Allowed fails before cooldown<input type="number" value={router.allowed_fails} disabled={!canManage} onChange={(e) => setRouter({ ...router, allowed_fails: e.target.value })} /></label>
        <label>Cooldown (s)<input type="number" value={router.cooldown_time} disabled={!canManage} onChange={(e) => setRouter({ ...router, cooldown_time: e.target.value })} /></label>
        <label>Retry after (s)<input type="number" value={router.retry_after} disabled={!canManage} onChange={(e) => setRouter({ ...router, retry_after: e.target.value })} /></label>
        <label>Routing strategy<select value={router.routing_strategy} disabled={!canManage} onChange={(e) => setRouter({ ...router, routing_strategy: e.target.value })}>{['simple-shuffle', 'least-busy', 'usage-based-routing-v2', 'latency-based-routing', 'cost-based-routing'].map(s => <option key={s} value={s}>{s}</option>)}</select></label>
        <label className="span-2">Fallbacks (JSON list: model → fallback models)<textarea value={fallbacks} disabled={!canManage} onChange={(e) => setFallbacks(e.target.value)} /></label>
        {canManage && <button type="button" disabled={busy === 'router'} onClick={saveRouter}>{busy === 'router' ? 'Saving...' : 'Save router settings'}</button>}
      </div>

      <h4>LiteLLM settings</h4>
      <div className="inline-form">
        <label>drop_params<select value={lite.drop_params} disabled={!canManage} onChange={(e) => setLite({ ...lite, drop_params: e.target.value })}><option value="">—</option><option value="true">true</option><option value="false">false</option></select></label>
        <label>request_timeout (s)<input type="number" value={lite.request_timeout} disabled={!canManage} onChange={(e) => setLite({ ...lite, request_timeout: e.target.value })} /></label>
        {canManage && <button type="button" disabled={busy === 'lite'} onClick={saveLite}>Save LiteLLM settings</button>}
        <div className="span-2 muted">Proxy reports live: {Object.entries(cfg.litellm_settings_live || {}).map(([k, v]) => `${k}=${v}`).join(' · ') || 'n/a'}. Per-request timeouts are governed by the router timeout above; LiteLLM applies <code>request_timeout</code> from its database only at start-up.</div>
      </div>

      <h4>Callbacks (logging / observability)</h4>
      {callbacks.length ? (
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Callback</th><th>Type</th><th>Variables</th><th></th></tr></thead>
          <tbody>{callbacks.map(c => <tr key={c.name}><td><code>{c.name}</code></td><td>{c.type}</td><td>{Object.entries(c.variables || {}).filter(([, v]) => v).map(([k, v]) => <div key={k}><code>{k}</code>={SECRET_RE.test(k) ? '••••' : String(v).slice(0, 60)}</div>)}</td>
            <td>{canManage && c.name !== 'otel' && <button type="button" className="danger" disabled={busy === `cb-del:${c.name}`} onClick={() => removeCallback(c.name)}>Remove</button>}{c.name === 'otel' && <span className="muted">pinned in config.yaml</span>}</td></tr>)}</tbody></table></div>
      ) : <p className="muted">No callbacks configured.</p>}
      {canManage && (
        <div className="inline-form">
          <label>Add callback<select value={cbName} onChange={(e) => { setCbName(e.target.value); setCbVars({}) }}><option value="">choose…</option>{available.map(([k, v]) => <option key={k} value={k}>{v.ui_callback_name || k}</option>)}</select></label>
          {selected && (selected.litellm_callback_params || []).map(v => <label key={v}>{v}<input type={SECRET_RE.test(v) ? 'password' : 'text'} autoComplete="off" value={cbVars[v] || ''} onChange={(e) => setCbVars({ ...cbVars, [v]: e.target.value })} /></label>)}
          {selected && <label className="toggle"><input type="checkbox" checked={cbFailure} onChange={(e) => setCbFailure(e.target.checked)} /> also on failures</label>}
          {selected && <button type="button" disabled={busy === 'cb'} onClick={addCallback}>{busy === 'cb' ? 'Enabling...' : 'Enable callback'}</button>}
        </div>
      )}
      <p className="muted">Credentials entered for a callback are stored by LiteLLM as encrypted environment variables in its database and never by this application.</p>

      <h4>Response cache (Redis)</h4>
      <p className="muted">Status: {cfg.cache_ping?.status === 'healthy' ? <span className="pill enabled">connected</span> : <span className="pill disabled">not initialized</span>} — provision ElastiCache first (see <code>docs/RESPONSE_CACHING.md</code>), then set the connection here, Test, Save and Ping.</p>
      <div className="inline-form">
        {(cfg.cache?.fields || []).filter(f => ['redis_type', 'url', 'host', 'port', 'db', 'password', 'username', 'ssl', 'namespace', 'ttl', 'max_connections', 'aws_iam_auth', 'aws_iam_region', 'aws_iam_serverless', 'aws_iam_cache_name'].includes(f.field_name)).map(f => (
          <label key={f.field_name} title={f.field_description || ''}>{f.ui_field_name || f.field_name}{canManage ? <FieldInput field={{ ...f, field_options: f.options }} value={cache[f.field_name]} onChange={(v) => setCache({ ...cache, [f.field_name]: v })} /> : <input value={cache[f.field_name] ?? ''} disabled />}</label>
        ))}
        {canManage && <><button type="button" className="ghost" disabled={busy === 'cache-test'} onClick={testCache}>Test connection</button><button type="button" disabled={busy === 'cache'} onClick={saveCache}>Save cache settings</button><button type="button" className="ghost" disabled={busy === 'cache-ping'} onClick={pingCache}>Ping</button><button type="button" className="danger" disabled={busy === 'cache-flush'} onClick={flushCache}>Flush</button></>}
      </div>

      <h4>General settings</h4>
      <p className="muted">LiteLLM's general proxy settings (field metadata from <code>/config/list</code>); saved per field with <code>/config/field/update</code>.</p>
      {tabs.map(tab => (
        <details key={tab} style={{ marginBottom: 8 }}><summary style={{ cursor: 'pointer', fontWeight: 600 }}>{tab} ({editableGeneral.filter(f => (f.field_tab || 'general') === tab).length})</summary>
          <div className="kv-grid" style={{ marginTop: 8 }}>
            {editableGeneral.filter(f => (f.field_tab || 'general') === tab).map(f => (
              <div key={f.field_name} title={f.field_description || ''}><span>{f.field_name} · {f.field_type}{f.field_default_value !== null && f.field_default_value !== undefined ? ` · default ${JSON.stringify(f.field_default_value)}` : ''}{f.stored_in_db ? ' · in DB' : ''}</span>
                <div className="inline-form" style={{ margin: '4px 0 0', gridTemplateColumns: '1fr auto' }}>{canManage ? <FieldInput field={f} value={general[f.field_name]} onChange={(v) => setGeneral({ ...general, [f.field_name]: v })} /> : <input value={general[f.field_name] ?? ''} disabled />}{canManage && <button type="button" className="ghost" disabled={busy === `gen:${f.field_name}`} onClick={() => saveGeneral(f)}>Save</button>}</div></div>
            ))}
          </div></details>
      ))}

      <details style={{ marginTop: 12 }}><summary style={{ cursor: 'pointer', fontWeight: 600 }}>Bootstrap config.yaml (repository-managed, read-only)</summary><pre className="json-view">{yaml}</pre><p className="muted">Pinned here: {(cfg.pinned_in_config_yaml || []).join(', ')}. Change these in Git, plan/apply <code>ecs-litellm-proxy</code>, force a new deployment.</p></details>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Spend() {
  const [data, setData] = useState(null)
  const n = useNotice()
  const load = async () => {
    try {
      const [models, keys, teams, providers, logs] = await Promise.all([litellmAdmin('GET', '/global/spend/models'), litellmAdmin('GET', '/global/spend/keys'), litellmAdmin('GET', '/global/spend/teams'), litellmAdmin('GET', '/global/spend/provider'), litellmAdmin('GET', '/spend/logs', undefined, { limit: 25 })])
      setData({ models, keys, teams, providers, logs })
    } catch (err) { n.fail(err) }
  }
  useEffect(() => { load() }, [])
  if (!data) return <><Notice notice={n.notice} /><p className="muted">Loading LiteLLM spend...</p></>
  const table = (rows, cols) => (
    <div className="table-wrap"><table className="policy-table finops-table"><thead><tr>{cols.map(c => <th key={c.key}>{c.label}</th>)}</tr></thead>
      <tbody>{(Array.isArray(rows) ? rows : []).slice(0, 25).map((r, i) => <tr key={i}>{cols.map(c => <td key={c.key}>{c.render ? c.render(r) : String(r[c.key] ?? '')}</td>)}</tr>)}
        {(!Array.isArray(rows) || rows.length === 0) && <tr><td colSpan={cols.length} className="muted">No data.</td></tr>}</tbody></table></div>
  )
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>LiteLLM spend (proxy view)</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">LiteLLM's own spend log across all consumers of the proxy; reconcile with the FinOps tab (this application's metering).</p>
      <Notice notice={n.notice} />
      <div className="eval-columns">
        <div><h4>By model</h4>{table(data.models, [{ key: 'model', label: 'Model' }, { key: 'total_spend', label: 'Spend', render: r => formatUsd(r.total_spend, 6) }])}</div>
        <div><h4>By provider</h4>{table(data.providers, [{ key: 'provider', label: 'Provider' }, { key: 'spend', label: 'Spend', render: r => formatUsd(r.spend ?? r.total_spend, 6) }])}</div>
      </div>
      <div className="eval-columns">
        <div><h4>By key</h4>{table(data.keys, [{ key: 'key_alias', label: 'Key', render: r => r.key_alias || (r.api_key || '').slice(0, 10) + '…' }, { key: 'total_spend', label: 'Spend', render: r => formatUsd(r.total_spend ?? r.spend, 6) }])}</div>
        <div><h4>By team</h4>{table(data.teams, [{ key: 'team_alias', label: 'Team', render: r => r.team_alias || r.team_id }, { key: 'total_spend', label: 'Spend', render: r => formatUsd(r.total_spend ?? r.spend, 6) }])}</div>
      </div>
      <h4>Recent spend log entries</h4>
      {table(data.logs, [{ key: 'startTime', label: 'Time', render: r => r.startTime ? new Date(r.startTime).toLocaleString() : '' }, { key: 'model', label: 'Model' }, { key: 'call_type', label: 'Call' }, { key: 'total_tokens', label: 'Tokens' }, { key: 'spend', label: 'Spend', render: r => formatUsd(r.spend, 6) }, { key: 'end_user', label: 'End user' }])}
    </div>
  )
}

// ---------------------------------------------------------------------------
export default function ProxyManager({ canManage }) {
  const [section, setSection] = useState('overview')
  const Body = { overview: Overview, providers: Providers, models: Models, keys: KeysTeams, mcp: McpServers, guardrails: Guardrails, routing: Routing, spend: Spend }[section]
  return (
    <section className="panel">
      <div className="panel-title-row">
        <div>
          <h2>LiteLLM Proxy Manager</h2>
          <p className="muted">Configure the model gateway from one place. Actions are authenticated with your Cognito role, forwarded to the proxy's management API by the gateway, and recorded in the policy audit trail.</p>
        </div>
        {!canManage && <span className="pill disabled">read-only</span>}
      </div>
      <div className="proxy-layout">
        <nav className="proxy-nav" aria-label="Proxy manager sections">
          {SECTIONS.map(s => <button key={s.id} type="button" className={section === s.id ? 'active' : ''} onClick={() => setSection(s.id)}>{s.label}<small>{s.hint}</small></button>)}
        </nav>
        <div><Body canManage={canManage} /></div>
      </div>
    </section>
  )
}
