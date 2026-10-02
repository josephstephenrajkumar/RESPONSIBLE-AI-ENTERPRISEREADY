import { useEffect, useState } from 'react'
import {
  deleteProviderCredential, fetchGatewaySettings, fetchModelCatalog, fetchProxyOverview, litellmAdmin,
  storeProviderCredential, toggleModel, toggleProvider, updateGatewaySetting
} from '../api'
import ModelCatalog from './ModelCatalog'
import { StatusDot, formatUsd } from './charts'

// LiteLLM Proxy Manager: one admin surface over the proxy's management API.
// Every call goes through the gateway (`/gateway/admin/litellm/*`, allow-listed,
// audited, admin key swapped in) — the browser never sees the proxy or its key.

const SECTIONS = [
  { id: 'overview', label: 'Overview', hint: 'health, counts, callbacks' },
  { id: 'providers', label: 'Providers', hint: 'enable / disable, credentials' },
  { id: 'models', label: 'Models', hint: 'catalogue, default & judge' },
  { id: 'keys', label: 'Keys & Teams', hint: 'virtual keys, budgets, limits' },
  { id: 'mcp', label: 'MCP Servers', hint: 'tools exposed via the proxy' },
  { id: 'guardrails', label: 'Guardrails', hint: 'proxy-side guardrails' },
  { id: 'routing', label: 'Routing & Settings', hint: 'retries, fallbacks, cache' },
  { id: 'spend', label: 'Spend', hint: "LiteLLM's own spend log" },
]

function Notice({ notice }) {
  if (!notice) return null
  return <div className={`notice ${notice.tone || 'ok'}`}>{notice.text}</div>
}

function useNotice() {
  const [notice, setNotice] = useState(null)
  const ok = (text) => setNotice({ tone: 'ok', text })
  const fail = (err) => setNotice({ tone: 'error', text: typeof err === 'string' ? err : (err?.message || 'Request failed') })
  const warn = (text) => setNotice({ tone: 'warn', text })
  return { notice, ok, fail, warn, clear: () => setNotice(null) }
}

function JsonView({ value }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>
}

