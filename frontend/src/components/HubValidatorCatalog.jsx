import { useEffect, useState } from 'react'
import { fetchHubValidators, installHubValidator } from '../api'

export default function HubValidatorCatalog({ onImportDraft }) {
  const [validators, setValidators] = useState([])
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
    const result = await installHubValidator({
      hub_uri: validator.hub_uri,
      install_local_models: false
    })
    setMessages(prev => ({
      ...prev,
      [validator.hub_uri]: result.status === 'installed'
        ? `${validator.name} installed.`
        : result.error || result.stderr || 'Install failed.'
    }))
    setInstalling('')
    await load()
  }

  const importDraft = async (validator) => {
    setCreating(validator.hub_uri)
    setMessages(prev => ({ ...prev, [validator.hub_uri]: '' }))
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
    setCreating('')
  }

  return (
    <section className="panel hub-catalog">
      <div className="panel-title-row">
        <h2>Guardrails Hub Validators</h2>
        <button type="button" className="refresh-button" disabled={refreshing} onClick={load}>
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
      {lastLoadedAt && <p className="muted">Last refreshed at {lastLoadedAt}</p>}
      <div className="hub-validator-list">
        {validators.map(validator => (
          <div className="hub-validator-row" key={validator.hub_uri}>
            <div>
              <strong>{validator.name}</strong>
              <span className={validator.installed ? 'install-status installed' : 'install-status missing'}>
                {validator.installed ? 'Installed' : 'Not installed'}
              </span>
              <p>{validator.description}</p>
              <code>{validator.hub_uri}</code>
              {messages[validator.hub_uri] && <p className="install-message">{messages[validator.hub_uri]}</p>}
            </div>
            <div className="button-row">
              <button
                type="button"
                className="ghost"
                disabled={validator.installed || installing === validator.hub_uri}
                onClick={() => runInstall(validator)}
              >
                {installing === validator.hub_uri ? 'Installing...' : 'Install'}
              </button>
              <button
                type="button"
                disabled={creating === validator.hub_uri}
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
