import { useEffect, useState } from 'react'
import { fetchHubValidators, installHubValidator } from '../api'

export default function HubValidatorCatalog({ onImportDraft, canManage = true }) {
  const [validators, setValidators] = useState([])
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [installing, setInstalling] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [lastLoadedAt, setLastLoadedAt] = useState('')
  const [messages, setMessages] = useState({})
  const [creating, setCreating] = useState('')

  const load = async () => {
    setRefreshing(true)
    try {
      const data = await fetchHubValidators()
      setValidators(data.validators || [])
      setLastLoadedAt(new Date().toLocaleTimeString())
      setMessages(prev => ({ ...prev, global: '' }))
    } catch (error) {
      setMessages(prev => ({ ...prev, global: error.message }))
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const runInstall = async (validator) => {
    setInstalling(validator.hub_uri)
    setMessages(prev => ({ ...prev, [validator.hub_uri]: '' }))
    try {
      const result = await installHubValidator({
        hub_uri: validator.hub_uri,
        install_local_models: false
      })
      setMessages(prev => ({
        ...prev,
        [validator.hub_uri]: result.status === 'installed'
          ? `${validator.name} installed.`
          : result.error || 'Install failed.'
      }))
      await load()
    } catch (error) {
      setMessages(prev => ({ ...prev, [validator.hub_uri]: error.message }))
    } finally {
      setInstalling('')
    }
  }

  const importDraft = async (validator) => {
    setCreating(validator.hub_uri)
    setMessages(prev => ({ ...prev, [validator.hub_uri]: '' }))
    try {
      const policy = await onImportDraft({
        name: `${validator.name} Hub Policy`,
        category: validator.category,
        severity: validator.severity,
        description: validator.description,
        source: 'guardrails_hub',
        policy_kind: 'guardrails_hub',
        hub_validators: [{
          hub_uri: validator.hub_uri,
          validator_class: validator.validator_class,
          install_local_models: false,
          runtime_params: validator.runtime_params || {},
          metadata: validator.metadata || {}
        }]
      })
      setMessages(prev => ({
        ...prev,
        [validator.hub_uri]: policy?.reused_existing
          ? `Policy already exists with status: ${policy.status}.`
          : 'Draft policy created.'
      }))
    } catch (error) {
      setMessages(prev => ({ ...prev, [validator.hub_uri]: error.message }))
    } finally {
      setCreating('')
    }
  }

  const categories = ['all', ...Array.from(new Set(validators.map(item => item.category).filter(Boolean))).sort()]
  const visibleValidators = validators.filter(validator => {
    const text = `${validator.name} ${validator.description} ${validator.hub_uri} ${validator.category}`.toLowerCase()
    return (category === 'all' || validator.category === category) && text.includes(query.toLowerCase())
  })

  return (
    <section className="panel hub-catalog">
      <div className="panel-title-row">
        <h2>Guardrails Hub Validators</h2>
        <button type="button" className="refresh-button" disabled={refreshing} onClick={load}>
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
      {lastLoadedAt && <p className="muted">Last refreshed at {lastLoadedAt}. Showing {visibleValidators.length} of {validators.length} validators.</p>}
      <div className="hub-catalog-controls">
        <input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="Search validators"
        />
        <select value={category} onChange={event => setCategory(event.target.value)}>
          {categories.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </div>
      <div className="hub-validator-list">
        {visibleValidators.map(validator => (
          <div className="hub-validator-row" key={validator.hub_uri}>
            <div>
              <strong>{validator.name}</strong>
              <span className={validator.installed ? 'install-status installed' : 'install-status missing'}>
                {validator.installed ? 'Installed' : 'Not installed'}
              </span>
              <p>{validator.description}</p>
              {validator.metadata?.recommended && <p className="muted">Recommended: {validator.metadata.why}</p>}
              <code>{validator.hub_uri}</code>
              {!validator.token_configured && (
                <p className="muted">Hub install requires GUARDRAILS_TOKEN on the backend.</p>
              )}
              {messages[validator.hub_uri] && <p className="install-message">{messages[validator.hub_uri]}</p>}
            </div>
            <div className="button-row">
              <button
                type="button"
                className="ghost"
                disabled={!canManage || validator.installed || installing === validator.hub_uri}
                onClick={() => runInstall(validator)}
              >
                {installing === validator.hub_uri ? 'Installing...' : 'Install'}
              </button>
              <button
                type="button"
                disabled={!canManage || creating === validator.hub_uri}
                onClick={() => importDraft(validator)}
              >
                {creating === validator.hub_uri ? 'Creating...' : 'Create Draft Policy'}
              </button>
            </div>
          </div>
        ))}
      </div>
      {messages.global && <p className="muted">{messages.global}</p>}
    </section>
  )
}
