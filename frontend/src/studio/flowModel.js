// Pure helpers for the Studio: step naming, validity, expressions and operation payloads.
// Shapes follow the engine's flow schemas (docs/ACTIVEPIECES_INTEGRATION.md, WORKFLOW_STUDIO_PLAN.md).

export const TEXT_TYPES = new Set(['SHORT_TEXT', 'LONG_TEXT', 'RICH_TEXT', 'NUMBER', 'DATE_TIME', 'COLOR', 'FILE', 'DATE_RANGE', 'CUSTOM'])
export const STATIC_SELECT_TYPES = new Set(['STATIC_DROPDOWN', 'STATIC_MULTI_SELECT_DROPDOWN'])
export const DYNAMIC_SELECT_TYPES = new Set(['DROPDOWN', 'MULTI_SELECT_DROPDOWN'])
export const AUTH_TYPES = new Set(['CUSTOM_AUTH', 'SECRET_TEXT', 'BASIC_AUTH', 'OAUTH2', 'OIDC'])

export const OPERATORS = [
  ['TEXT_CONTAINS', 'contains'], ['TEXT_DOES_NOT_CONTAIN', 'does not contain'], ['TEXT_EXACTLY_MATCHES', 'equals'], ['TEXT_DOES_NOT_EXACTLY_MATCH', 'does not equal'],
  ['TEXT_STARTS_WITH', 'starts with'], ['TEXT_ENDS_WITH', 'ends with'], ['NUMBER_IS_GREATER_THAN', 'number >'], ['NUMBER_IS_LESS_THAN', 'number <'],
  ['NUMBER_IS_EQUAL_TO', 'number ='], ['BOOLEAN_IS_TRUE', 'is true'], ['BOOLEAN_IS_FALSE', 'is false'], ['EXISTS', 'exists'], ['DOES_NOT_EXIST', 'does not exist'],
  ['LIST_IS_EMPTY', 'list is empty'], ['LIST_IS_NOT_EMPTY', 'list is not empty'],
]
export const SINGLE_VALUE_OPERATORS = new Set(['BOOLEAN_IS_TRUE', 'BOOLEAN_IS_FALSE', 'EXISTS', 'DOES_NOT_EXIST', 'LIST_IS_EMPTY', 'LIST_IS_NOT_EMPTY'])

export function nextStepName(steps) {
  const taken = new Set(steps.map(s => s.name))
  let n = 1
  while (taken.has(`step_${n}`)) n += 1
  return `step_${n}`
}

export function tilde(version) {
  return !version ? '' : (version.startsWith('~') || version.startsWith('^') ? version : `~${version}`)
}

export function isEmptyValue(value) {
  if (value === undefined || value === null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value).length === 0
  return false
}

// A step is valid when every required, user-facing property has a value and, when the
// piece needs a connection, one is selected. Mirrors what the engine's own UI checks.
export function computeValid(props, input, needsAuth) {
  if (needsAuth && isEmptyValue(input.auth)) return false
  return Object.entries(props || {}).every(([key, prop]) => {
    if (!prop?.required) return true
    if (prop.type === 'MARKDOWN' || prop.type === 'DYNAMIC') return true
    return !isEmptyValue(input[key])
  })
}

export function manualSettings(input) {
  return Object.fromEntries(Object.keys(input || {}).map(key => [key, { type: 'MANUAL' }]))
}

export function coerceValue(prop, raw) {
  if (raw === undefined || raw === null) return raw
  if (prop?.type === 'NUMBER' && typeof raw === 'string' && raw.trim() !== '' && !raw.includes('{{') && !Number.isNaN(Number(raw))) return Number(raw)
  if (prop?.type === 'CHECKBOX') return Boolean(raw)
  return raw
}

// Engine 0.92 addresses a step's result as {{step['output']...}}; the loop step exposes
// {{loop['output']['item']}} and ['index']. Flows imported with an older schema are migrated
// by the engine, flows edited through the API must use this format directly.
export function expression(stepName, path) {
  const parts = !path ? [] : Array.isArray(path) ? path : String(path).split('.')
  return `{{${stepName}['output']${parts.map(p => (/^\d+$/.test(p) ? `[${p}]` : `['${p}']`)).join('')}}}`
}

