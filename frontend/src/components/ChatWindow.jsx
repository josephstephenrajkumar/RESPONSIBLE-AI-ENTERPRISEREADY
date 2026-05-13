import { useState } from 'react'
import MessageBubble from './MessageBubble'

export default function ChatWindow({ messages, onSend, loading }) {
  const [input, setInput] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!input.trim()) return
    await onSend(input.trim())
    setInput('')
  }

  return (
    <div className="chat-window">
      <div className="message-list">
        {messages.length === 0 && <div className="empty-state">Ask a responsible AI question to begin.</div>}
        {messages.map((message, index) => (
          <MessageBubble 
            key={index} 
            role={message.role} 
            text={message.text} 
            responsibleAI={message.responsibleAI} 
          />
        ))}
      </div>
      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type a question and press Enter..."
          disabled={loading}
        />
        <button type="submit" disabled={loading}>
          {loading ? 'Thinking...' : 'Send'}
        </button>
      </form>
    </div>
  )
}
