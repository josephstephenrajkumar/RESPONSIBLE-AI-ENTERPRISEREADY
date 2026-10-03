import { useEffect, useState } from 'react'
import {
  bootstrapWorkflows, chatWithWorkflowApp, createWorkflowApp, deleteWorkflowApp, fetchGatewayModels,
  fetchWorkflowAppRuns, fetchWorkflowApps, fetchWorkflowStatus, publishWorkflowApp, setWorkflowAppStatus, syncWorkflowUsage
} from '../api'
import { StatusDot, formatUsd } from './charts'

// Workflow Apps: build and publish workflow apps on the Activepieces engine from
// inside the gateway. The gateway owns credentials and the app registry; the
// engine's builder and chat UI are embedded from an allow-listed origin.
// docs/ACTIVEPIECES_INTEGRATION.md

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

const STATUS_PILL = { draft: 'status-draft', published: 'enabled', disabled: 'disabled' }

function EngineStatus({ status, onBootstrap, busy }) {
  if (!status) return <p className="muted">Loading engine status...</p>
  const pieces = status.pieces || {}
  const pieceRows = Object.entries(pieces)
  const okDot = status.engine_reachable ? (status.bootstrapped_at ? 'ok' : 'warn') : 'error'
  return (
    <div className="proxy-section">
      <div className="panel-title-row">
        <h3>Workflow engine <StatusDot status={okDot} /></h3>
        <div className="button-row">
          <button type="button" className="ghost" disabled={busy} onClick={() => onBootstrap(false)}>{busy === 'bootstrap' ? 'Bootstrapping...' : 'Bootstrap engine'}</button>
          <a className="tracing-badge enabled" href={status.public_url} target="_blank" rel="noreferrer">Open Activepieces ↗</a>
        </div>
      </div>
      <div className="kv-grid">
        <div><span>Engine</span><code>{status.public_url}</code></div>
        <div><span>Reachable</span>{status.engine_reachable ? 'yes' : 'no'} · signed in {status.signed_in ? 'yes' : 'no'}</div>
        <div><span>Service account</span>{status.service_configured ? status.service_email : 'not configured (ACTIVEPIECES_SERVICE_PASSWORD)'}</div>
        <div><span>Bootstrapped</span>{status.bootstrapped_at ? new Date(status.bootstrapped_at).toLocaleString() : 'never'}</div>
        <div><span>AI provider</span>{status.ai_provider_id ? `${status.ai_provider_name} (${status.ai_provider_id})` : 'not configured'}</div>
        <div><span>Engine → gateway / proxy</span><code>{status.gateway_url_for_engine}</code><br /><code>{status.litellm_url_for_engine}</code></div>
      </div>
      {pieceRows.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="policy-table finops-table"><thead><tr><th>Piece</th><th>Version</th><th>State</th></tr></thead>
            <tbody>{pieceRows.map(([name, info]) => <tr key={name}><td><code>{name}</code></td><td>{info?.version || '—'}</td><td><span className={`pill ${info?.state === 'failed' || info?.state === 'missing' ? 'disabled' : 'enabled'}`}>{info?.state || '—'}</span>{info?.error && <div className="muted" style={{ fontSize: '0.72rem' }}>{info.error}</div>}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      {status.last_bootstrap?.errors?.length > 0 && <div className="notice warn">{status.last_bootstrap.errors.join(' · ')}</div>}
      <p className="muted" style={{ fontSize: '0.78rem' }}>{status.edition_notes}</p>
    </div>
  )
}

function CreateForm({ status, models, onCreated, canManage }) {
  const n = useNotice()
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', template: 'responsible-ai-chat', rai_mode: 'framework', model: '', monthly_budget_usd: '', bot_name: 'Responsible AI Bot' })
  const templates = status?.templates || []
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }))
  const submit = async () => {
    setBusy(true); n.clear()
    try {
      const payload = { ...form, monthly_budget_usd: form.monthly_budget_usd === '' ? 0 : Number(form.monthly_budget_usd) }
      const created = await createWorkflowApp(payload)
      n.ok(`Created ${created.name} (${created.id}). Open the builder to review the flow, then publish.`)
      setForm(prev => ({ ...prev, name: '', description: '' }))
      onCreated(created)
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }
  if (!canManage) return null
  const selected = templates.find(t => t.id === form.template)
  return (
    <div className="proxy-section">
      <h3>New workflow app</h3>
      <Notice notice={n.notice} />
      <div className="inline-form">
        <label>Name<input value={form.name} placeholder="Customer support assistant" onChange={(e) => set('name', e.target.value)} /></label>
        <label>Template<select value={form.template} onChange={(e) => set('template', e.target.value)}>{templates.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}</select></label>
        <label>Responsible AI mode<select value={form.rai_mode} onChange={(e) => set('rai_mode', e.target.value)}><option value="framework">framework</option><option value="code">code</option></select></label>
        <label>Model<select value={form.model} onChange={(e) => set('model', e.target.value)}><option value="">gateway default</option>{models.map(m => <option key={m} value={m}>{m}</option>)}</select></label>
        <label>Monthly budget (USD)<input type="number" step="0.5" min="0" value={form.monthly_budget_usd} placeholder="default" onChange={(e) => set('monthly_budget_usd', e.target.value)} /></label>
        <label>Bot name<input value={form.bot_name} onChange={(e) => set('bot_name', e.target.value)} /></label>
        <label className="span-2">Description<input value={form.description} placeholder="What this app does" onChange={(e) => set('description', e.target.value)} /></label>
      </div>
      {selected && <p className="muted" style={{ marginTop: 0 }}>{selected.description}</p>}
      <div className="button-row"><button type="button" disabled={busy || !form.name.trim()} onClick={submit}>{busy ? 'Creating...' : 'Create app'}</button></div>
    </div>
  )
}

function TestChat({ app }) {
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState([])
  const [busy, setBusy] = useState(false)
  const [sessionId] = useState(() => `test-${app.id}-${Date.now()}`)
  const n = useNotice()
  const send = async () => {
    if (!message.trim()) return
    const text = message; setMessage(''); setBusy(true); n.clear()
    setTurns(prev => [...prev, { role: 'user', text }])
    try {
      const result = await chatWithWorkflowApp(app.id, text, sessionId)
      setTurns(prev => [...prev, { role: 'assistant', text: result.answer || JSON.stringify(result.raw), latency: result.latency_ms }])
    } catch (err) { n.fail(err); setTurns(prev => [...prev, { role: 'assistant', text: `Failed: ${err.message}`, error: true }]) } finally { setBusy(false) }
  }
  return (
    <div className="mini-chat">
      <p className="muted" style={{ marginTop: 0 }}>Sends a turn to the published flow through the gateway (<code>POST /workflows/apps/{app.id}/chat</code>), so the round trip is exercised under your Cognito session rather than the public chat page.</p>
      <Notice notice={n.notice} />
      <div className="mini-chat-log">
        {turns.length === 0 && <div className="muted">No turns yet.</div>}
        {turns.map((t, i) => <div key={i} className={`bubble ${t.role}${t.error ? ' error' : ''}`}><div className="bubble-role">{t.role}</div><div style={{ whiteSpace: 'pre-wrap' }}>{t.text}</div>{t.latency != null && <div className="usage-footer">{t.latency} ms round trip</div>}</div>)}
      </div>
      <div className="composer"><input value={message} placeholder="Ask the workflow app..." disabled={busy} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send() }} /><button type="button" disabled={busy || !message.trim()} onClick={send}>{busy ? '...' : 'Send'}</button></div>
    </div>
  )
}

