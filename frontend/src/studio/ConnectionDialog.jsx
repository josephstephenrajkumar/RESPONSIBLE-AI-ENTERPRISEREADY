import { useEffect, useState } from 'react'
import { createStudioConnection, studioOAuthUrl } from '../api'
import { Button, Field, Modal, Notice, useNotice } from '../components/ui'
import { pieceAuthOptions } from './flowModel'

// Creates an app-scoped connection for a piece. Custom auth, secret text and basic auth are
// plain forms; OAuth2 opens the provider in a popup and the portal's /oauth/callback page
// relays the code back, so the engine's UI and URL never appear.
export default function ConnectionDialog({ appId, piece, onClose, onCreated }) {
  const options = pieceAuthOptions(piece)
  const [choice, setChoice] = useState(0)
  const auth = options[choice]
  const [displayName, setDisplayName] = useState(`${piece.displayName} connection`)
  const [props, setProps] = useState({})
  const [secret, setSecret] = useState('')
  const [basic, setBasic] = useState({ username: '', password: '' })
  const [oauth, setOauth] = useState({ client_id: '', client_secret: '', code: '', scope: '', state: '' })
  const [busy, setBusy] = useState(false)
  const n = useNotice()
  const redirectUrl = `${window.location.origin}/oauth/callback`

  useEffect(() => {
    const handler = (event) => {
      if (event.origin !== window.location.origin || event.data?.type !== 'rai-oauth-callback') return
      if (event.data.error) { n.fail(`Authorization failed: ${event.data.error}`); return }
      if (oauth.state && event.data.state && event.data.state !== oauth.state) { n.fail('Authorization state mismatch; try again.'); return }
      setOauth(prev => ({ ...prev, code: event.data.code || '' }))
      n.ok('Authorization received. Save the connection to finish.')
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [oauth.state])

  const authorize = async () => {
    setBusy(true); n.clear()
    try {
      const result = await studioOAuthUrl(appId, { piece_name: piece.name, client_id: oauth.client_id, redirect_url: redirectUrl, scope: oauth.scope })
      setOauth(prev => ({ ...prev, state: result.state, scope: result.scope }))
      window.open(result.authorization_url, 'rai-oauth', 'width=600,height=720')
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }

  const save = async () => {
    setBusy(true); n.clear()
    try {
      const body = { piece_name: piece.name, display_name: displayName, auth_type: auth?.type || 'SECRET_TEXT' }
      if (auth?.type === 'CUSTOM_AUTH') body.props = props
      else if (auth?.type === 'SECRET_TEXT') body.secret_text = secret
      else if (auth?.type === 'BASIC_AUTH') { body.username = basic.username; body.password = basic.password }
      else if (auth?.type === 'OAUTH2') body.oauth2 = { client_id: oauth.client_id, client_secret: oauth.client_secret, code: oauth.code, redirect_url: redirectUrl, scope: oauth.scope }
      const created = await createStudioConnection(appId, body)
      onCreated(created)
    } catch (err) { n.fail(err) } finally { setBusy(false) }
  }

  if (!auth) return <Modal title={`${piece.displayName}: no authentication`} onClose={onClose} footer={<Button variant="ghost" onClick={onClose}>Close</Button>}><p className="muted">This piece needs no connection.</p></Modal>

  return (
    <Modal title={`New ${piece.displayName} connection`} onClose={onClose} width="min(560px, 100%)" footer={<><Button disabled={busy || (auth.type === 'OAUTH2' && !oauth.code)} onClick={save}>{busy ? 'Saving…' : 'Save connection'}</Button><Button variant="ghost" onClick={onClose}>Cancel</Button></>}>
      <Notice notice={n.notice} />
      {options.length > 1 && <Field label="Authentication method"><select value={choice} onChange={(e) => setChoice(Number(e.target.value))}>{options.map((o, i) => <option key={i} value={i}>{o.displayName || o.type}</option>)}</select></Field>}
      {auth.description && <p className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: '0.78rem' }}>{String(auth.description).replace(/<[^>]+>/g, '')}</p>}
      <Field label="Name" required><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></Field>
      {auth.type === 'CUSTOM_AUTH' && Object.entries(auth.props || {}).map(([key, prop]) => (
        <Field key={key} label={prop.displayName || key} required={prop.required} hint={prop.description}>
          {prop.type === 'STATIC_DROPDOWN'
            ? <select value={props[key] ?? ''} onChange={(e) => setProps({ ...props, [key]: e.target.value })}><option value="">Select…</option>{(prop.options?.options || []).map(o => <option key={String(o.value)} value={o.value}>{o.label}</option>)}</select>
            : prop.type === 'CHECKBOX'
              ? <input type="checkbox" checked={Boolean(props[key])} onChange={(e) => setProps({ ...props, [key]: e.target.checked })} />
              : prop.type === 'LONG_TEXT'
                ? <textarea rows={3} value={props[key] ?? ''} onChange={(e) => setProps({ ...props, [key]: e.target.value })} />
                : <input type={prop.type === 'SECRET_TEXT' ? 'password' : 'text'} value={props[key] ?? ''} placeholder={prop.defaultValue ?? ''} onChange={(e) => setProps({ ...props, [key]: e.target.value })} />}
        </Field>
      ))}
      {auth.type === 'SECRET_TEXT' && <Field label={auth.displayName || 'Secret'} required hint={auth.description}><input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} /></Field>}
      {auth.type === 'BASIC_AUTH' && <><Field label={auth.username?.displayName || 'Username'} required><input value={basic.username} onChange={(e) => setBasic({ ...basic, username: e.target.value })} /></Field><Field label={auth.password?.displayName || 'Password'} required><input type="password" value={basic.password} onChange={(e) => setBasic({ ...basic, password: e.target.value })} /></Field></>}
      {auth.type === 'OAUTH2' && (
        <>
          <p className="muted" style={{ fontSize: '0.78rem' }}>Register <code>{redirectUrl}</code> as the redirect URL in the provider's app settings, then enter its client credentials and authorize.</p>
          <Field label="Client id" required><input value={oauth.client_id} onChange={(e) => setOauth({ ...oauth, client_id: e.target.value })} /></Field>
          <Field label="Client secret" required><input type="password" value={oauth.client_secret} onChange={(e) => setOauth({ ...oauth, client_secret: e.target.value })} /></Field>
          <Field label="Scopes" hint="Space separated; defaults to the piece's scopes"><input value={oauth.scope} onChange={(e) => setOauth({ ...oauth, scope: e.target.value })} /></Field>
          <div className="button-row"><Button variant="ghost" disabled={busy || !oauth.client_id} onClick={authorize}>{oauth.code ? 'Authorized ✓ (authorize again)' : 'Authorize with provider'}</Button></div>
        </>
      )}
      {auth.type === 'OIDC' && <p className="muted">OIDC connections are not supported in the Studio yet.</p>}
    </Modal>
  )
}