// Flatten an object into dotted paths (depth-limited) for the data picker.
export function samplePaths(value, prefix = '', depth = 0, out = []) {
  if (depth > 3 || out.length > 200) return out
  if (Array.isArray(value)) {
    value.slice(0, 5).forEach((v, i) => samplePaths(v, prefix ? `${prefix}.${i}` : String(i), depth + 1, out))
  } else if (value && typeof value === 'object') {
    Object.entries(value).forEach(([k, v]) => {
      const path = prefix ? `${prefix}.${k}` : k
      out.push({ path, preview: previewValue(v) })
      samplePaths(v, path, depth + 1, out)
    })
  }
  return out
}

export function previewValue(v) {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'object') return Array.isArray(v) ? `[${v.length}]` : '{…}'
  const s = String(v)
  return s.length > 48 ? s.slice(0, 45) + '…' : s
}

export function pieceAuthOptions(piece) {
  const auth = piece?.auth
  if (!auth) return []
  return Array.isArray(auth) ? auth : [auth]
}

export function pieceShortName(name) {
  return String(name || '').split('/').pop().replace(/^piece-/, '')
}

export function newPieceAction({ name, piece, actionName, action }) {
  return {
    name, displayName: action?.displayName || actionName, type: 'PIECE', valid: false,
    settings: { pieceName: piece.name, pieceVersion: tilde(piece.version), actionName, input: {}, propertySettings: {}, errorHandlingOptions: { continueOnFailure: { value: false }, retryOnFailure: { value: false } } },
  }
}

export function newCodeAction(name) {
  return {
    name, displayName: 'Code', type: 'CODE', valid: true,
    settings: { sourceCode: { code: 'export const code = async (inputs) => {\n  return { ok: true, inputs };\n};\n', packageJson: '{}' }, input: {}, errorHandlingOptions: { continueOnFailure: { value: false }, retryOnFailure: { value: false } } },
  }
}

export function newRouterAction(name) {
  return {
    name, displayName: 'Router', type: 'ROUTER', valid: true,
    settings: {
      branches: [
        { branchName: 'Branch 1', branchType: 'CONDITION', conditions: [[{ firstValue: '', secondValue: '', operator: 'TEXT_CONTAINS', caseSensitive: false }]] },
        { branchName: 'Otherwise', branchType: 'FALLBACK' },
      ],
      executionType: 'EXECUTE_FIRST_MATCH',
    },
  }
}

export function newLoopAction(name) {
  return { name, displayName: 'Loop on items', type: 'LOOP_ON_ITEMS', valid: false, settings: { items: '' } }
}

export function stepToUpdateRequest(step) {
  // Rebuild the engine action/trigger object from the flattened editor row.
  const base = { name: step.name, displayName: step.displayName, valid: step.valid, type: step.type }
  if (step.type === 'PIECE') {
    return { ...base, settings: { pieceName: step.pieceName, pieceVersion: step.pieceVersion, actionName: step.actionName, input: step.input || {}, propertySettings: manualSettings(step.input), errorHandlingOptions: step.errorHandlingOptions || {} } }
  }
  if (step.type === 'PIECE_TRIGGER') {
    return { ...base, settings: { pieceName: step.pieceName, pieceVersion: step.pieceVersion, triggerName: step.actionName, input: step.input || {}, propertySettings: manualSettings(step.input) } }
  }
  if (step.type === 'CODE') {
    return { ...base, settings: { sourceCode: step.sourceCode, input: step.input || {}, errorHandlingOptions: step.errorHandlingOptions || {} } }
  }
  if (step.type === 'ROUTER') {
    return { ...base, settings: { branches: step.branches, executionType: step.executionType || 'EXECUTE_FIRST_MATCH' } }
  }
  if (step.type === 'LOOP_ON_ITEMS') {
    return { ...base, settings: { items: step.items || '' } }
  }
  return base
}
