import { useEffect, useMemo, useState } from 'react'
import {
  applyStudioOperation, fetchStudioFlow, fetchStudioPiece, fetchStudioStepSample, fetchStudioVersions, publishWorkflowApp, setWorkflowAppStatus, testStudioStep,
} from '../api'
import { Button, Field, JsonView, Modal, Notice, Pill, Tabs, useNotice } from '../components/ui'
import AppChat from '../components/AppChat'
import ConnectionDialog from './ConnectionDialog'
import StepPicker from './StepPicker'
import RunsPanel from './RunsPanel'
import PropertyForm, { DataPicker } from './PropertyForm'
import {
  OPERATORS, SINGLE_VALUE_OPERATORS, coerceValue, computeValid, newCodeAction, newLoopAction, newPieceAction, newRouterAction, nextStepName, pieceAuthOptions, pieceShortName, stepToUpdateRequest, tilde,
} from './flowModel'

// Workflow Studio: the portal's own flow builder. Every call goes to the gateway, which talks
// to the engine with the service account; the engine's UI, origin and login never appear.
// docs/WORKFLOW_STUDIO_PLAN.md (Track 2), docs/ROADMAP.md (Sprints WS-1..WS-3).

const TYPE_LABEL = { PIECE_TRIGGER: 'Trigger', PIECE: 'Action', CODE: 'Code', ROUTER: 'Router', LOOP_ON_ITEMS: 'Loop' }

function stepIcon(step, piece) {
  if (piece?.logoUrl) return <img src={piece.logoUrl} alt="" className="step-logo" />
  return <span className={`step-glyph ${step.type.toLowerCase()}`}>{step.type === 'CODE' ? '{}' : step.type === 'ROUTER' ? '⑂' : step.type === 'LOOP_ON_ITEMS' ? '↻' : '●'}</span>
}

// ----------------------------------------------------------------------------- step list
function StepTree({ steps, pieces, selected, onSelect, onAdd, canManage }) {
  const byParent = useMemo(() => {
    const map = new Map()
    steps.forEach(s => { const key = `${s.parent ?? ''}|${s.branch ?? ''}`; if (!map.has(key)) map.set(key, []); map.get(key).push(s) })
    return map
  }, [steps])
  const AddButton = ({ parentStep, location, branchIndex, label = '+' }) => canManage
    ? <button type="button" className="step-add" title="Add step here" onClick={() => onAdd({ parentStep, location, branchIndex })}>{label}</button>
    : null
  const renderChain = (parent, branch) => {
    const chain = byParent.get(`${parent ?? ''}|${branch ?? ''}`) || []
    return chain.map(step => {
      const piece = step.pieceName ? pieces[step.pieceName] : null
      const isTrigger = step.type === 'PIECE_TRIGGER'
      return (
        <div key={step.name} className="step-node-wrap">
          <button type="button" className={`step-node ${selected === step.name ? 'active' : ''} ${step.valid === false ? 'invalid' : ''} ${step.skip ? 'skipped' : ''}`} onClick={() => onSelect(step.name)}>
            {stepIcon(step, piece)}
            <span className="step-node-text"><strong>{step.displayName}</strong><span className="muted">{isTrigger ? 'Trigger' : step.name}{step.pieceName ? ` · ${pieceShortName(step.pieceName)}` : ''}{step.skip ? ' · skipped' : ''}</span></span>
            {step.valid === false && <span className="step-flag" title="Incomplete">!</span>}
          </button>
          {step.type === 'ROUTER' && (
            <div className="branches">
              {(step.branches || []).map((b, i) => (
                <div key={i} className="branch">
                  <div className="branch-label">{b.branchName || `Branch ${i + 1}`}{b.branchType === 'FALLBACK' && <span className="muted"> (otherwise)</span>}</div>
                  {renderChain(step.name, i)}
                  <AddButton parentStep={step.name} location="INSIDE_BRANCH" branchIndex={i} />
                </div>
              ))}
            </div>
          )}
          {step.type === 'LOOP_ON_ITEMS' && (
            <div className="branches"><div className="branch"><div className="branch-label">each item</div>{renderChain(step.name, null)}<AddButton parentStep={step.name} location="INSIDE_LOOP" /></div></div>
          )}
          <AddButton parentStep={step.name} location="AFTER" />
        </div>
      )
    })
  }
  return <div className="step-tree">{renderChain(null, null)}</div>
}

