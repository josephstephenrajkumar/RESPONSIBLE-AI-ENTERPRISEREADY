import { useEffect, useState } from 'react'
import { addCatalogModel, deleteCatalogModel, fetchAvailableModels, fetchModelCatalog, testCatalogModel } from '../api'
import { formatMs, formatUsd } from './charts'

// Admin view of the LiteLLM proxy's model catalogue: which providers the proxy has
// credentials for, which models are served (from litellm/config.yaml or added at
// runtime), and controls to add, test and remove models. Keys never pass through
// this screen: a new model references the proxy's own environment variable.

function perMillion(value) {
  return value === null || value === undefined ? 'n/a' : `$${Number(value).toFixed(3)}/M`
}

function ProviderCard({ provider, selected, onSelect }) {
  const credential = provider.credential || {}
  return (
    <div className={`provider-card${selected ? ' selected' : ''}${provider.enabled ? '' : ' disabled'}`}>
      <h4>
        {provider.display_name}
        <span className={`pill ${provider.enabled ? 'enabled' : 'disabled'}`}>{provider.enabled ? 'enabled' : 'not enabled'}</span>
      </h4>
      <p>
        {credential.type === 'iam' ? 'Credential: IAM task role' : `Credential: ${credential.env} (proxy only)`}
        {' · '}{provider.configured_models} model{provider.configured_models === 1 ? '' : 's'} configured
      </p>
      {provider.enabled ? (
        <button type="button" className={selected ? '' : 'ghost'} onClick={() => onSelect(provider.id)}>
          {selected ? 'Selected' : 'Browse models'}
        </button>
      ) : (
        <p className="muted" title={provider.how_to_enable}>{provider.how_to_enable}</p>
      )}
    </div>
  )
}

