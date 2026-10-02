import { useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import ResponsibleAIPanel from './components/ResponsibleAIPanel'
import SettingsPanel from './components/SettingsPanel'
import TracingStatus from './components/TracingStatus'
import PolicyManager from './components/PolicyManager'
import EvaluationDashboard from './components/EvaluationDashboard'
import GuardrailsDashboard from './components/GuardrailsDashboard'
import FinOpsDashboard from './components/FinOpsDashboard'
import AIOpsDashboard from './components/AIOpsDashboard'
import AuthStatus from './components/AuthStatus'
import ProxyManager from './components/ProxyManager'
import { sendChat, fetchPolicy } from './api'

// `model` has no client-side default: it must come from the backend's /policy
// endpoint (Settings.LLM_DEFAULT_MODEL, sourced from backend/.env) so there is a
// single source of truth for which model is configured, instead of a value
// hardcoded here that can drift out of sync with the backend's configuration.
const defaultSettings = {
  mode: 'code',
  model: '',
  temperature: 0.2,
  max_tokens: 800,
  explain: true,
  verify: true
}

// Screen -> permission flag from /auth/me. Chat is always available.
const SCREENS = [
  { id: 'chat', label: 'Chat', permission: null },
  { id: 'dashboards', label: 'Responsible AI', permission: 'manage_policies' },
  { id: 'proxy', label: 'Proxy Manager', permission: 'manage_models' },
  { id: 'finops', label: 'FinOps', permission: 'view_finops' },
  { id: 'aiops', label: 'AIOps', permission: 'view_aiops' },
  { id: 'configuration', label: 'Configuration', permission: 'manage_policies' },
]

export default function App() {
  const [policy, setPolicy] = useState(null)
  const [messages, setMessages] = useState([])
  const [settings, setSettings] = useState(defaultSettings)
  const [loading, setLoading] = useState(false)
  const [user, setUser] = useState(null)
  const [screen, setScreen] = useState('chat')

  const permissions = user?.permissions || {}
  const canView = (screenDef) => !screenDef.permission || permissions[screenDef.permission] === true
  const visibleScreens = SCREENS.filter(canView)

  useEffect(() => {
    const current = SCREENS.find(item => item.id === screen)
    if (current && !canView(current)) {
      setScreen('chat')
    }
  }, [user, screen])

  useEffect(() => {
    fetchPolicy().then(data => {
      setPolicy(data.policy)
      // Sync the chat model default from the backend's configured policy
      // (backend/.env's LLM_DEFAULT_MODEL) rather than a hardcoded frontend value.
      if (data.policy?.model) {
        setSettings(prev => (prev.model ? prev : { ...prev, model: data.policy.model }))
      }
    }).catch(console.error)
  }, [])

  const handleSend = async (message) => {
    const userMessage = { role: 'user', text: message }
    setMessages(prev => [...prev, userMessage])
    setLoading(true)
    const payload = { ...settings, message }
    try {
      const result = await sendChat(payload)
      const assistantMessage = {
        role: 'assistant',
        text: result.answer || 'No answer returned.',
        responsibleAI: result.responsible_ai,
        metadata: result.metadata
      }
      setMessages(prev => [...prev, assistantMessage])
      return result
    } catch (error) {
      const errorMessage = {
        role: 'assistant',
        text: `Request failed: ${error.message}`,
        isError: true
      }
      setMessages(prev => [...prev, errorMessage])
      return null
    } finally {
      setLoading(false)
    }
  }

  const renderScreen = () => {
    switch (screen) {
      case 'dashboards':
        return (
          <main className="admin-screen">
            <PolicyManager user={user} view="dashboards" />
            <GuardrailsDashboard />
            <EvaluationDashboard />
          </main>
        )
      case 'finops':
        return (
          <main className="admin-screen">
            <FinOpsDashboard />
          </main>
        )
      case 'aiops':
        return (
          <main className="admin-screen">
            <AIOpsDashboard />
          </main>
        )
      case 'proxy':
        return (
          <main className="admin-screen">
            <ProxyManager canManage={permissions.manage_models === true} />
          </main>
        )
      case 'configuration':
        return (
          <main className="admin-screen">
            <PolicyManager user={user} view="configuration" />
          </main>
        )
      default:
        return (
          <main className="layout">
            <section className="chat-section">
              <ChatWindow messages={messages} onSend={handleSend} loading={loading} />
            </section>
            <aside className="sidebar">
              <SettingsPanel settings={settings} onChange={setSettings} />
              <ResponsibleAIPanel policy={policy} />
            </aside>
          </main>
        )
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>Responsible AI Chat Agent</h1>
          <p>Ask the model questions and inspect responsible AI checks in code or framework mode.</p>
        </div>
        <div className="header-actions">
          <nav className="screen-tabs" aria-label="Main screens">
            {visibleScreens.map(item => (
              <button
                key={item.id}
                type="button"
                className={screen === item.id ? 'active' : 'ghost'}
                onClick={() => setScreen(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <TracingStatus />
          <AuthStatus onUserChange={setUser} />
        </div>
      </header>
      {renderScreen()}
    </div>
  )
}
