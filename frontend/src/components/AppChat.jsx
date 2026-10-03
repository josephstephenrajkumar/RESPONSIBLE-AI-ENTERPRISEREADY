import { useState } from 'react'
import { chatWithWorkflowApp } from '../api'
import { Notice, useNotice } from './ui'

// The portal's own chat window for a published workflow app. Every turn goes through the
// gateway (POST /workflows/apps/{id}/chat); the engine's public chat page is never used.
export default function AppChat({ app, compact = false }) {
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState([])
  const [busy, setBusy] = useState(false)
  const [sessionId] = useState(() => `portal-${app.id}-${Date.now()}`)
  const n = useNotice()
  const send = async () => {
    if (!message.trim() || busy) return
    const text = message; setMessage(''); setBusy(true); n.clear()
    setTurns(prev => [...prev, { role: 'user', text }])
    try {
      const result = await chatWithWorkflowApp(app.id, text, sessionId)
      setTurns(prev => [...prev, { role: 'assistant', text: result.answer || JSON.stringify(result.raw), latency: result.latency_ms }])
    } catch (err) { n.fail(err); setTurns(prev => [...prev, { role: 'assistant', text: `Failed: ${err.message}`, error: true }]) } finally { setBusy(false) }
  }
  if (app.status !== 'published') return <p className="muted">Publish the app to chat with it.</p>
  return (
    <div className={`mini-chat ${compact ? 'compact' : ''}`}>
      <Notice notice={n.notice} />
      <div className="mini-chat-log">
        {turns.length === 0 && <div className="muted">Ask the app something. Replies include the gateway footer with model, tokens and request id.</div>}
        {turns.map((t, i) => <div key={i} className={`bubble ${t.role}${t.error ? ' error' : ''}`}><div className="bubble-role">{t.role === 'user' ? 'You' : app.name}</div><div style={{ whiteSpace: 'pre-wrap' }}>{t.text}</div>{t.latency != null && <div className="usage-footer">{t.latency} ms round trip</div>}</div>)}
      </div>
      <div className="composer"><input value={message} placeholder="Type a message…" disabled={busy} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send() }} /><button type="button" disabled={busy || !message.trim()} onClick={send}>{busy ? '…' : 'Send'}</button></div>
    </div>
  )
}
