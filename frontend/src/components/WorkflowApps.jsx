import { useEffect, useState } from 'react'
import {
  bootstrapWorkflows, createWorkflowApp, deleteWorkflowApp, fetchGatewayModels, fetchStudioCatalogue, fetchStudioPieces,
  fetchWorkflowApps, fetchWorkflowStatus, publishWorkflowApp, setWorkflowAppStatus, syncWorkflowUsage, updateStudioCatalogue,
} from '../api'
import { StatusDot, formatUsd } from './charts'
import { Button, EmptyRow, Field, Modal, Notice, Pill, useNotice } from './ui'
import WorkflowStudio from '../studio/WorkflowStudio'

// Workflow Apps: build and publish workflow apps from inside the portal. The gateway owns the
// engine (service account, credentials, app registry); the Workflow Studio is our own builder
// over the engine API, so the engine's UI, origin and login never appear to users.
// docs/ACTIVEPIECES_INTEGRATION.md · docs/WORKFLOW_STUDIO_PLAN.md

const STATUS_TONE = { draft: 'draft', published: 'ok', disabled: 'neutral' }

function EngineStatus({ status, onBootstrap, onCatalogue, busy, canManage }) {
  if (!status) return <p className="muted">Loading engine status...</p>
  const pieceRows = Object.entries(status.pieces || {})
  const okDot = status.engine_reachable ? (status.bootstrapped_at ? 'ok' : 'warn') : 'error'
  const providers = status.engine_ai_providers || []
  return (
    <details className="proxy-section">
      <summary className="panel-title-row" style={{ cursor: 'pointer' }}>
        <h3 style={{ margin: 0 }}>Workflow engine <StatusDot status={okDot} /> <span className="muted" style={{ fontWeight: 400, fontSize: '0.8rem' }}>{status.engine_reachable ? 'reachable' : 'unreachable'} · {status.bootstrapped_at ? `bootstrapped ${new Date(status.bootstrapped_at).toLocaleString()}` : 'not bootstrapped'}</span></h3>
      </summary>
      {canManage && <div className="button-row" style={{ margin: '8px 0' }}>
        <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => onBootstrap(false)}>{busy === 'bootstrap' ? 'Bootstrapping...' : 'Bootstrap engine'}</Button>
        <Button variant="ghost" size="sm" onClick={onCatalogue}>Studio catalogue</Button>
      </div>}
      <div className="kv-grid">
        <div><span>Engine (internal)</span><code>{status.api_url}</code></div>
        <div><span>Service account</span>{status.service_configured ? status.service_email : 'not configured (ACTIVEPIECES_SERVICE_PASSWORD)'}</div>
        <div><span>Signed in</span>{status.signed_in ? 'yes' : 'no'}</div>
        <div><span>AI provider</span>{status.ai_provider_id ? `${status.ai_provider_name} (${status.ai_provider_id})` : 'not configured'}{providers.length > 1 && <span className="warning-text"> · {providers.length} providers on the engine</span>}</div>
        <div><span>Engine → gateway / proxy</span><code>{status.gateway_url_for_engine}</code><br /><code>{status.litellm_url_for_engine}</code></div>
      </div>
      {pieceRows.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="policy-table finops-table"><thead><tr><th>Piece</th><th>Version</th><th>State</th></tr></thead>
            <tbody>{pieceRows.map(([name, info]) => <tr key={name}><td><code>{name}</code></td><td>{info?.version || '—'}</td><td><Pill tone={info?.state === 'failed' || info?.state === 'missing' ? 'danger' : 'ok'}>{info?.state || '—'}</Pill>{info?.error && <div className="muted" style={{ fontSize: '0.72rem' }}>{info.error}</div>}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      {status.last_bootstrap?.errors?.length > 0 && <div className="notice warn">{status.last_bootstrap.errors.join(' · ')}</div>}
      {status.last_bootstrap?.note && <p className="muted" style={{ fontSize: '0.78rem' }}>{status.last_bootstrap.note}</p>}
      <p className="muted" style={{ fontSize: '0.78rem' }}>{status.edition_notes}</p>
    </details>
  )
}

function CatalogueDialog({ onClose }) {
  const [all, setAll] = useState([])
  const [chosen, setChosen] = useState(null)
  const [defaults, setDefaults] = useState([])
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const n = useNotice()
  useEffect(() => {
    Promise.all([fetchStudioPieces('', true), fetchStudioCatalogue()]).then(([pieces, cat]) => { setAll(pieces.pieces || []); setChosen(new Set(cat.pieces || [])); setDefaults(cat.default || []) }).catch(n.fail)
  }, [])
  const save = async () => {
    setBusy(true); n.clear()
    try {
      // Keep the configured order for pieces already in the catalogue, append new picks alphabetically.
      const ordered = [...defaults.filter(p => chosen.has(p)), ...all.map(p => p.name).filter(name => chosen.has(name) && !defaults.includes(name)).sort()]
      await updateStudioCatalogue(ordered); n.ok('Catalogue saved. Builders see these pieces in the step picker.')
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }
  const visible = all.filter(p => !filter || (p.displayName || '').toLowerCase().includes(filter.toLowerCase()) || (p.name || '').toLowerCase().includes(filter.toLowerCase()))
  return (
    <Modal title="Studio catalogue" onClose={onClose} width="min(900px, 100%)" footer={<><Button disabled={busy || !chosen} onClick={save}>{busy ? 'Saving…' : 'Save catalogue'}</Button><Button variant="ghost" onClick={() => setChosen(new Set(defaults))}>Reset to default</Button><Button variant="ghost" onClick={onClose}>Close</Button></>}>
      <p className="muted" style={{ marginTop: 0 }}>Pieces builders may add to a workflow. AI steps should use the Responsible AI Gateway or LiteLLM Proxy pieces so inference stays governed and metered; other pieces call their APIs directly.</p>
      <Notice notice={n.notice} />
      <input className="studio-search" placeholder="Filter pieces…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="muted" style={{ fontSize: '0.75rem', marginBottom: 6 }}>{chosen ? `${chosen.size} of ${all.length} pieces enabled` : 'Loading…'}</div>
      <div className="catalogue-list">
        {chosen && visible.map(p => (
          <label key={p.name}><input type="checkbox" checked={chosen.has(p.name)} onChange={(e) => { const next = new Set(chosen); e.target.checked ? next.add(p.name) : next.delete(p.name); setChosen(next) }} />{p.logoUrl && <img src={p.logoUrl} alt="" />}<span>{p.displayName}<br /><code style={{ fontSize: '0.68rem' }}>{p.name}</code></span></label>
        ))}
      </div>
    </Modal>
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
      const created = await createWorkflowApp({ ...form, monthly_budget_usd: form.monthly_budget_usd === '' ? 0 : Number(form.monthly_budget_usd) })
      setForm(prev => ({ ...prev, name: '', description: '' }))
      onCreated(created)
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }
  if (!canManage) return null
  return (
    <details className="proxy-section">
      <summary style={{ cursor: 'pointer' }}><h3 style={{ display: 'inline', margin: 0 }}>New workflow app</h3> <span className="muted" style={{ fontSize: '0.8rem' }}>pick a template, then open it in the Studio</span></summary>
      <Notice notice={n.notice} />
      <div className="template-gallery">
        {templates.map(t => (
          <button type="button" key={t.id} className={`template-card ${form.template === t.id ? 'active' : ''}`} onClick={() => set('template', t.id)}>
            <strong>{t.label}</strong><span className="muted">{t.description}</span>
          </button>
        ))}
      </div>
      <div className="inline-form">
        <Field label="Name" required><input value={form.name} placeholder="Customer support assistant" onChange={(e) => set('name', e.target.value)} /></Field>
        <Field label="Responsible AI mode"><select value={form.rai_mode} onChange={(e) => set('rai_mode', e.target.value)}><option value="framework">framework</option><option value="code">code</option></select></Field>
        <Field label="Model"><select value={form.model} onChange={(e) => set('model', e.target.value)}><option value="">gateway default</option>{models.map(m => <option key={m} value={m}>{m}</option>)}</select></Field>
        <Field label="Monthly budget (USD)" hint="0 = platform default"><input type="number" step="0.5" min="0" value={form.monthly_budget_usd} placeholder="default" onChange={(e) => set('monthly_budget_usd', e.target.value)} /></Field>
        <Field label="Bot name"><input value={form.bot_name} onChange={(e) => set('bot_name', e.target.value)} /></Field>
        <Field label="Description" span><input value={form.description} placeholder="What this app does" onChange={(e) => set('description', e.target.value)} /></Field>
      </div>
      <div className="button-row"><Button disabled={busy || !form.name.trim()} onClick={submit}>{busy ? 'Creating...' : 'Create and open in Studio'}</Button></div>
    </details>
  )
}

export default function WorkflowApps({ canManage }) {
  const [status, setStatus] = useState(null)
  const [apps, setApps] = useState([])
  const [models, setModels] = useState([])
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState(null) // app open in the Studio
  const [catalogue, setCatalogue] = useState(false)
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
  const bootstrap = (force) => run('bootstrap', () => bootstrapWorkflows(force), 'Bootstrap finished. Check the piece and AI provider states.')
  const publish = (app) => run(`publish:${app.id}`, () => publishWorkflowApp(app.id), `${app.name} published.`)
  const toggle = (app) => run(`status:${app.id}`, () => setWorkflowAppStatus(app.id, app.status !== 'published'))
  const remove = (app) => { if (!window.confirm(`Delete ${app.name}? The flow, its connections and its LiteLLM key are removed.`)) return; run(`delete:${app.id}`, () => deleteWorkflowApp(app.id), `${app.name} deleted.`); if (open?.id === app.id) setOpen(null) }
  const sync = () => run('sync', () => syncWorkflowUsage(), 'Workflow spend synchronised into FinOps.')

  if (open) {
    const current = apps.find(a => a.id === open.id) || open
    return <WorkflowStudio app={current} canManage={canManage} onClose={() => { setOpen(null); load() }} onAppChanged={load} />
  }

  return (
    <section className="panel">
      <div className="panel-title-row">
        <div>
          <h2>Workflow Apps</h2>
          <p className="muted">Build, test and publish workflow apps in the Workflow Studio. Each app gets its own LiteLLM virtual key (budgeted, metered) and a gateway token for governed chat. AI steps go through the LiteLLM proxy; other API calls run directly.</p>
        </div>
        {!canManage && <Pill tone="neutral">read-only</Pill>}
      </div>
      <Notice notice={n.notice} />
      <EngineStatus status={status} onBootstrap={bootstrap} onCatalogue={() => setCatalogue(true)} busy={busy} canManage={canManage} />
      <CreateForm status={status} models={models} canManage={canManage} onCreated={(created) => { load(); setOpen(created) }} />
      <div className="proxy-section">
        <div className="panel-title-row"><h3>Apps</h3><div className="button-row"><Button variant="ghost" size="sm" disabled={busy === 'sync'} onClick={sync}>{busy === 'sync' ? 'Syncing...' : 'Sync spend to FinOps'}</Button><Button variant="ghost" size="sm" onClick={load}>Refresh</Button></div></div>
        <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>App</th><th>Template</th><th>Status</th><th>Model</th><th>Budget</th><th>Attribution</th><th></th></tr></thead>
          <tbody>{apps.map(app => (
            <tr key={app.id}>
              <td><button type="button" className="link-btn" style={{ fontSize: '0.9rem', fontWeight: 700 }} onClick={() => setOpen(app)}>{app.name}</button><div className="muted" style={{ fontSize: '0.72rem' }}>{app.id} · {app.owner_email || app.owner_user_id}</div></td>
              <td>{app.template_label}<div className="muted" style={{ fontSize: '0.72rem' }}>RAI {app.rai_mode}</div></td>
              <td><Pill tone={STATUS_TONE[app.status] || 'neutral'}>{app.status}</Pill></td>
              <td><code>{app.model || 'default'}</code></td>
              <td>{formatUsd(app.monthly_budget_usd)} / 30d</td>
              <td><code>{app.client_id}</code></td>
              <td><div className="action-cell">
                <Button variant="ghost" size="sm" onClick={() => setOpen(app)}>Open Studio</Button>
                {canManage && <Button size="sm" disabled={busy === `publish:${app.id}`} onClick={() => publish(app)}>{busy === `publish:${app.id}` ? 'Publishing...' : (app.published_at ? 'Republish' : 'Publish')}</Button>}
                {canManage && app.published_at && <Button variant="ghost" size="sm" disabled={busy === `status:${app.id}`} onClick={() => toggle(app)}>{app.status === 'published' ? 'Disable' : 'Enable'}</Button>}
                {canManage && <Button variant="danger" size="sm" disabled={busy === `delete:${app.id}`} onClick={() => remove(app)}>Delete</Button>}
              </div></td>
            </tr>))}
            {apps.length === 0 && <EmptyRow colSpan={7}>No workflow apps yet. Create one above; the Responsible AI chat template reproduces the Chat tab as a workflow you can extend in the Studio.</EmptyRow>}</tbody></table></div>
      </div>
      {catalogue && <CatalogueDialog onClose={() => setCatalogue(false)} />}
    </section>
  )
}
