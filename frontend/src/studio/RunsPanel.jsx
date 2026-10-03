import { useEffect, useState } from 'react'
import { fetchStudioRun, fetchWorkflowAppRuns, retryStudioRun } from '../api'
import { Button, JsonView, Notice, Pill, useNotice } from '../components/ui'

const TONE = { SUCCEEDED: 'ok', FAILED: 'danger', RUNNING: 'info', QUEUED: 'info', PAUSED: 'warn', TIMEOUT: 'danger', INTERNAL_ERROR: 'danger' }

export default function RunsPanel({ app }) {
  const [runs, setRuns] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  const load = () => fetchWorkflowAppRuns(app.id, 30).then(r => setRuns(r.runs || [])).catch(n.fail)
  useEffect(() => { load() }, [app.id])
  const open = async (run) => {
    setSelected(run.id); setDetail(null)
    try { setDetail(await fetchStudioRun(app.id, run.id)) } catch (err) { n.fail(err) }
  }
  const retry = async (strategy) => {
    setBusy(strategy); n.clear()
    try { const r = await retryStudioRun(app.id, selected, strategy); n.ok(`Re-run queued (${r.id}).`); await load() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  return (
    <div className="runs-panel">
      <Notice notice={n.notice} />
      <div className="runs-layout">
        <div>
          <div className="panel-title-row"><h4 style={{ margin: 0 }}>Runs</h4><Button variant="ghost" size="sm" onClick={load}>Refresh</Button></div>
          <div className="runs-list">
            {(runs || []).map(r => (
              <button type="button" key={r.id} className={`run-row ${selected === r.id ? 'active' : ''}`} onClick={() => open(r)}>
                <Pill tone={TONE[r.status] || 'neutral'}>{r.status}</Pill>
                <span className="muted">{r.created ? new Date(r.created).toLocaleString() : ''}</span>
                <span className="muted">{r.duration_ms != null ? `${r.duration_ms} ms` : ''}</span>
              </button>
            ))}
            {runs && runs.length === 0 && <p className="muted">No runs yet. Publish the app and send it a message.</p>}
            {!runs && <p className="muted">Loading…</p>}
          </div>
        </div>
        <div>
          {!selected && <p className="muted">Select a run to see each step's input and output.</p>}
          {selected && !detail && <p className="muted">Loading run…</p>}
          {detail && (
            <>
              <div className="panel-title-row">
                <h4 style={{ margin: 0 }}>Run <code>{detail.id}</code> <Pill tone={TONE[detail.status] || 'neutral'}>{detail.status}</Pill></h4>
                <div className="button-row">
                  <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => retry('ON_LATEST_VERSION')}>Re-run</Button>
                  {detail.status === 'FAILED' && <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => retry('FROM_FAILED_STEP')}>Retry from failed step</Button>}
                </div>
              </div>
              {detail.failed_step && <div className="notice warn">Failed at <code>{detail.failed_step}</code></div>}
              {detail.steps.map(step => (
                <details key={step.name} className="run-step" open={step.status === 'FAILED'}>
                  <summary><Pill tone={TONE[step.status] || 'neutral'}>{step.status || '—'}</Pill> <code>{step.name}</code> <span className="muted">{step.type}</span></summary>
                  {step.error && <div className="notice error">{step.error}</div>}
                  <div className="run-io"><div><span className="muted">Input</span><JsonView value={step.input ?? {}} maxHeight={200} /></div><div><span className="muted">Output</span><JsonView value={step.output ?? {}} maxHeight={200} /></div></div>
                </details>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
