const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const TOKEN_KEY = 'enterprise_auth_token'

function authHeaders() {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function jsonHeaders() {
  return { 'Content-Type': 'application/json', ...authHeaders() }
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json')
    ? await response.json()
    : { detail: await response.text() }

  if (!response.ok) {
    const detail = data?.detail || data?.message || `Request failed with HTTP ${response.status}`
    throw new Error(detail)
  }

  return data
}

export async function sendChat(payload) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export function getAuthToken() {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setAuthToken(token) {
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token)
  }
}

export function clearAuthToken() {
  window.localStorage.removeItem(TOKEN_KEY)
}

export async function fetchAuthConfig() {
  const response = await fetch(`${API_BASE}/auth/config`)
  return parseResponse(response)
}

export async function fetchMe() {
  const response = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchPolicy() {
  const response = await fetch(`${API_BASE}/policy`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchObservability() {
  const response = await fetch(`${API_BASE}/observability`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchPolicies() {
  const response = await fetch(`${API_BASE}/policies`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function createPolicy(payload) {
  const response = await fetch(`${API_BASE}/policies`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function importHubPolicy(payload) {
  const response = await fetch(`${API_BASE}/policies/import/hub`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({
      name: payload.name,
      category: payload.category,
      severity: payload.severity,
      description: payload.description,
      source: payload.source,
      hub_validator: payload.hub_validators[0]
    })
  })
  return parseResponse(response)
}

export async function fetchHubValidators() {
  const response = await fetch(`${API_BASE}/policies/hub/validators`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function installHubValidator(payload) {
  const response = await fetch(`${API_BASE}/policies/hub/validators/install`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function updatePolicy(id, payload) {
  const response = await fetch(`${API_BASE}/policies/${id}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function deletePolicy(id) {
  const response = await fetch(`${API_BASE}/policies/${id}`, { method: 'DELETE', headers: authHeaders() })
  return parseResponse(response)
}

export async function approvePolicy(id) {
  const response = await fetch(`${API_BASE}/policies/${id}/approve`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ actor: 'policy-manager' })
  })
  return parseResponse(response)
}

export async function activatePolicy(id) {
  const response = await fetch(`${API_BASE}/policies/${id}/activate`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ actor: 'policy-manager' })
  })
  return parseResponse(response)
}

export async function reloadPolicies() {
  const response = await fetch(`${API_BASE}/policies/reload`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function testPolicies(message) {
  const response = await fetch(`${API_BASE}/policies/test`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message })
  })
  return parseResponse(response)
}

export async function fetchMyAudit() {
  const response = await fetch(`${API_BASE}/audit/me`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchGuardrailReport(userId = '') {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  const response = await fetch(`${API_BASE}/reports/guardrails${query}`, { headers: authHeaders() })
  return parseResponse(response)
}