// ---------------------------------------------------------------------------
function Overview({ canManage }) {
  const [data, setData] = useState(null)
  const n = useNotice()
  const load = () => fetchProxyOverview().then(setData).catch(n.fail)
  useEffect(() => { load() }, [])
  if (!data) return <p className="muted">Loading proxy overview...</p>
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
          The gateway manages the proxy with the LiteLLM <strong>master key</strong> (dev). Issue a scoped admin key and store it in
          <code> litellm_gateway_key</code> / <code>LITELLM_ADMIN_API_KEY</code> before production (TD-25).
        </div>
      )}
      <h4>Spend by model (LiteLLM spend log)</h4>
      {data.spend_by_model?.length ? (
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Model</th><th>Total spend</th></tr></thead>
          <tbody>{data.spend_by_model.map(row => <tr key={row.model}><td><code>{row.model}</code></td><td>{formatUsd(row.total_spend, 6)}</td></tr>)}</tbody></table></div>
      ) : <p className="muted">No spend recorded by the proxy yet.</p>}
      <p className="muted">The FinOps tab is the application's own metering with tenant/user/purpose attribution; this table is LiteLLM's view, useful for reconciliation.</p>
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
  if (!catalog) return <p className="muted">Loading providers...</p>

  const act = async (label, fn) => {
    setBusy(label); n.clear()
    try { await fn(); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }

  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Providers</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">
        A provider is usable when the <em>proxy</em> holds a credential for it — mounted by the deployment (<code>env</code>),
        stored here in LiteLLM's encrypted credential store (<code>litellm</code>), or via IAM (<code>iam</code>, Amazon Bedrock).
        Disabling a provider hides its models from the chat selector and makes the gateway reject chat requests for them.
      </p>
      <Notice notice={n.notice} />
      <div className="provider-grid">
        {catalog.providers.map(p => (
          <div key={p.id} className={`provider-card${p.enabled ? '' : ' disabled'}`}>
            <h4>{p.display_name}<span className={`pill ${p.enabled ? 'enabled' : 'disabled'}`}>{p.enabled ? 'enabled' : p.has_credential ? 'disabled by admin' : 'no credential'}</span></h4>
            <p>Credential: {p.credential?.type === 'iam' ? 'IAM task role' : p.credential?.env} · sources: {p.credential_sources.join(', ') || 'none'} · {p.configured_models} model{p.configured_models === 1 ? '' : 's'}</p>
            {p.stored_credential && <p>Stored credential <code>{p.stored_credential.name}</code> by {p.stored_credential.created_by || 'unknown'}</p>}
            {p.credential?.type === 'api_key' && canManage && (
              <div className="inline-form" style={{ margin: '6px 0' }}>
                <label className="span-2">{p.stored_credential ? 'Replace API key' : 'API key'}
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
      <p className="muted">Keys entered here are sent once to the proxy over the private network and stored encrypted with <code>LITELLM_SALT_KEY</code>; this application never stores or logs them.</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Models({ canManage }) {
  const [settings, setSettings] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => Promise.all([fetchGatewaySettings(), fetchModelCatalog()]).then(([s, c]) => { setSettings(s); setCatalog(c) }).catch(n.fail)
  useEffect(() => { load() }, [])
  const setModelSetting = async (key, value) => {
    setBusy(key); n.clear()
    try { await updateGatewaySetting(key, value || null); n.ok(`${key} ${value ? `set to ${value}` : 'reset to environment default'}`); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const toggle = async (model) => {
    setBusy(`m:${model.model_name}`); n.clear()
    try { await toggleModel(model.model_name, model.disabled_by_admin ? 'enable' : 'disable'); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const names = (catalog?.models || []).map(m => m.model_name)
  return (
    <div className="proxy-section">
      <h3>Default and judge models</h3>
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
          <div><span className="muted">Effective: chat <code>{settings.default_model}</code> · judge <code>{settings.judge_model}</code></span></div>
        </div>
      )}
      {catalog && (
        <>
          <h3>Enable / disable models</h3>
          <p className="muted">Disabled models stay configured on the proxy but are hidden from the chat selector and rejected by the gateway.</p>
          <div className="button-row" style={{ marginBottom: 16 }}>
            {catalog.models.map(m => (
              <button key={m.model_name} type="button" className={m.disabled_by_admin ? 'danger' : 'ghost'} disabled={!canManage || busy === `m:${m.model_name}`} onClick={() => toggle(m)} title={m.disabled_by_admin ? 'Click to enable' : 'Click to disable'}>
                {m.disabled_by_admin ? '✕ ' : '✓ '}{m.model_name}
              </button>
            ))}
          </div>
        </>
      )}
      <ModelCatalog canManage={canManage} />
    </div>
  )
}

// ---------------------------------------------------------------------------
function KeysTeams({ canManage }) {
  const [teams, setTeams] = useState([])
  const [keys, setKeys] = useState([])
  const [models, setModels] = useState([])
  const [teamForm, setTeamForm] = useState({ team_alias: '', max_budget: '', budget_duration: '30d', models: '' })
  const [keyForm, setKeyForm] = useState({ key_alias: '', team_id: '', max_budget: '', budget_duration: '30d', rpm_limit: '', tpm_limit: '', duration: '', models: '' })
  const [generated, setGenerated] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = async () => {
    try {
      const [t, k, m] = await Promise.all([
        litellmAdmin('GET', '/team/list'),
        litellmAdmin('GET', '/key/list', undefined, { return_full_object: 'true', page: 1, size: 100 }),
        fetchModelCatalog(),
      ])
      setTeams(Array.isArray(t) ? t : []); setKeys(k.keys || []); setModels(m.models.map(x => x.model_name))
    } catch (err) { n.fail(err) }
  }
  useEffect(() => { load() }, [])
  const csv = (v) => v.split(',').map(x => x.trim()).filter(Boolean)
  const num = (v) => (v === '' ? undefined : Number(v))
  const createTeam = async () => {
    setBusy('team'); n.clear()
    try {
      await litellmAdmin('POST', '/team/new', { team_alias: teamForm.team_alias, max_budget: num(teamForm.max_budget), budget_duration: teamForm.budget_duration || undefined, models: csv(teamForm.models) })
      n.ok(`Team ${teamForm.team_alias} created`); setTeamForm({ team_alias: '', max_budget: '', budget_duration: '30d', models: '' }); await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const createKey = async () => {
    setBusy('key'); n.clear()
    try {
      const body = { key_alias: keyForm.key_alias, team_id: keyForm.team_id || undefined, max_budget: num(keyForm.max_budget), budget_duration: keyForm.budget_duration || undefined, rpm_limit: num(keyForm.rpm_limit), tpm_limit: num(keyForm.tpm_limit), duration: keyForm.duration || undefined, models: csv(keyForm.models) }
      const result = await litellmAdmin('POST', '/key/generate', body)
      setGenerated(result); n.ok(`Key ${result.key_alias || ''} generated — copy it now, it is shown once.`); await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const keyAction = async (k, action) => {
    setBusy(`${action}:${k.token}`); n.clear()
    try {
      if (action === 'delete') { if (!window.confirm(`Delete key ${k.key_alias || k.token}?`)) return; await litellmAdmin('POST', '/key/delete', { keys: [k.token] }) }
      else await litellmAdmin('POST', `/key/${action}`, { key: k.token })
      await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const deleteTeam = async (t) => {
    if (!window.confirm(`Delete team ${t.team_alias || t.team_id}? Keys in the team keep working but lose the team budget.`)) return
    setBusy(`team:${t.team_id}`); n.clear()
    try { await litellmAdmin('POST', '/team/delete', { team_ids: [t.team_id] }); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Teams (tenants) and virtual keys</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">Teams carry a budget and model scope per tenant; keys belong to client applications and inherit the team's limits. Budgets are enforced by the proxy (HTTP 429 when exceeded).</p>
      <Notice notice={n.notice} />
      {generated?.key && (
        <div className="notice warn">
          <strong>New key (shown once):</strong>
          <div className="secret-once">{generated.key}</div>
          Store it in Secrets Manager (e.g. <code>responsible-ai-dev/litellm_gateway_key</code>) or hand it to the client application owner.
          <div className="button-row" style={{ marginTop: 8 }}><button type="button" className="ghost" onClick={() => setGenerated(null)}>Dismiss</button></div>
        </div>
      )}
      <h4>Teams</h4>
      {canManage && (
        <div className="inline-form">
          <label>Team alias<input value={teamForm.team_alias} onChange={(e) => setTeamForm({ ...teamForm, team_alias: e.target.value })} placeholder="tenant-acme" /></label>
          <label>Monthly budget (USD)<input type="number" step="0.01" value={teamForm.max_budget} onChange={(e) => setTeamForm({ ...teamForm, max_budget: e.target.value })} /></label>
          <label>Budget duration<input value={teamForm.budget_duration} onChange={(e) => setTeamForm({ ...teamForm, budget_duration: e.target.value })} placeholder="30d" /></label>
          <label className="span-2">Models (comma separated, empty = all)<input value={teamForm.models} onChange={(e) => setTeamForm({ ...teamForm, models: e.target.value })} placeholder={models.slice(0, 2).join(', ')} /></label>
          <button type="button" disabled={!teamForm.team_alias || busy === 'team'} onClick={createTeam}>{busy === 'team' ? 'Creating...' : 'Create team'}</button>
        </div>
      )}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Team</th><th>Budget</th><th>Spend</th><th>Models</th><th>Keys</th><th></th></tr></thead>
        <tbody>
          {teams.map(t => <tr key={t.team_id}><td><code>{t.team_alias || t.team_id}</code></td><td>{t.max_budget != null ? `${formatUsd(t.max_budget)} / ${t.budget_duration || '∞'}` : 'none'}</td><td>{formatUsd(t.spend || 0, 6)}</td><td>{(t.models || []).join(', ') || 'all'}</td><td>{keys.filter(k => k.team_id === t.team_id).length}</td><td>{canManage && <button type="button" className="danger" disabled={busy === `team:${t.team_id}`} onClick={() => deleteTeam(t)}>Delete</button>}</td></tr>)}
          {teams.length === 0 && <tr><td colSpan="6" className="muted">No teams yet.</td></tr>}
        </tbody></table></div>
      <h4>Virtual keys</h4>
      {canManage && (
        <div className="inline-form">
          <label>Key alias<input value={keyForm.key_alias} onChange={(e) => setKeyForm({ ...keyForm, key_alias: e.target.value })} placeholder="acme-web-app" /></label>
          <label>Team<select value={keyForm.team_id} onChange={(e) => setKeyForm({ ...keyForm, team_id: e.target.value })}><option value="">none</option>{teams.map(t => <option key={t.team_id} value={t.team_id}>{t.team_alias || t.team_id}</option>)}</select></label>
          <label>Max budget (USD)<input type="number" step="0.01" value={keyForm.max_budget} onChange={(e) => setKeyForm({ ...keyForm, max_budget: e.target.value })} /></label>
          <label>Budget duration<input value={keyForm.budget_duration} onChange={(e) => setKeyForm({ ...keyForm, budget_duration: e.target.value })} placeholder="30d" /></label>
          <label>RPM limit<input type="number" value={keyForm.rpm_limit} onChange={(e) => setKeyForm({ ...keyForm, rpm_limit: e.target.value })} /></label>
          <label>TPM limit<input type="number" value={keyForm.tpm_limit} onChange={(e) => setKeyForm({ ...keyForm, tpm_limit: e.target.value })} /></label>
          <label>Expires in<input value={keyForm.duration} onChange={(e) => setKeyForm({ ...keyForm, duration: e.target.value })} placeholder="90d (empty = never)" /></label>
          <label className="span-2">Models (comma separated, empty = all)<input value={keyForm.models} onChange={(e) => setKeyForm({ ...keyForm, models: e.target.value })} /></label>
          <button type="button" disabled={!keyForm.key_alias || busy === 'key'} onClick={createKey}>{busy === 'key' ? 'Generating...' : 'Generate key'}</button>
        </div>
      )}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Alias</th><th>Team</th><th>Budget</th><th>Spend</th><th>Limits</th><th>Models</th><th>Expires</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          {keys.map(k => <tr key={k.token}><td><code>{k.key_alias || k.token.slice(0, 10) + '…'}</code></td><td>{teams.find(t => t.team_id === k.team_id)?.team_alias || k.team_id || '—'}</td><td>{k.max_budget != null ? `${formatUsd(k.max_budget)} / ${k.budget_duration || '∞'}` : 'none'}</td><td>{formatUsd(k.spend || 0, 6)}</td><td>{[k.rpm_limit && `${k.rpm_limit} rpm`, k.tpm_limit && `${k.tpm_limit} tpm`].filter(Boolean).join(', ') || '—'}</td><td>{(k.models || []).join(', ') || 'all'}</td><td>{k.expires ? new Date(k.expires).toLocaleDateString() : 'never'}</td><td><span className={`pill ${k.blocked ? 'status-active' : 'status-draft'}`}>{k.blocked ? 'blocked' : 'active'}</span></td>
            <td>{canManage && <div className="action-cell">
              <button type="button" className="ghost" disabled={busy.startsWith(k.blocked ? 'unblock' : 'block')} onClick={() => keyAction(k, k.blocked ? 'unblock' : 'block')}>{k.blocked ? 'Unblock' : 'Block'}</button>
              <button type="button" className="danger" disabled={busy === `delete:${k.token}`} onClick={() => keyAction(k, 'delete')}>Delete</button>
            </div>}</td></tr>)}
          {keys.length === 0 && <tr><td colSpan="9" className="muted">No virtual keys yet. The gateway itself currently uses the master key (TD-25); generate a scoped key for it here.</td></tr>}
        </tbody></table></div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function McpServers({ canManage }) {
  const [servers, setServers] = useState([])
  const [tools, setTools] = useState({})
  const [health, setHealth] = useState({})
  const [form, setForm] = useState({ server_name: '', url: '', transport: 'http', auth_type: '', auth_value: '', description: '' })
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => litellmAdmin('GET', '/v1/mcp/server').then(d => setServers(Array.isArray(d) ? d : [])).catch(n.fail)
  useEffect(() => { load() }, [])
  const add = async () => {
    setBusy('add'); n.clear()
    try {
      const body = { server_name: form.server_name, alias: form.server_name, url: form.url, transport: form.transport, description: form.description || undefined }
      if (form.auth_type) { body.auth_type = form.auth_type; body.credentials = { auth_value: form.auth_value } }
      await litellmAdmin('POST', '/v1/mcp/server', body)
      n.ok(`MCP server ${form.server_name} registered on the proxy`); setForm({ server_name: '', url: '', transport: 'http', auth_type: '', auth_value: '', description: '' }); await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const inspect = async (s) => {
    setBusy(`tools:${s.server_id}`)
    try {
      const [t, h] = await Promise.all([litellmAdmin('GET', '/v1/mcp/tools', undefined, { server_id: s.server_id }), litellmAdmin('GET', '/v1/mcp/server/health', undefined, { server_id: s.server_id })])
      setTools(prev => ({ ...prev, [s.server_id]: t.tools || [] })); setHealth(prev => ({ ...prev, [s.server_id]: Array.isArray(h) ? h[0] : h }))
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const remove = async (s) => {
    if (!window.confirm(`Remove MCP server ${s.server_name || s.alias}?`)) return
    setBusy(`del:${s.server_id}`); n.clear()
    try { await litellmAdmin('DELETE', `/v1/mcp/server/${s.server_id}`); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>MCP servers</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">MCP servers registered on the proxy expose their tools to agents through LiteLLM's MCP gateway (<code>/mcp</code>), with the same keys, budgets and logging as model calls. Register a server, then inspect its tools and health.</p>
      <Notice notice={n.notice} />
      {canManage && (
        <div className="inline-form">
          <label>Name<input value={form.server_name} onChange={(e) => setForm({ ...form, server_name: e.target.value })} placeholder="deepwiki" /></label>
          <label className="span-2">URL<input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://mcp.example.com/mcp" /></label>
          <label>Transport<select value={form.transport} onChange={(e) => setForm({ ...form, transport: e.target.value })}><option value="http">http (streamable)</option><option value="sse">sse</option></select></label>
          <label>Auth<select value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value })}><option value="">none</option><option value="api_key">api_key</option><option value="bearer_token">bearer_token</option><option value="basic">basic</option></select></label>
          {form.auth_type && <label>Auth value<input type="password" autoComplete="off" value={form.auth_value} onChange={(e) => setForm({ ...form, auth_value: e.target.value })} /></label>}
          <label className="span-2">Description<input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
          <button type="button" disabled={!form.server_name || !form.url || busy === 'add'} onClick={add}>{busy === 'add' ? 'Registering...' : 'Register server'}</button>
        </div>
      )}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Name</th><th>URL</th><th>Transport</th><th>Auth</th><th>Health</th><th>Tools</th><th>Actions</th></tr></thead>
        <tbody>
          {servers.map(s => <tr key={s.server_id}><td><code>{s.server_name || s.alias}</code><div className="muted">{s.description}</div></td><td><code>{s.url}</code></td><td>{s.transport}</td><td>{s.auth_type || 'none'}</td>
            <td>{health[s.server_id] ? <span className={`pill ${health[s.server_id].status === 'healthy' ? 'enabled' : 'status-active'}`}>{health[s.server_id].status}</span> : '—'}</td>
            <td>{tools[s.server_id] ? (tools[s.server_id].length ? tools[s.server_id].map(t => <code key={t.name} style={{ display: 'block' }}>{t.name}</code>) : 'none') : '—'}</td>
            <td><div className="action-cell"><button type="button" className="ghost" disabled={busy === `tools:${s.server_id}`} onClick={() => inspect(s)}>{busy === `tools:${s.server_id}` ? 'Checking...' : 'Inspect'}</button>{canManage && <button type="button" className="danger" disabled={busy === `del:${s.server_id}`} onClick={() => remove(s)}>Remove</button>}</div></td></tr>)}
          {servers.length === 0 && <tr><td colSpan="7" className="muted">No MCP servers registered.</td></tr>}
        </tbody></table></div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Guardrails({ canManage }) {
  const [list, setList] = useState([])
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({ guardrail_name: '', guardrail: 'presidio', mode: 'pre_call', default_on: true, params: '{}' })
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => Promise.all([litellmAdmin('GET', '/guardrails/list'), litellmAdmin('GET', '/guardrails/ui/add_guardrail_settings')]).then(([l, s]) => { setList(l.guardrails || []); setSettings(s) }).catch(n.fail)
  useEffect(() => { load() }, [])
  const providers = settings?.supported_modes_by_provider ? Object.keys(settings.supported_modes_by_provider) : ['presidio', 'bedrock', 'lakera_v2', 'aporia']
  const add = async () => {
    setBusy('add'); n.clear()
    try {
      let params = {}
      try { params = JSON.parse(form.params || '{}') } catch { throw new Error('Params must be valid JSON') }
      await litellmAdmin('POST', '/guardrails', { guardrail: { guardrail_name: form.guardrail_name, litellm_params: { guardrail: form.guardrail, mode: form.mode, default_on: form.default_on, ...params }, guardrail_info: { created_via: 'proxy-manager' } } })
      n.ok(`Guardrail ${form.guardrail_name} added to the proxy`); setForm({ ...form, guardrail_name: '', params: '{}' }); await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const remove = async (g) => {
    if (!window.confirm(`Delete proxy guardrail ${g.guardrail_name}?`)) return
    setBusy(`del:${g.guardrail_id}`); n.clear()
    try { await litellmAdmin('DELETE', `/guardrails/${g.guardrail_id}`); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Proxy-side guardrails</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted">
        These run inside LiteLLM for <em>every</em> consumer of the proxy (pre-call, during-call or post-call) — Bedrock Guardrails,
        Presidio PII, Lakera, Aporia and others. They complement, not replace, this application's Guardrails AI policies on the
        Configuration tab, which carry the approval lifecycle and audit trail.
      </p>
      <Notice notice={n.notice} />
      {canManage && (
        <div className="inline-form">
          <label>Name<input value={form.guardrail_name} onChange={(e) => setForm({ ...form, guardrail_name: e.target.value })} placeholder="pii-pre-call" /></label>
          <label>Type<select value={form.guardrail} onChange={(e) => setForm({ ...form, guardrail: e.target.value })}>{providers.map(p => <option key={p} value={p}>{p}</option>)}</select></label>
          <label>Mode<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>{(settings?.supported_modes || ['pre_call', 'during_call', 'post_call']).map(m => <option key={m} value={m}>{m}</option>)}</select></label>
          <label className="toggle"><input type="checkbox" checked={form.default_on} onChange={(e) => setForm({ ...form, default_on: e.target.checked })} /> default on</label>
          <label className="span-2">Type-specific params (JSON, e.g. {'{"guardrailIdentifier":"...","guardrailVersion":"DRAFT"}'} for Bedrock)
            <textarea value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} />
          </label>
          <button type="button" disabled={!form.guardrail_name || busy === 'add'} onClick={add}>{busy === 'add' ? 'Adding...' : 'Add guardrail'}</button>
        </div>
      )}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Name</th><th>Type</th><th>Mode</th><th>Default on</th><th>Defined in</th><th></th></tr></thead>
        <tbody>
          {list.map(g => <tr key={g.guardrail_id || g.guardrail_name}><td><code>{g.guardrail_name}</code></td><td>{g.litellm_params?.guardrail}</td><td>{Array.isArray(g.litellm_params?.mode) ? g.litellm_params.mode.join(', ') : g.litellm_params?.mode}</td><td>{String(g.litellm_params?.default_on ?? '')}</td><td>{g.guardrail_definition_location || 'db'}</td><td>{canManage && g.guardrail_id && <button type="button" className="danger" disabled={busy === `del:${g.guardrail_id}`} onClick={() => remove(g)}>Delete</button>}</td></tr>)}
          {list.length === 0 && <tr><td colSpan="6" className="muted">No proxy-side guardrails configured.</td></tr>}
        </tbody></table></div>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Routing({ canManage }) {
  const [settings, setSettings] = useState(null)
  const [callbacks, setCallbacks] = useState(null)
  const [cache, setCache] = useState(null)
  const [yaml, setYaml] = useState('')
  const [update, setUpdate] = useState('{\n  "litellm_settings": {}\n}')
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = async () => {
    try {
      const [s, c, k, y] = await Promise.all([litellmAdmin('GET', '/settings'), litellmAdmin('GET', '/get/config/callbacks'), litellmAdmin('GET', '/cache/settings'), litellmAdmin('GET', '/config/yaml')])
      setSettings(s); setCallbacks(c.callbacks || c); setCache(k); setYaml(typeof y === 'string' ? y : (y.data || y.raw || JSON.stringify(y, null, 2)))
    } catch (err) { n.fail(err) }
  }
  useEffect(() => { load() }, [])
  const apply = async () => {
    setBusy('update'); n.clear()
    try {
      let body
      try { body = JSON.parse(update) } catch { throw new Error('Update must be valid JSON') }
      const result = await litellmAdmin('POST', '/config/update', body)
      n.ok(`Config updated: ${JSON.stringify(result).slice(0, 160)}`); await load()
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const routerKeys = ['num_retries', 'timeout', 'allowed_fails', 'cooldown_time', 'routing_strategy', 'fallbacks']
  return (
    <div className="proxy-section">
      <div className="panel-title-row"><h3>Routing, callbacks and cache</h3><button className="ghost" onClick={load}>Refresh</button></div>
      <Notice notice={n.notice} />
      <div className="notice warn">
        Keys pinned in <code>litellm/config.yaml</code> (model list, router settings, OTel callback) are owned by the repository: change the file,
        plan/apply <code>ecs-litellm-proxy</code> (re-uploads it to S3) and force a new deployment. LiteLLM rejects runtime updates to those keys.
        Runtime updates below are for settings <em>not</em> in the file (for example enabling a Langfuse callback or cache parameters).
      </div>
      <h4>Router settings (from the proxy)</h4>
      <div className="kv-grid">
        {routerKeys.map(k => <div key={k}><span>{k}</span>{settings && settings[`router_settings.${k}`] !== undefined ? JSON.stringify(settings[`router_settings.${k}`]) : (settings?.router_settings?.[k] !== undefined ? JSON.stringify(settings.router_settings[k]) : 'see config.yaml')}</div>)}
      </div>
      <h4>Callbacks</h4>
      {Array.isArray(callbacks) && callbacks.length ? callbacks.map(c => <div key={c.name} className="kv-grid" style={{ marginBottom: 8 }}><div><span>{c.name}</span>{Object.entries(c.variables || {}).filter(([, v]) => v).map(([k, v]) => <div key={k}><code>{k}</code>={String(v).slice(0, 60)}</div>)}</div></div>) : <p className="muted">No success/failure callbacks configured on the proxy.</p>}
      <h4>Cache</h4>
      <JsonView value={cache} />
      <p className="muted">Response caching needs a Redis endpoint (ElastiCache) — roadmap Sprint 5. Until then cache settings are informational.</p>
      {canManage && (
        <>
          <h4>Advanced: runtime config update (<code>POST /config/update</code>)</h4>
          <div className="inline-form"><label className="span-2">JSON body<textarea value={update} onChange={(e) => setUpdate(e.target.value)} /></label><button type="button" disabled={busy === 'update'} onClick={apply}>{busy === 'update' ? 'Applying...' : 'Apply to proxy'}</button></div>
        </>
      )}
      <h4>Effective config.yaml</h4>
      <pre className="json-view">{yaml}</pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
function Spend() {
  const [data, setData] = useState(null)
  const n = useNotice()
  const load = async () => {
    try {
      const [models, keys, teams, providers, logs] = await Promise.all([
        litellmAdmin('GET', '/global/spend/models'), litellmAdmin('GET', '/global/spend/keys'), litellmAdmin('GET', '/global/spend/teams'),
        litellmAdmin('GET', '/global/spend/provider'), litellmAdmin('GET', '/spend/logs', undefined, { limit: 25 }),
      ])
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
      <p className="muted">LiteLLM's own spend log across all consumers of the proxy. Use it to reconcile with the FinOps tab (this application's metering). Differences indicate calls from other consumers or unpriced models.</p>
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
          <p className="muted">Configure the model gateway from one place. All actions are authenticated with your Cognito role, forwarded to the proxy's management API by the gateway, and recorded in the policy audit trail.</p>
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
