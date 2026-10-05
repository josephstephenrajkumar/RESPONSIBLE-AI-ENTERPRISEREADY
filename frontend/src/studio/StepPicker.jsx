import { useEffect, useState } from 'react'
import { fetchStudioPiece, fetchStudioPieces } from '../api'
import { Button, Modal, Notice, Pill, useNotice } from '../components/ui'
import { aiGovernanceNote } from './flowModel'

// Picks what to add: a piece action (or trigger), a Code step, a Router or a Loop.
export default function StepPicker({ mode = 'action', onClose, onPick }) {
  const [pieces, setPieces] = useState([])
  const [search, setSearch] = useState('')
  const [piece, setPiece] = useState(null)
  const [meta, setMeta] = useState(null)
  const [busy, setBusy] = useState(false)
  const n = useNotice()

  useEffect(() => { fetchStudioPieces(search).then(r => setPieces(r.pieces || [])).catch(n.fail) }, [search])
  const open = async (p) => {
    setPiece(p); setBusy(true)
    try { setMeta(await fetchStudioPiece(p.name)) } catch (err) { n.fail(err) } finally { setBusy(false) }
  }
  const items = mode === 'trigger' ? Object.entries(meta?.triggers || {}) : Object.entries(meta?.actions || {})
  const visible = mode === 'trigger' ? pieces.filter(p => (p.triggers || 0) > 0) : pieces.filter(p => (p.actions || 0) > 0)

  return (
    <Modal title={mode === 'trigger' ? 'Choose a trigger' : 'Add a step'} onClose={onClose} width="min(820px, 100%)" footer={<Button variant="ghost" onClick={onClose}>Cancel</Button>}>
      <Notice notice={n.notice} />
      {mode !== 'trigger' && !piece && (
        <div className="button-row" style={{ marginBottom: 12 }}>
          <Button variant="ghost" onClick={() => onPick({ kind: 'code' })}>Code (TypeScript)</Button>
          <Button variant="ghost" onClick={() => onPick({ kind: 'router' })}>Router (branches)</Button>
          <Button variant="ghost" onClick={() => onPick({ kind: 'loop' })}>Loop on items</Button>
        </div>
      )}
      {!piece ? (
        <>
          <input className="studio-search" placeholder="Search pieces…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="piece-grid">
            {visible.map(p => (
              <button type="button" key={p.name} className="piece-card" onClick={() => open(p)}>
                {p.logoUrl && <img src={p.logoUrl} alt="" />}
                <div><strong>{p.displayName}</strong><div className="muted" style={{ fontSize: '0.72rem' }}>{mode === 'trigger' ? `${p.triggers} triggers` : `${p.actions} actions`}{aiGovernanceNote(p) && <> · <span title={aiGovernanceNote(p).hint}><Pill tone={aiGovernanceNote(p).tone}>{aiGovernanceNote(p).label}</Pill></span></>}</div></div>
              </button>
            ))}
            {visible.length === 0 && <p className="muted">No pieces match.</p>}
          </div>
        </>
      ) : (
        <>
          <div className="panel-title-row"><h3 style={{ margin: 0 }}>{piece.displayName}</h3><Button variant="ghost" size="sm" onClick={() => { setPiece(null); setMeta(null) }}>← All pieces</Button></div>
          {busy && <p className="muted">Loading…</p>}
          <div className="action-list">
            {items.map(([name, item]) => (
              <button type="button" key={name} className="action-card" onClick={() => onPick({ kind: mode === 'trigger' ? 'trigger' : 'piece', piece: meta, name, item })}>
                <strong>{item.displayName || name}</strong>
                <span className="muted">{item.description}</span>
              </button>
            ))}
            {!busy && items.length === 0 && <p className="muted">Nothing to pick here.</p>}
          </div>
        </>
      )}
    </Modal>
  )
}
