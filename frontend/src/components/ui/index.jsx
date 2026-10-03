import { useState } from 'react'

// Shared UI primitives. Every new screen composes these so the portal has one look; the
// visual values come from theme.css tokens. Keep this module dependency-free.

export function Button({ variant = 'primary', size = 'md', type = 'button', className = '', children, ...rest }) {
  const cls = ['ui-btn', variant !== 'primary' ? variant : '', size === 'sm' ? 'ui-btn-sm' : '', className].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest}>{children}</button>
}

export function Panel({ title, subtitle, actions, children, className = '', ...rest }) {
  return (
    <section className={`panel ${className}`} {...rest}>
      {(title || actions) && (
        <div className="panel-title-row">
          <div>{title && <h2>{title}</h2>}{subtitle && <p className="muted">{subtitle}</p>}</div>
          {actions && <div className="button-row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Pill({ tone = 'neutral', children, className = '' }) {
  const toneClass = { ok: 'enabled', success: 'enabled', neutral: 'disabled', draft: 'status-draft', warn: 'status-approved', danger: 'severity-high', info: 'source-db' }[tone] || 'disabled'
  return <span className={`pill ${toneClass} ${className}`}>{children}</span>
}

export function Notice({ notice }) {
  if (!notice) return null
  return <div className={`notice ${notice.tone || 'ok'}`}>{notice.text}</div>
}

export function useNotice() {
  const [notice, setNotice] = useState(null)
  return {
    notice,
    ok: (text) => setNotice({ tone: 'ok', text }),
    warn: (text) => setNotice({ tone: 'warn', text }),
    fail: (err) => setNotice({ tone: 'error', text: typeof err === 'string' ? err : (err?.message || 'Request failed') }),
    clear: () => setNotice(null),
  }
}

export function Field({ label, hint, children, span, required }) {
  return (
    <label className={`ui-field ${span ? 'span-2' : ''}`}>
      {label && <span className="ui-field-label">{label}{required && <em className="ui-required">*</em>}</span>}
      {children}
      {hint && <small className="ui-field-hint">{hint}</small>}
    </label>
  )
}

export function Modal({ title, onClose, width = 'min(640px, 100%)', children, footer }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width }} onClick={(e) => e.stopPropagation()}>
        {title && <h3 style={{ marginTop: 0 }}>{title}</h3>}
        {children}
        {footer && <div className="button-row" style={{ marginTop: 16 }}>{footer}</div>}
      </div>
    </div>
  )
}

export function Tabs({ items, value, onChange, className = '' }) {
  return (
    <div className={`segmented ${className}`} role="tablist">
      {items.map(item => (
        <button key={item.id} type="button" role="tab" aria-selected={value === item.id} className={value === item.id ? 'active' : ''} onClick={() => onChange(item.id)}>{item.label}</button>
      ))}
    </div>
  )
}

export function EmptyRow({ colSpan, children }) {
  return <tr><td colSpan={colSpan} className="muted">{children}</td></tr>
}

export function JsonView({ value, maxHeight = 320 }) {
  return <pre className="json-view" style={{ maxHeight }}>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
}

export function KeyValue({ items }) {
  return (
    <div className="kv-grid">
      {items.map(([label, value]) => <div key={label}><span>{label}</span>{value}</div>)}
    </div>
  )
}
