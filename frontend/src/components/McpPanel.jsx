import { useEffect, useState } from 'react'
import { fetchMcpInfo, issueMcpKey, revokeMcpKey, updateMcpTool } from '../api'
import { Button, Field, Modal, Notice, Pill, useNotice } from './ui'

// Publishes workflow apps as MCP tools for external agents (Amazon Quick Suite Actions,
// Claude, LiteLLM's MCP gateway, IDE agents). docs/MCP_PUBLISHING.md
export default function McpPanel({ apps, canManage }) {
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState('')
  const [issued, setIssued] = useState(null)
  const [keyName, setKeyName] = useState('')
  const [editing, setEditing] = useState(null) // { app_id, tool_name, description, published }
  const n = useNotice()
  const load = () => fetchMcpInfo().then(setInfo).catch(n.fail)
  useEffect(() => { load() }, [apps.length])

  const toolFor = (app) => (info?.tools || []).find(t => t.app_id === app.id)
  const toggle = async (app) => {
    const current = toolFor(app)
    setBusy(app.id); n.clear()
    try { await updateMcpTool(app.id, { published: !(current?.published) }); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const saveEdit = async () => {
    setBusy('edit'); n.clear()
    try { await updateMcpTool(editing.app_id, { published: editing.published, tool_name: editing.tool_name, description: editing.description }); setEditing(null); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const issue = async () => {
    setBusy('issue'); n.clear()
    try { const r = await issueMcpKey(keyName || 'MCP key'); setIssued(r); setKeyName(''); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const revoke = async (key) => {
    if (!window.confirm(`Revoke key ${key.name}? Clients using it stop working immediately.`)) return
    setBusy(key.key_id); n.clear()
    try { await revokeMcpKey(key.key_id); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const endpoint = info?.endpoint || ''
  const published = (info?.tools || []).filter(t => t.published)

  return (
    <details className="proxy-section">
      <summary style={{ cursor: 'pointer' }}><h3 style={{ display: 'inline', margin: 0 }}>MCP server</h3> <span className="muted" style={{ fontSize: '0.8rem' }}>{published.length} app{published.length === 1 ? '' : 's'} published as tools · {(info?.keys || []).filter(k => !k.revoked).length} active key{(info?.keys || []).filter(k => !k.revoked).length === 1 ? '' : 's'}</span></summary>
      <Notice notice={n.notice} />
      <p className="muted">External agents call published apps as tools over the Model Context Protocol. Each call runs the app's published flow exactly like the Chat tab, so the Responsible AI pipeline, budgets and metering of the app apply.</p>
      <div className="kv-grid">
        <div><span>Endpoint (streamable HTTP)</span><code>{endpoint || '…'}</code></div>
        <div><span>Authentication</span>Bearer MCP key (below), or a Cognito token; OAuth clients discover Cognito at <code>{info?.resource_metadata || '…'}</code></div>
      </div>

      <h4>Apps published as tools</h4>
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>App</th><th>Tool name</th><th>Description</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {apps.map(app => { const t = toolFor(app); return (
            <tr key={app.id}>
              <td><strong>{app.name}</strong><div className="muted" style={{ fontSize: '0.72rem' }}>{app.id}</div></td>
              <td><code>{t?.tool_name || '—'}</code></td>
              <td className="muted" style={{ fontSize: '0.78rem' }}>{t?.description || app.description || ''}</td>
              <td>{t?.published ? (app.status === 'published' ? <Pill tone="ok">visible to clients</Pill> : <Pill tone="warn">enabled, app not published</Pill>) : <Pill tone="neutral">not published</Pill>}</td>
              <td><div className="action-cell">
                {canManage && <Button size="sm" variant={t?.published ? 'ghost' : 'primary'} disabled={busy === app.id} onClick={() => toggle(app)}>{t?.published ? 'Unpublish' : 'Publish as tool'}</Button>}
                {canManage && <Button size="sm" variant="ghost" onClick={() => setEditing({ app_id: app.id, tool_name: t?.tool_name || '', description: t?.description || app.description || '', published: Boolean(t?.published) })}>Edit</Button>}
              </div></td>
            </tr>) })}
          {apps.length === 0 && <tr><td colSpan="5" className="muted">No apps yet.</td></tr>}
        </tbody></table></div>

      <h4>Keys</h4>
      {canManage && <div className="inline-form" style={{ alignItems: 'end' }}>
        <Field label="New key name"><input value={keyName} placeholder="Quick Suite integration" onChange={(e) => setKeyName(e.target.value)} /></Field>
        <div className="button-row"><Button disabled={busy === 'issue'} onClick={issue}>{busy === 'issue' ? 'Issuing…' : 'Issue key'}</Button></div>
      </div>}
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Key</th><th>Name</th><th>Created</th><th>Last used</th><th>State</th><th></th></tr></thead>
        <tbody>
          {(info?.keys || []).map(k => <tr key={k.key_id}><td><code>{k.key_id}</code></td><td>{k.name}</td><td>{k.created_at ? new Date(k.created_at).toLocaleString() : ''}</td><td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}</td><td>{k.revoked ? <Pill tone="neutral">revoked</Pill> : <Pill tone="ok">active</Pill>}</td><td>{canManage && !k.revoked && <Button size="sm" variant="danger" disabled={busy === k.key_id} onClick={() => revoke(k)}>Revoke</Button>}</td></tr>)}
          {info && info.keys.length === 0 && <tr><td colSpan="6" className="muted">No keys issued.</td></tr>}
        </tbody></table></div>

      <h4>Connect a client</h4>
      <div className="mcp-howto">
        <div><strong>Amazon Quick Suite</strong><p className="muted">Integrations → Actions → Model Context Protocol → endpoint <code>{endpoint}</code>, remote transport (streamable HTTP), authentication: bearer key from above. Enterprise subscription required on the Quick side. Each published app appears as an action for Quick chat agents and flows.</p></div>
        <div><strong>Claude Code</strong><pre className="json-view">{`claude mcp add --transport http responsible-ai ${endpoint} --header "Authorization: Bearer <key>"`}</pre></div>
        <div><strong>LiteLLM proxy (Proxy Manager → MCP servers)</strong><p className="muted">URL <code>{endpoint}</code>, transport http, auth type bearer, the key above. Models behind the proxy can then call the apps as tools.</p></div>
        <div><strong>Any MCP client</strong><p className="muted">JSON-RPC over <code>POST {endpoint}</code>: <code>initialize</code>, <code>tools/list</code>, <code>tools/call</code> with <code>{'{ "message": "...", "session_id": "..." }'}</code>. Responses are plain JSON (no server-initiated streams).</p></div>
      </div>

      {issued && <Modal title="MCP key issued" onClose={() => setIssued(null)} footer={<Button onClick={() => setIssued(null)}>Done</Button>}>
        <p>Copy it now; it is shown once and stored only as a hash.</p>
        <div className="secret-once">{issued.key}</div>
        <p className="muted" style={{ fontSize: '0.78rem' }}>Key id <code>{issued.key_id}</code> · {issued.name}. Paste it into the client as a bearer token. Never commit it to a repository.</p>
      </Modal>}
      {editing && <Modal title="MCP tool settings" onClose={() => setEditing(null)} footer={<><Button disabled={busy === 'edit'} onClick={saveEdit}>Save</Button><Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button></>}>
        <Field label="Tool name" hint="Lowercase letters, digits and underscores; what the agent sees."><input value={editing.tool_name} onChange={(e) => setEditing({ ...editing, tool_name: e.target.value })} /></Field>
        <Field label="Description" hint="Tell the agent when to use this tool."><textarea rows={3} value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} /></Field>
        <label className="toggle"><input type="checkbox" checked={editing.published} onChange={(e) => setEditing({ ...editing, published: e.target.checked })} /> Published to MCP clients</label>
      </Modal>}
    </details>
  )
}