function AppPanels({ app, view, onClose }) {
  const [runs, setRuns] = useState(null)
  const n = useNotice()
  useEffect(() => {
    if (view === 'runs') fetchWorkflowAppRuns(app.id).then(r => setRuns(r.runs || [])).catch(n.fail)
  }, [app.id, view])
  const frameUrl = view === 'builder' ? app.builder_url : app.chat_url
  return (
    <div className="proxy-section workflow-panel">
      <div className="panel-title-row">
        <h3>{app.name} · {view === 'builder' ? 'builder' : view === 'chat' ? 'chat' : view === 'test' ? 'test through gateway' : 'runs'}</h3>
        <div className="button-row">
          {(view === 'builder' || view === 'chat') && <a className="tracing-badge enabled" href={frameUrl} target="_blank" rel="noreferrer">Open in new tab ↗</a>}
          <button type="button" className="ghost" onClick={onClose}>Close</button>
        </div>
      </div>
      <Notice notice={n.notice} />
      {view === 'builder' && <p className="muted" style={{ marginTop: 0 }}>Community edition: the builder asks for the Activepieces login of the workflow service account (platform admin). Flows live in that account's project. Enterprise embedding removes this step.</p>}
      {(view === 'builder' || view === 'chat') && <iframe title={`${app.name} ${view}`} src={frameUrl} className={`workflow-frame ${view === 'chat' ? 'workflow-chat-frame' : ''}`} allow="clipboard-read; clipboard-write" />}
      {view === 'test' && <TestChat app={app} />}
      {view === 'runs' && (
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Duration</th><th>Env</th></tr></thead>
          <tbody>{(runs || []).map(r => <tr key={r.id}><td><code>{r.id}</code></td><td><span className={`pill ${r.status === 'SUCCEEDED' ? 'enabled' : (r.status === 'RUNNING' || r.status === 'QUEUED') ? 'status-review' : 'severity-high'}`}>{r.status}</span></td><td>{r.created ? new Date(r.created).toLocaleString() : '—'}</td><td>{r.duration_ms != null ? `${r.duration_ms} ms` : '—'}</td><td>{r.environment || '—'}</td></tr>)}
            {runs && runs.length === 0 && <tr><td colSpan="5" className="muted">No runs yet.</td></tr>}
            {!runs && <tr><td colSpan="5" className="muted">Loading runs...</td></tr>}</tbody></table></div>
      )}
    </div>
  )
}

export default function WorkflowApps({ canManage }) {
  const [status, setStatus] = useState(null)
  const [apps, setApps] = useState([])
  const [models, setModels] = useState([])
  const [busy, setBusy] = useState('')
  const [selected, setSelected] = useState(null) // { app, view }
  const n = useNotice()

  const load = async () => {
    try {
      const [s, a] = await Promise.all([fetchWorkflowStatus(), fetchWorkflowApps()])
      setStatus(s); setApps(a.apps || [])
    } catch (err) { n.fail(err) }
  }
  useEffect(() => {
    load()
    fetchGatewayModels().then(data => {
      const list = (data?.models || []).map(m => (typeof m === 'string' ? m : (m.model_name || m.name || m.id))).filter(Boolean)
      setModels([...new Set(list)])
    }).catch(() => setModels([]))
  }, [])

  const run = async (label, fn, okText) => {
    setBusy(label); n.clear()
    try { const r = await fn(); if (okText) n.ok(okText); await load(); return r } catch (err) { n.fail(err); return null } finally { setBusy('') }
  }
  const bootstrap = (force) => run('bootstrap', () => bootstrapWorkflows(force), 'Bootstrap finished. Check the piece and AI provider states below.')
  const publish = (app) => run(`publish:${app.id}`, () => publishWorkflowApp(app.id), `${app.name} published. The chat page and the gateway test are live.`)
  const toggle = (app) => run(`status:${app.id}`, () => setWorkflowAppStatus(app.id, app.status !== 'published'))
  const remove = (app) => { if (!window.confirm(`Delete ${app.name}? The flow, its connections and its LiteLLM key are removed.`)) return; run(`delete:${app.id}`, () => deleteWorkflowApp(app.id), `${app.name} deleted.`); if (selected?.app.id === app.id) setSelected(null) }
  const sync = () => run('sync', () => syncWorkflowUsage(), 'Workflow spend synchronised into FinOps.')

  return (
    <section className="panel">
      <div className="panel-title-row">
        <div>
          <h2>Workflow Apps</h2>
          <p className="muted">Build and publish workflow apps on the Activepieces engine. Each app gets its own LiteLLM virtual key (budgeted, metered) and a gateway token for governed chat. AI steps go through the LiteLLM proxy; other API calls run directly.</p>
        </div>
        {!canManage && <span className="pill disabled">read-only</span>}
      </div>
      <Notice notice={n.notice} />
      <EngineStatus status={status} onBootstrap={bootstrap} busy={busy} />
      <CreateForm status={status} models={models} canManage={canManage} onCreated={(created) => { load(); setSelected({ app: created, view: 'builder' }) }} />
      <div className="proxy-section">
        <div className="panel-title-row"><h3>Apps</h3><div className="button-row"><button type="button" className="ghost" disabled={busy === 'sync'} onClick={sync}>{busy === 'sync' ? 'Syncing...' : 'Sync spend to FinOps'}</button><button type="button" className="ghost" onClick={load}>Refresh</button></div></div>
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>App</th><th>Template</th><th>Status</th><th>Model</th><th>Budget</th><th>Attribution</th><th></th></tr></thead>
          <tbody>{apps.map(app => (
            <tr key={app.id}>
              <td><strong>{app.name}</strong><div className="muted" style={{ fontSize: '0.72rem' }}>{app.id} · {app.owner_email || app.owner_user_id}</div></td>
              <td>{app.template_label}<div className="muted" style={{ fontSize: '0.72rem' }}>RAI {app.rai_mode}</div></td>
              <td><span className={`pill ${STATUS_PILL[app.status] || 'disabled'}`}>{app.status}</span></td>
              <td><code>{app.model || 'default'}</code></td>
              <td>{formatUsd(app.monthly_budget_usd)} / 30d</td>
              <td><code>{app.client_id}</code></td>
              <td><div className="action-cell">
                <button type="button" className="ghost" onClick={() => setSelected({ app, view: 'builder' })}>Builder</button>
                <button type="button" className="ghost" disabled={app.status !== 'published'} onClick={() => setSelected({ app, view: 'chat' })}>Chat</button>
                <button type="button" className="ghost" disabled={app.status !== 'published'} onClick={() => setSelected({ app, view: 'test' })}>Test</button>
                <button type="button" className="ghost" onClick={() => setSelected({ app, view: 'runs' })}>Runs</button>
                {canManage && <button type="button" disabled={busy === `publish:${app.id}`} onClick={() => publish(app)}>{busy === `publish:${app.id}` ? 'Publishing...' : (app.published_at ? 'Republish' : 'Publish')}</button>}
                {canManage && app.published_at && <button type="button" className="ghost" disabled={busy === `status:${app.id}`} onClick={() => toggle(app)}>{app.status === 'published' ? 'Disable' : 'Enable'}</button>}
                {canManage && <button type="button" className="danger" disabled={busy === `delete:${app.id}`} onClick={() => remove(app)}>Delete</button>}
              </div></td>
            </tr>))}
            {apps.length === 0 && <tr><td colSpan="7" className="muted">No workflow apps yet. Create one above; the Responsible AI chat template reproduces the Chat tab as a workflow.</td></tr>}</tbody></table></div>
      </div>
      {selected && <AppPanels app={apps.find(a => a.id === selected.app.id) || selected.app} view={selected.view} onClose={() => setSelected(null)} />}
    </section>
  )
}