// ----------------------------------------------------------------------------- editors
function ConnectionPicker({ appId, piece, value, connections, onChange, onNew }) {
  const mine = connections.filter(c => c.pieceName === piece?.name)
  const toExpr = (externalId) => `{{connections['${externalId}']}}`
  const current = mine.find(c => value === toExpr(c.externalId))
  return (
    <Field label="Connection" required hint={pieceAuthOptions(piece)[0]?.description ? undefined : 'Credentials stay encrypted in the engine, scoped to this app.'}>
      <div className="prop-input-row">
        <select value={current ? current.externalId : ''} onChange={(e) => onChange(e.target.value ? toExpr(e.target.value) : '')}>
          <option value="">{mine.length ? 'Select a connection…' : 'No connection yet'}</option>
          {mine.map(c => <option key={c.externalId} value={c.externalId}>{c.displayName} {c.status && c.status !== 'ACTIVE' ? `(${c.status})` : ''}</option>)}
        </select>
        <Button variant="ghost" size="sm" onClick={onNew}>New connection</Button>
      </div>
      {value && !current && <small className="muted">Uses <code>{value}</code></small>}
    </Field>
  )
}

function CodeEditor({ draft, setDraft, dataSteps }) {
  const inputs = Object.entries(draft.input || {})
  const update = (list) => setDraft({ ...draft, input: Object.fromEntries(list.filter(([k]) => k !== '')) })
  return (
    <>
      <Field label="Inputs" hint="Available inside the code as inputs.<name>">
        <div className="kv-editor">
          {inputs.map(([k, v], i) => (
            <div key={i} className="kv-editor-row">
              <input value={k} placeholder="name" onChange={(e) => { const l = inputs.slice(); l[i] = [e.target.value, v]; update(l) }} />
              <div className="prop-input-row"><input value={typeof v === 'string' ? v : JSON.stringify(v)} placeholder="value or {{expression}}" onChange={(e) => { const l = inputs.slice(); l[i] = [k, e.target.value]; update(l) }} /><DataPicker steps={dataSteps} onInsert={(expr) => { const l = inputs.slice(); l[i] = [k, (typeof v === 'string' ? v : '') + expr]; update(l) }} /></div>
              <button type="button" className="ghost ui-btn-sm" onClick={() => update(inputs.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
          <button type="button" className="ghost ui-btn-sm" onClick={() => update([...inputs, ['', '']])}>+ Add input</button>
        </div>
      </Field>
      <Field label="Code (TypeScript)" hint="Export an async function named code; return a JSON-serialisable value.">
        <textarea className="mono" rows={14} value={draft.sourceCode?.code || ''} onChange={(e) => setDraft({ ...draft, sourceCode: { ...(draft.sourceCode || {}), code: e.target.value, packageJson: draft.sourceCode?.packageJson || '{}' } })} />
      </Field>
      <details><summary className="muted">package.json (npm dependencies)</summary><textarea className="mono" rows={4} value={draft.sourceCode?.packageJson || '{}'} onChange={(e) => setDraft({ ...draft, sourceCode: { ...(draft.sourceCode || {}), packageJson: e.target.value } })} /></details>
    </>
  )
}

function ConditionEditor({ cond, onChange, onRemove, dataSteps }) {
  const single = SINGLE_VALUE_OPERATORS.has(cond.operator)
  return (
    <div className="condition-row">
      <div className="prop-input-row"><input value={cond.firstValue ?? ''} placeholder="value or {{expression}}" onChange={(e) => onChange({ ...cond, firstValue: e.target.value })} /><DataPicker steps={dataSteps} onInsert={(expr) => onChange({ ...cond, firstValue: (cond.firstValue || '') + expr })} /></div>
      <select value={cond.operator} onChange={(e) => onChange({ ...cond, operator: e.target.value })}>{OPERATORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      {!single && <div className="prop-input-row"><input value={cond.secondValue ?? ''} placeholder="compare with" onChange={(e) => onChange({ ...cond, secondValue: e.target.value })} /><DataPicker steps={dataSteps} onInsert={(expr) => onChange({ ...cond, secondValue: (cond.secondValue || '') + expr })} /></div>}
      {!single && cond.operator.startsWith('TEXT') && <label className="toggle"><input type="checkbox" checked={Boolean(cond.caseSensitive)} onChange={(e) => onChange({ ...cond, caseSensitive: e.target.checked })} /> case sensitive</label>}
      <button type="button" className="ghost ui-btn-sm" onClick={onRemove}>×</button>
    </div>
  )
}

function RouterEditor({ draft, setDraft, dataSteps, onAddBranch, onDeleteBranch, canManage }) {
  const branches = draft.branches || []
  const setBranch = (i, next) => setDraft({ ...draft, branches: branches.map((b, j) => (j === i ? next : b)) })
  return (
    <>
      <p className="muted" style={{ fontSize: '0.78rem' }}>Branches are evaluated top to bottom; the first match runs. Within a branch, groups are OR-ed and the conditions inside a group are AND-ed.</p>
      {branches.map((b, i) => (
        <div key={i} className="branch-editor">
          <div className="panel-title-row">
            <Field label={`Branch ${i + 1}`}><input value={b.branchName || ''} onChange={(e) => setBranch(i, { ...b, branchName: e.target.value })} /></Field>
            {b.branchType === 'CONDITION' && canManage && branches.filter(x => x.branchType === 'CONDITION').length > 1 && <Button variant="ghost" size="sm" onClick={() => onDeleteBranch(i)}>Delete branch</Button>}
          </div>
          {b.branchType === 'FALLBACK' ? <p className="muted">Runs when no other branch matches.</p> : (
            <>
              {(b.conditions || []).map((group, gi) => (
                <div key={gi} className="condition-group">
                  {gi > 0 && <div className="muted or-label">OR</div>}
                  {group.map((cond, ci) => (
                    <ConditionEditor key={ci} cond={cond} dataSteps={dataSteps}
                      onChange={(next) => setBranch(i, { ...b, conditions: b.conditions.map((g, x) => (x === gi ? g.map((c, y) => (y === ci ? next : c)) : g)) })}
                      onRemove={() => setBranch(i, { ...b, conditions: b.conditions.map((g, x) => (x === gi ? g.filter((_, y) => y !== ci) : g)).filter(g => g.length) })} />
                  ))}
                  <button type="button" className="ghost ui-btn-sm" onClick={() => setBranch(i, { ...b, conditions: b.conditions.map((g, x) => (x === gi ? [...g, { firstValue: '', secondValue: '', operator: 'TEXT_CONTAINS', caseSensitive: false }] : g)) })}>+ AND condition</button>
                </div>
              ))}
              <button type="button" className="ghost ui-btn-sm" onClick={() => setBranch(i, { ...b, conditions: [...(b.conditions || []), [{ firstValue: '', secondValue: '', operator: 'TEXT_CONTAINS', caseSensitive: false }]] })}>+ OR group</button>
            </>
          )}
        </div>
      ))}
      {canManage && <div className="button-row"><Button variant="ghost" size="sm" onClick={onAddBranch}>+ Add branch</Button></div>}
    </>
  )
}

function ErrorHandling({ draft, setDraft }) {
  const eh = draft.errorHandlingOptions || {}
  const set = (key, value) => setDraft({ ...draft, errorHandlingOptions: { ...eh, [key]: { value } } })
  return (
    <details className="error-handling"><summary className="muted">Error handling</summary>
      <label className="toggle"><input type="checkbox" checked={Boolean(eh.continueOnFailure?.value)} onChange={(e) => set('continueOnFailure', e.target.checked)} /> Continue the flow if this step fails</label>
      <label className="toggle"><input type="checkbox" checked={Boolean(eh.retryOnFailure?.value)} onChange={(e) => set('retryOnFailure', e.target.checked)} /> Retry on failure (engine back-off)</label>
    </details>
  )
}

function TriggerSample({ app, step, sample, onSaved }) {
  const isChat = step.pieceName === '@activepieces/piece-forms' && step.actionName === 'chat_submission'
  const [text, setText] = useState(() => JSON.stringify(sample ?? (isChat ? { sessionId: 'studio-sample', message: 'Hello from the Studio', files: [] } : {}), null, 2))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    setBusy(true); setError('')
    try { const payload = JSON.parse(text); await applyStudioOperation(app.id, 'SAVE_SAMPLE_DATA', { stepName: step.name, payload, type: 'OUTPUT' }); onSaved(payload) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return (
    <div className="test-panel">
      <h4>Sample trigger data</h4>
      <p className="muted" style={{ fontSize: '0.78rem' }}>{isChat ? 'A chat turn as the trigger will receive it. Later steps reference it as {{trigger[\'output\'][\'message\']}} and test against it.' : 'Example output of the trigger, used by step tests and the data picker.'}</p>
      <textarea className="mono" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
      {error && <div className="notice error">{error}</div>}
      <div className="button-row"><Button size="sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save sample'}</Button></div>
    </div>
  )
}

function StepTest({ app, step, result, onResult, dirty }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async () => {
    setBusy(true); setError('')
    try { onResult(await testStudioStep(app.id, step.name)) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return (
    <div className="test-panel">
      <div className="panel-title-row"><h4>Test this step</h4><Button size="sm" variant="ghost" disabled={busy || dirty} title={dirty ? 'Save the step first' : ''} onClick={run}>{busy ? 'Running…' : 'Run test'}</Button></div>
      {dirty && <small className="muted">Save the step before testing.</small>}
      {error && <div className="notice error">{error}</div>}
      {result && (
        <>
          <div>{result.success ? <Pill tone="ok">succeeded</Pill> : result.settled ? <Pill tone="danger">{result.status || 'failed'}</Pill> : <Pill tone="warn">still running</Pill>} {result.run_id && <span className="muted">run {result.run_id}{result.duration_ms != null ? ` · ${result.duration_ms} ms` : ''}</span>}</div>
          {result.error && <div className="notice error" style={{ whiteSpace: 'pre-wrap' }}>{typeof result.error === 'string' ? result.error : JSON.stringify(result.error)}</div>}
          <div className="run-io"><div><span className="muted">Input</span><JsonView value={result.input ?? {}} maxHeight={220} /></div><div><span className="muted">Output</span><JsonView value={result.output ?? {}} maxHeight={220} /></div></div>
          {result.stderr && <pre className="json-view">{result.stderr}</pre>}
        </>
      )}
    </div>
  )
}

function StepEditor({ app, step, pieces, connections, samples, tests, dataSteps, canManage, onOperation, onNewConnection, onChangeTrigger, onTestResult, onSampleSaved }) {
  const [draft, setDraft] = useState(step)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  useEffect(() => { setDraft(step); n.clear() }, [step])
  const piece = step.pieceName ? pieces[step.pieceName] : null
  const definition = piece ? (step.type === 'PIECE_TRIGGER' ? piece.triggers?.[step.actionName] : piece.actions?.[step.actionName]) : null
  const props = definition?.props || {}
  const needsAuth = Boolean(piece?.auth) && definition?.requireAuth !== false
  const dirty = JSON.stringify(draft) !== JSON.stringify(step)
  const isTrigger = step.type === 'PIECE_TRIGGER'

  const save = async () => {
    setBusy('save'); n.clear()
    try {
      const next = { ...draft }
      if (next.type === 'PIECE' || next.type === 'PIECE_TRIGGER') {
        const input = Object.fromEntries(Object.entries(next.input || {}).map(([k, v]) => [k, coerceValue(props[k], v)]))
        next.input = input
        next.valid = computeValid(props, input, needsAuth)
      } else if (next.type === 'LOOP_ON_ITEMS') next.valid = Boolean((next.items || '').trim())
      else if (next.type === 'ROUTER') next.valid = (next.branches || []).every(b => b.branchType === 'FALLBACK' || (b.conditions || []).every(g => g.every(c => c.operator && (SINGLE_VALUE_OPERATORS.has(c.operator) ? c.firstValue : c.firstValue && c.secondValue !== undefined))))
      else if (next.type === 'CODE') next.valid = Boolean(next.sourceCode?.code?.trim())
      await onOperation(isTrigger ? 'UPDATE_TRIGGER' : 'UPDATE_ACTION', stepToUpdateRequest(next))
      n.ok('Step saved.')
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const remove = async () => {
    if (!window.confirm(`Delete step ${step.displayName}? Steps nested inside it are deleted too.`)) return
    setBusy('delete'); try { await onOperation('DELETE_ACTION', { names: [step.name] }) } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const duplicate = async () => { setBusy('dup'); try { await onOperation('DUPLICATE_ACTION', { stepName: step.name }) } catch (err) { n.fail(err) } finally { setBusy('') } }
  const skip = async () => { setBusy('skip'); try { await onOperation('SET_SKIP_ACTION', { names: [step.name], skip: !step.skip }) } catch (err) { n.fail(err) } finally { setBusy('') } }
  const addBranch = async () => { setBusy('branch'); try { await onOperation('ADD_BRANCH', { stepName: step.name, branchIndex: (draft.branches || []).length - 1, branchName: `Branch ${(draft.branches || []).length}`, conditions: [[{ firstValue: '', secondValue: '', operator: 'TEXT_CONTAINS', caseSensitive: false }]] }) } catch (err) { n.fail(err) } finally { setBusy('') } }
  const deleteBranch = async (i) => { if (!window.confirm('Delete this branch and the steps inside it?')) return; setBusy('branch'); try { await onOperation('DELETE_BRANCH', { stepName: step.name, branchIndex: i }) } catch (err) { n.fail(err) } finally { setBusy('') } }

  const context = { pieceName: step.pieceName, pieceVersion: step.pieceVersion, actionName: step.actionName, input: draft.input || {} }
  return (
    <div className="step-editor">
      <div className="panel-title-row">
        <div className="step-editor-title">
          {stepIcon(step, piece)}
          <div>
            <input className="step-title-input" value={draft.displayName || ''} disabled={!canManage} onChange={(e) => setDraft({ ...draft, displayName: e.target.value })} />
            <div className="muted" style={{ fontSize: '0.75rem' }}>{TYPE_LABEL[step.type]} · <code>{step.name}</code>{piece ? ` · ${piece.displayName} / ${definition?.displayName || step.actionName}` : ''}{definition?.description ? ` — ${definition.description}` : ''}</div>
          </div>
        </div>
        {canManage && (
          <div className="button-row">
            {isTrigger ? <Button variant="ghost" size="sm" onClick={onChangeTrigger}>Change trigger</Button> : (
              <>
                <Button variant="ghost" size="sm" disabled={!!busy} onClick={skip}>{step.skip ? 'Unskip' : 'Skip'}</Button>
                <Button variant="ghost" size="sm" disabled={!!busy} onClick={duplicate}>Duplicate</Button>
                <Button variant="danger" size="sm" disabled={!!busy} onClick={remove}>Delete</Button>
              </>
            )}
            <Button size="sm" disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : dirty ? 'Save step' : 'Saved'}</Button>
          </div>
        )}
      </div>
      <Notice notice={n.notice} />
      {!piece && step.pieceName && <p className="muted">Loading piece metadata…</p>}
      {(step.type === 'PIECE' || step.type === 'PIECE_TRIGGER') && piece && (
        <PropertyForm appId={app.id} props={props} input={draft.input || {}} onChange={(input) => setDraft({ ...draft, input })} context={context} dataSteps={dataSteps}
          authSlot={needsAuth ? <ConnectionPicker appId={app.id} piece={piece} value={draft.input?.auth} connections={connections} onChange={(auth) => setDraft({ ...draft, input: { ...(draft.input || {}), auth } })} onNew={() => onNewConnection(piece)} /> : null} />
      )}
      {step.type === 'CODE' && <CodeEditor draft={draft} setDraft={setDraft} dataSteps={dataSteps} />}
      {step.type === 'ROUTER' && <RouterEditor draft={draft} setDraft={setDraft} dataSteps={dataSteps} onAddBranch={addBranch} onDeleteBranch={deleteBranch} canManage={canManage} />}
      {step.type === 'LOOP_ON_ITEMS' && (
        <Field label="Items" required hint="A list to iterate; the steps inside see {{step_name['output']['item']}} and {{step_name['output']['index']}}">
          <div className="prop-input-row"><input value={draft.items || ''} placeholder="{{trigger['output']['files']}}" onChange={(e) => setDraft({ ...draft, items: e.target.value })} /><DataPicker steps={dataSteps} onInsert={(expr) => setDraft({ ...draft, items: (draft.items || '') + expr })} /></div>
        </Field>
      )}
      {(step.type === 'PIECE' || step.type === 'CODE') && <ErrorHandling draft={draft} setDraft={setDraft} />}
      {isTrigger ? <TriggerSample app={app} step={step} sample={samples[step.name]} onSaved={onSampleSaved} /> : <StepTest app={app} step={step} result={tests[step.name]} onResult={onTestResult} dirty={dirty} />}
    </div>
  )
}

// ----------------------------------------------------------------------------- versions
function VersionsPanel({ app, current, onRestored, canManage }) {
  const [versions, setVersions] = useState(null)
  const [busy, setBusy] = useState('')
  const n = useNotice()
  useEffect(() => { fetchStudioVersions(app.id).then(r => setVersions(r.versions || [])).catch(n.fail) }, [app.id, current?.id])
  const restore = async (v) => {
    if (!window.confirm(`Replace the current draft with version ${v.id}?`)) return
    setBusy(v.id); n.clear()
    try { await applyStudioOperation(app.id, 'USE_AS_DRAFT', { versionId: v.id }); n.ok('Draft replaced from the selected version.'); onRestored() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  return (
    <div>
      <Notice notice={n.notice} />
      <div className="table-wrap"><table className="policy-table finops-table"><thead><tr><th>Version</th><th>Name</th><th>State</th><th>Valid</th><th>Updated</th><th></th></tr></thead>
        <tbody>
          {(versions || []).map(v => <tr key={v.id}><td><code>{v.id}</code>{v.id === current?.id && <Pill tone="info" className="ml">current draft</Pill>}</td><td>{v.displayName}</td><td><Pill tone={v.state === 'LOCKED' ? 'ok' : 'draft'}>{v.state}</Pill></td><td>{v.valid ? 'yes' : 'no'}</td><td>{v.updated ? new Date(v.updated).toLocaleString() : ''}</td><td>{canManage && v.state === 'LOCKED' && <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => restore(v)}>{busy === v.id ? 'Restoring…' : 'Use as draft'}</Button>}</td></tr>)}
          {versions && versions.length === 0 && <tr><td colSpan="6" className="muted">No versions.</td></tr>}
        </tbody></table></div>
    </div>
  )
}

// ----------------------------------------------------------------------------- studio
export default function WorkflowStudio({ app: initialApp, canManage, onClose, onAppChanged }) {
  const [data, setData] = useState(null)
  const [pieces, setPieces] = useState({})
  const [selected, setSelected] = useState('trigger')
  const [tab, setTab] = useState('build')
  const [picker, setPicker] = useState(null)
  const [connDialog, setConnDialog] = useState(null)
  const [samples, setSamples] = useState({})
  const [tests, setTests] = useState({})
  const [busy, setBusy] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState('')
  const n = useNotice()
  const app = data?.app || initialApp

  const load = async () => {
    try {
      const payload = await fetchStudioFlow(initialApp.id)
      setData(payload)
      const names = [...new Set(payload.steps.map(s => s.pieceName).filter(Boolean))]
      const missing = names.filter(name => !pieces[name])
      if (missing.length) {
        const loaded = await Promise.all(missing.map(name => fetchStudioPiece(name).catch(() => null)))
        setPieces(prev => ({ ...prev, ...Object.fromEntries(missing.map((name, i) => [name, loaded[i]]).filter(([, p]) => p)) }))
      }
      return payload
    } catch (err) { n.fail(err); return null }
  }
  useEffect(() => { load() }, [initialApp.id])
  // Samples recorded in earlier sessions feed the data picker.
  useEffect(() => {
    if (!data) return
    data.steps.filter(s => s.sampleData?.sampleDataFileId && samples[s.name] === undefined).forEach(s => {
      fetchStudioStepSample(app.id, s.name).then(r => setSamples(prev => ({ ...prev, [s.name]: r.payload }))).catch(() => {})
    })
  }, [data?.version?.id])

  const steps = data?.steps || []
  const selectedStep = steps.find(s => s.name === selected) || steps[0]
  const dataSteps = useMemo(() => {
    if (!selectedStep) return []
    const index = steps.findIndex(s => s.name === selectedStep.name)
    return steps.slice(0, index).filter(s => s.type !== 'ROUTER').map(s => ({ name: s.name, displayName: s.displayName, sample: samples[s.name] ?? tests[s.name]?.output }))
  }, [steps, selectedStep?.name, samples, tests])

  const operation = async (type, request) => {
    const result = await applyStudioOperation(app.id, type, request)
    setData(result)
    const names = [...new Set(result.steps.map(s => s.pieceName).filter(Boolean))].filter(name => !pieces[name])
    if (names.length) { const loaded = await Promise.all(names.map(name => fetchStudioPiece(name).catch(() => null))); setPieces(prev => ({ ...prev, ...Object.fromEntries(names.map((name, i) => [name, loaded[i]]).filter(([, p]) => p)) })) }
    return result
  }

  const addStep = async (choice) => {
    const { parentStep, location, branchIndex } = picker
    const name = nextStepName(steps)
    let action
    if (choice.kind === 'code') action = newCodeAction(name)
    else if (choice.kind === 'router') action = newRouterAction(name)
    else if (choice.kind === 'loop') action = newLoopAction(name)
    else if (choice.kind === 'piece') {
      action = newPieceAction({ name, piece: choice.piece, actionName: choice.name, action: choice.item })
      // Pre-fill the app's own connection for our pieces so the step is usable immediately.
      const own = (data.connections || []).find(c => c.pieceName === choice.piece.name)
      if (own && choice.piece.auth) action.settings.input.auth = `{{connections['${own.externalId}']}}`
      setPieces(prev => ({ ...prev, [choice.piece.name]: choice.piece }))
    } else if (choice.kind === 'trigger') {
      setPieces(prev => ({ ...prev, [choice.piece.name]: choice.piece }))
      setPicker(null); setBusy('op')
      try {
        await operation('UPDATE_TRIGGER', { name: 'trigger', displayName: choice.item.displayName || choice.name, type: 'PIECE_TRIGGER', valid: false, settings: { pieceName: choice.piece.name, pieceVersion: tilde(choice.piece.version), triggerName: choice.name, input: {}, propertySettings: {} } })
        setSelected('trigger')
      } catch (err) { n.fail(err) } finally { setBusy('') }
      return
    }
    setPicker(null); setBusy('op')
    try {
      await operation('ADD_ACTION', { parentStep, stepLocationRelativeToParent: location, branchIndex, action })
      setSelected(name)
    } catch (err) { n.fail(err) } finally { setBusy('') }
  }

  const publish = async () => {
    setBusy('publish'); n.clear()
    try { const r = await publishWorkflowApp(app.id); n.ok(`${r.name || app.name} published. The current draft is live.`); await load(); onAppChanged?.() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const toggle = async () => {
    setBusy('toggle'); n.clear()
    try { await setWorkflowAppStatus(app.id, app.status !== 'published'); await load(); onAppChanged?.() } catch (err) { n.fail(err) } finally { setBusy('') }
  }
  const rename = async () => {
    setBusy('rename')
    try { await operation('CHANGE_NAME', { displayName: newName }); setRenaming(false) } catch (err) { n.fail(err) } finally { setBusy('') }
  }

  const version = data?.version
  const invalidCount = steps.filter(s => s.valid === false).length
  return (
    <section className="panel studio">
      <div className="studio-header">
        <div className="studio-title">
          <Button variant="ghost" size="sm" onClick={onClose}>← Apps</Button>
          <div>
            <h2 style={{ margin: 0 }}>{version?.displayName || app.name} {canManage && <button type="button" className="link-btn" onClick={() => { setNewName(version?.displayName || app.name); setRenaming(true) }}>rename</button>}</h2>
            <div className="muted" style={{ fontSize: '0.78rem' }}>
              <Pill tone={app.status === 'published' ? 'ok' : app.status === 'disabled' ? 'neutral' : 'draft'}>{app.status}</Pill>{' '}
              {version && <Pill tone={version.state === 'LOCKED' ? 'ok' : 'draft'}>{version.state === 'LOCKED' ? 'draft = published' : 'unpublished changes'}</Pill>}{' '}
              {invalidCount > 0 && <Pill tone="warn">{invalidCount} incomplete step{invalidCount > 1 ? 's' : ''}</Pill>}
              {' '}<span>Model {app.model || 'default'} · RAI {app.rai_mode} · attribution <code>{app.client_id}</code></span>
            </div>
          </div>
        </div>
        <div className="button-row">
          <Tabs items={[{ id: 'build', label: 'Build' }, { id: 'runs', label: 'Runs' }, { id: 'versions', label: 'Versions' }, { id: 'chat', label: 'Chat' }]} value={tab} onChange={setTab} />
          {canManage && app.published_at && <Button variant="ghost" disabled={!!busy} onClick={toggle}>{app.status === 'published' ? 'Disable' : 'Enable'}</Button>}
          {canManage && <Button disabled={!!busy || invalidCount > 0} title={invalidCount ? 'Complete every step first' : ''} onClick={publish}>{busy === 'publish' ? 'Publishing…' : app.published_at ? 'Publish changes' : 'Publish'}</Button>}
        </div>
      </div>
      <Notice notice={n.notice} />
      {!data && <p className="muted">Loading flow…</p>}
      {data && tab === 'build' && (
        <div className="studio-layout">
          <div className="studio-steps">
            <StepTree steps={steps} pieces={pieces} selected={selectedStep?.name} onSelect={setSelected} canManage={canManage} onAdd={(where) => setPicker({ mode: 'action', ...where })} />
          </div>
          <div className="studio-editor">
            {selectedStep && (
              <StepEditor key={selectedStep.name + (version?.id || '')} app={app} step={selectedStep} pieces={pieces} connections={data.connections || []} samples={samples} tests={tests} dataSteps={dataSteps} canManage={canManage}
                onOperation={operation} onNewConnection={(piece) => setConnDialog(piece)} onChangeTrigger={() => setPicker({ mode: 'trigger' })}
                onTestResult={(r) => setTests(prev => ({ ...prev, [selectedStep.name]: r }))} onSampleSaved={(payload) => setSamples(prev => ({ ...prev, trigger: payload }))} />
            )}
          </div>
        </div>
      )}
      {data && tab === 'runs' && <RunsPanel app={app} />}
      {data && tab === 'versions' && <VersionsPanel app={app} current={version} canManage={canManage} onRestored={load} />}
      {data && tab === 'chat' && (app.status === 'published' ? <AppChat app={app} /> : <p className="muted">Publish the app to chat with it. The Chat tab talks to the published version through the gateway.</p>)}
      {picker && <StepPicker mode={picker.mode} onClose={() => setPicker(null)} onPick={addStep} />}
      {connDialog && <ConnectionDialog appId={app.id} piece={connDialog} onClose={() => setConnDialog(null)} onCreated={async (created) => { setConnDialog(null); await load(); n.ok(`Connection ${created.displayName} created. Select it in the step.`) }} />}
      {renaming && <Modal title="Rename flow" onClose={() => setRenaming(false)} footer={<><Button disabled={!newName.trim() || !!busy} onClick={rename}>Rename</Button><Button variant="ghost" onClick={() => setRenaming(false)}>Cancel</Button></>}><Field label="Flow name"><input value={newName} onChange={(e) => setNewName(e.target.value)} /></Field></Modal>}
    </section>
  )
}
