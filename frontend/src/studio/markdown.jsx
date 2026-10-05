// Minimal markdown renderer for piece help texts (MARKDOWN properties and descriptions).
// Supports fenced code blocks, paragraphs, bullet lists, **bold**, `code` and [links](url).
// No dependency: the texts are short and come from the engine's piece metadata.

function inline(text, keyBase) {
  const out = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
  let last = 0, m, i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) out.push(<strong key={`${keyBase}-${i++}`}>{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) out.push(<code key={`${keyBase}-${i++}`}>{tok.slice(1, -1)}</code>)
    else { const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok); out.push(<a key={`${keyBase}-${i++}`} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>) }
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let para = [], list = null, code = null, k = 0
  const flush = () => {
    if (para.length) { blocks.push(<p key={k++}>{para.map((l, i) => <span key={i}>{inline(l, `${k}-${i}`)}{i < para.length - 1 ? <br /> : null}</span>)}</p>); para = [] }
    if (list) { blocks.push(<ul key={k++}>{list.map((l, i) => <li key={i}>{inline(l, `${k}-${i}`)}</li>)}</ul>); list = null }
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (code !== null) {
      if (line.trim().startsWith('```')) { blocks.push(<pre key={k++} className="md-code">{code.join('\n')}</pre>); code = null } else code.push(raw)
      continue
    }
    if (line.trim().startsWith('```')) { flush(); code = []; continue }
    if (/^\s*[-*] /.test(line)) { if (para.length) flush(); (list = list || []).push(line.replace(/^\s*[-*] /, '')); continue }
    if (line.trim() === '') { flush(); continue }
    if (list) flush()
    para.push(line)
  }
  if (code !== null) blocks.push(<pre key={k++} className="md-code">{code.join('\n')}</pre>)
  flush()
  return blocks
}

// Engine help texts carry {{variables}} that the engine's own UI fills in (its public chat,
// form and webhook URLs). The Studio substitutes what applies to the portal and marks the rest.
export function substituteVariables(text, variables = {}) {
  return String(text || '').replace(/<br\s*\/?>/gi, '\n').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (whole, name) => (name in variables ? String(variables[name]) : whole))
}

export default function Markdown({ text, variables, className = 'prop-markdown' }) {
  return <div className={className}>{renderMarkdown(substituteVariables(text, variables))}</div>
}
