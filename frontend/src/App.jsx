import { useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import ResponsibleAIPanel from './components/ResponsibleAIPanel'
import SettingsPanel from './components/SettingsPanel'
import TracingStatus from './components/TracingStatus'
import PolicyManager from './components/PolicyManager'
import AuthStatus from './components/AuthStatus'
import { sendChat, fetchPolicy } from './api'

const defaultSettings = {
  mode: 'code',
  model: 'llama-3.3-70b-versatile',
  temperature: 0.2,
  max_tokens: 800,
  explain: true,
  verify: true
}

export default function App() {
  const [policy, setPolicy] = useState(null)
  const [messages, setMessages] = useState([])
  const [settings, setSettings] = useState(defaultSettings)
  const [loading, setLoading] = useState(false)
  const [user, setUser] = useState(null)
  const [screen, setScreen] = useState('chat')

  const canManagePolicies = user?.permissions?.manage_policies === true

  useEffect(() => {
    if (!canManagePolicies && screen === 'admin') {
      setScreen('chat')
    }
  }, [canManagePolicies, screen])

  useEffect(() => {
    fetchPolicy().then(data => setPolicy(data.policy)).catch(console.error)
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
        responsibleAI: result.responsible_ai 
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

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>Responsible AI Chat Agent</h1>
          <p>Ask the model questions and inspect responsible AI checks in code or framework mode.</p>
        </div>
        <div className="header-actions">
          <nav className="screen-tabs" aria-label="Main screens">
            <button
              type="button"
              className={screen === 'chat' ? 'active' : 'ghost'}
              onClick={() => setScreen('chat')}
            >
              Chat
            </button>
            {canManagePolicies && (
              <button
                type="button"
                className={screen === 'admin' ? 'active' : 'ghost'}
                onClick={() => setScreen('admin')}
              >
                Admin
              </button>
            )}
          </nav>
          <TracingStatus />
          <AuthStatus onUserChange={setUser} />
        </div>
      </header>
      {screen === 'admin' && canManagePolicies ? (
        <main className="admin-screen">
          <PolicyManager user={user} />
        </main>
      ) : (
        <main className="layout">
          <section className="chat-section">
            <ChatWindow messages={messages} onSend={handleSend} loading={loading} />
          </section>
          <aside className="sidebar">
            <SettingsPanel settings={settings} onChange={setSettings} />
            <ResponsibleAIPanel policy={policy} />
          </aside>
        </main>
      )}
    </div>
  )
}