export default function ModelCatalog({ canManage }) {
  const [catalog, setCatalog] = useState(null)
  const [error, setError] = useState(null)
  const [selectedProvider, setSelectedProvider] = useState(null)
  const [available, setAvailable] = useState(null)
  const [query, setQuery] = useState('')
  const [pick, setPick] = useState(null)
  const [alias, setAlias] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState(null)
  const [testResults, setTestResults] = useState({})

  const load = () => {
    setError(null)
    fetchModelCatalog().then(setCatalog).catch(err => setError(err.message))
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!selectedProvider) return
    setAvailable(null)
    fetchAvailableModels(selectedProvider, query)
      .then(setAvailable)
      .catch(err => setAvailable({ models: [], note: err.message }))
  }, [selectedProvider, query])

  const runAdd = async () => {
    if (!pick || !selectedProvider) return
    setBusy('add'); setNotice(null)
    try {
      const result = await addCatalogModel({ provider: selectedProvider, model: pick.id, model_name: alias || undefined })
      setNotice({ tone: 'ok', text: `Added ${result.model_name} → ${result.litellm_model}. Test it below before pointing chat at it.` })
      setPick(null); setAlias('')
      load()
      fetchAvailableModels(selectedProvider, query).then(setAvailable).catch(() => null)
    } catch (err) {
      setNotice({ tone: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  const runDelete = async (model) => {
    if (!window.confirm(`Remove ${model.model_name} from the proxy catalogue?`)) return
    setBusy(`delete:${model.model_id}`); setNotice(null)
    try {
      await deleteCatalogModel(model.model_id)
      setNotice({ tone: 'ok', text: `Removed ${model.model_name}.` })
      load()
    } catch (err) {
      setNotice({ tone: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  const runTest = async (model) => {
    setBusy(`test:${model.model_name}`)
    try {
      const result = await testCatalogModel(model.model_name)
      setTestResults(prev => ({ ...prev, [model.model_name]: result }))
    } catch (err) {
      setTestResults(prev => ({ ...prev, [model.model_name]: { status: 'error', error_type: err.message } }))
    } finally {
      setBusy('')
    }
  }

  if (error) {
    return (
      <section className="panel">
        <h2>Model Catalogue</h2>
        <p className="muted">Unable to load the model catalogue: {error}</p>
      </section>
    )
  }
  if (!catalog) {
    return (
      <section className="panel">
        <h2>Model Catalogue</h2>
        <p className="muted">Loading providers and models from the LiteLLM proxy...</p>
      </section>
    )
  }

  const providerName = (id) => (catalog.providers.find(p => p.id === id) || {}).display_name || id

  return (
    <section className="panel model-catalog">
      <div className="panel-title-row">
        <div>
          <h2>Model Catalogue</h2>
          <p className="muted">
            Providers and models served by the LiteLLM proxy at <code>{catalog.proxy_url}</code>. Chat default{' '}
            <code>{catalog.default_model}</code>, judge <code>{catalog.judge_model}</code>
            {catalog.allowed_models?.length ? <> · allowlist: <code>{catalog.allowed_models.join(', ')}</code></> : null}.
          </p>
        </div>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>

      <h3>Providers</h3>
      <div className="provider-grid">
        {catalog.providers.map(provider => (
          <ProviderCard key={provider.id} provider={provider} selected={selectedProvider === provider.id}
            onSelect={(id) => { setSelectedProvider(id); setPick(null); setQuery('') }} />
        ))}
      </div>

      {selectedProvider && (
        <div className="catalog-add">
          <div>
            <h3>Available from {providerName(selectedProvider)}</h3>
            <div className="field">
              <input placeholder="Filter models..." value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            {!available ? <p className="muted">Loading model list...</p> : (
              <>
                {available.note && <p className="muted">{available.note}</p>}
                {available.region && <p className="muted">Region {available.region}. Bedrock requires inference-profile ids (<code>apac.*</code>, <code>global.*</code>) for most models.</p>}
                <div className="model-pick-list">
                  {available.models.length === 0 && <p className="muted" style={{ padding: 12 }}>No models match.</p>}
                  {available.models.map(model => (
                    <div key={model.id} className={`model-pick-row${pick?.id === model.id ? ' selected' : ''}`} onClick={() => { setPick(model); setAlias('') }}>
                      <div>
                        <code>{model.id}</code>
                        <div className="muted">
                          {model.max_input_tokens ? `${Number(model.max_input_tokens).toLocaleString()} ctx` : 'context n/a'}
                          {model.supports_function_calling ? ' · tools' : ''}{model.supports_vision ? ' · vision' : ''}
                          {model.available_in_region ? ' · available in region' : ''}
                        </div>
                      </div>
                      <span className="muted">{perMillion(model.input_cost_per_million)} in · {perMillion(model.output_cost_per_million)} out</span>
                      <span>{model.configured ? <span className="pill source-db">added</span> : null}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          <div>
            <h3>Add to the proxy</h3>
            {!canManage && <p className="muted">You can browse the catalogue; adding or removing models needs the <code>admin</code> or <code>model-admin</code> role.</p>}
            {pick ? (
              <>
                <div className="field">
                  <label>Provider model</label>
                  <input value={pick.id} readOnly />
                </div>
                <div className="field">
                  <label>Name in the gateway (optional alias)</label>
                  <input value={alias} placeholder={pick.id} onChange={(e) => setAlias(e.target.value)} />
                  <span className="muted field-note">Routes as <code>{pick.litellm_model}</code>; credential resolved by the proxy, never sent from here.</span>
                </div>
                <div className="button-row">
                  <button type="button" onClick={runAdd} disabled={!canManage || busy === 'add' || pick.configured}>
                    {pick.configured ? 'Already added' : busy === 'add' ? 'Adding...' : 'Add model'}
                  </button>
                  <button type="button" className="ghost" onClick={() => setPick(null)}>Clear</button>
                </div>
              </>
            ) : <p className="muted">Pick a model on the left.</p>}
            {notice && <p className={`catalog-test${notice.tone === 'error' ? ' error' : ''}`}>{notice.text}</p>}
          </div>
        </div>
      )}

      <h3>Configured models</h3>
      <div className="table-wrap">
        <table className="policy-table finops-table">
          <thead>
            <tr><th>Name</th><th>Provider</th><th>Routes to</th><th>Price (in / out per 1M)</th><th>Context</th><th>Source</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {catalog.models.map(model => {
              const test = testResults[model.model_name]
              return (
                <tr key={model.model_id || model.model_name}>
                  <td><code>{model.model_name}</code>{model.model_name === catalog.default_model && <span className="pill status-draft" style={{ marginLeft: 6 }}>default</span>}{model.model_name === catalog.judge_model && <span className="pill status-approved" style={{ marginLeft: 6 }}>judge</span>}</td>
                  <td>{providerName(model.provider)}</td>
                  <td><code>{model.litellm_model}</code>{model.aws_region_name ? <span className="muted"> ({model.aws_region_name})</span> : null}</td>
                  <td>{perMillion(model.input_cost_per_million)} / {perMillion(model.output_cost_per_million)}</td>
                  <td>{model.max_input_tokens ? Number(model.max_input_tokens).toLocaleString() : 'n/a'}</td>
                  <td><span className={`pill source-${model.source}`}>{model.source === 'db' ? 'added at runtime' : 'config.yaml'}</span></td>
                  <td>
                    <div className="action-cell">
                      <button type="button" className="ghost" disabled={!canManage || busy === `test:${model.model_name}`} onClick={() => runTest(model)}>
                        {busy === `test:${model.model_name}` ? 'Testing...' : 'Test'}
                      </button>
                      {model.source === 'db' && (
                        <button type="button" className="danger" disabled={!canManage || busy === `delete:${model.model_id}`} onClick={() => runDelete(model)}>Remove</button>
                      )}
                    </div>
                    {test && (
                      <div className={`catalog-test${test.status === 'success' ? '' : ' error'}`}>
                        {test.status === 'success'
                          ? `OK · ${test.served_model} · ${formatMs(test.latency_ms)} · ${formatUsd(test.cost_usd, 6)} (${test.cost_source})${test.finish_reason === 'length' ? ' · no text (token budget used by reasoning)' : ''}`
                          : `Failed · ${test.error_type || 'error'}${test.http_status ? ` (HTTP ${test.http_status})` : ''}${test.answer ? ` · ${test.answer}` : ''}`}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {catalog.groups?.length > 0 && (
        <p className="muted">
          Model groups: {catalog.groups.map(g => <code key={g.model_group} style={{ marginRight: 6 }}>{g.model_group} → {(g.providers || []).join(', ')}</code>)}
          — defined in <code>litellm/config.yaml</code>; point <code>LLM_JUDGE_MODEL</code> or chat at a group to re-route without an app release.
        </p>
      )}
    </section>
  )
}
