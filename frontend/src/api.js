const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const TOKEN_KEY = 'enterprise_auth_token'
const REFRESH_KEY = 'enterprise_refresh_token'
const AUTH_CONFIG_KEY = 'enterprise_auth_config'

// ---- Session handling --------------------------------------------------------
// Cognito ID tokens expire after one hour. We keep the refresh token from the
// hosted-UI code exchange, refresh proactively when the ID token is close to
// expiry, retry once on a 401, and announce an unrecoverable expiry so the UI
// can ask for a fresh login instead of failing every call silently.

const SESSION_EXPIRED_EVENT = 'enterprise-session-expired'
let refreshPromise = null

function decodeJwtPayload(token) {
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  } catch {
    return null
  }
}

export function tokenExpiresInSeconds(token = getAuthToken()) {
  const payload = token ? decodeJwtPayload(token) : null
  if (!payload?.exp) return null
  return Math.round(payload.exp - Date.now() / 1000)
}

export function getRefreshToken() {
  return window.localStorage.getItem(REFRESH_KEY)
}

export function setRefreshToken(token) {
  if (token) window.localStorage.setItem(REFRESH_KEY, token)
}

export function rememberAuthConfig(config) {
  try { window.localStorage.setItem(AUTH_CONFIG_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

function storedAuthConfig() {
  try { return JSON.parse(window.localStorage.getItem(AUTH_CONFIG_KEY) || 'null') } catch { return null }
}

export function onSessionExpired(handler) {
  window.addEventListener(SESSION_EXPIRED_EVENT, handler)
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handler)
}

function announceSessionExpired(reason) {
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { reason } }))
}

export async function refreshSession() {
  const refreshToken = getRefreshToken()
  const config = storedAuthConfig()
  if (!refreshToken || !config?.cognito?.domain || !config?.cognito?.app_client_id) return false
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${config.cognito.domain}/oauth2/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ grant_type: 'refresh_token', client_id: config.cognito.app_client_id, refresh_token: refreshToken })
        })
        const payload = await response.json()
        if (!response.ok || !(payload.id_token || payload.access_token)) return false
        setAuthToken(payload.id_token || payload.access_token)
        return true
      } catch {
        return false
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

async function ensureFreshToken() {
  const remaining = tokenExpiresInSeconds()
  if (remaining !== null && remaining < 120 && getRefreshToken()) {
    await refreshSession()
  }
}

function authHeaders() {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function jsonHeaders() {
  return { 'Content-Type': 'application/json', ...authHeaders() }
}

// All API calls go through here: refresh before expiry, retry once after a 401
// by refreshing, and surface an unrecoverable expiry to the app shell.
async function fetchWithAuth(url, options = {}, retry = true) {
  await ensureFreshToken()
  const headers = { ...(options.headers || {}), ...authHeaders() }
  const response = await fetch(url, { ...options, headers })
  if (response.status === 401 && retry && getRefreshToken()) {
    const refreshed = await refreshSession()
    if (refreshed) return fetchWithAuth(url, options, false)
  }
  if (response.status === 401 && getAuthToken() && getAuthToken() !== 'local-dev-auto-login') {
    announceSessionExpired('Your session has expired. Please sign in again.')
  }
  return response
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json')
    ? await response.json()
    : { detail: await response.text() }

  if (!response.ok) {
    const detail = data?.detail || data?.message || `Request failed with HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return data
}

export async function sendChat(payload) {
  const response = await fetchWithAuth(`${API_BASE}/chat`, {
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
  window.localStorage.removeItem(REFRESH_KEY)
}

export async function fetchAuthConfig() {
  const response = await fetch(`${API_BASE}/auth/config`)
  const config = await parseResponse(response)
  rememberAuthConfig(config)
  return config
}

export async function fetchMe() {
  const response = await fetchWithAuth(`${API_BASE}/auth/me`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchPolicy() {
  const response = await fetchWithAuth(`${API_BASE}/policy`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchObservability() {
  const response = await fetchWithAuth(`${API_BASE}/observability`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchPolicies() {
  const response = await fetchWithAuth(`${API_BASE}/policies`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function createPolicy(payload) {
  const response = await fetchWithAuth(`${API_BASE}/policies`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function importHubPolicy(payload) {
  const response = await fetchWithAuth(`${API_BASE}/policies/import/hub`, {
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
  const response = await fetchWithAuth(`${API_BASE}/policies/hub/validators`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function installHubValidator(payload) {
  const response = await fetchWithAuth(`${API_BASE}/policies/hub/validators/install`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function updatePolicy(id, payload) {
  const response = await fetchWithAuth(`${API_BASE}/policies/${id}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function deletePolicy(id) {
  const response = await fetchWithAuth(`${API_BASE}/policies/${id}`, { method: 'DELETE', headers: authHeaders() })
  return parseResponse(response)
}

export async function approvePolicy(id) {
  const response = await fetchWithAuth(`${API_BASE}/policies/${id}/approve`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ actor: 'policy-manager' })
  })
  return parseResponse(response)
}

export async function activatePolicy(id) {
  const response = await fetchWithAuth(`${API_BASE}/policies/${id}/activate`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ actor: 'policy-manager' })
  })
  return parseResponse(response)
}

export async function reloadPolicies() {
  const response = await fetchWithAuth(`${API_BASE}/policies/reload`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function testPolicies(message) {
  const response = await fetchWithAuth(`${API_BASE}/policies/test`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message })
  })
  return parseResponse(response)
}

export async function fetchMyAudit() {
  const response = await fetchWithAuth(`${API_BASE}/audit/me`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchGuardrailReport(userId = '') {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  const response = await fetchWithAuth(`${API_BASE}/reports/guardrails${query}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchEvaluationReport(limit = 200) {
  const response = await fetchWithAuth(`${API_BASE}/reports/evaluations?limit=${limit}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchSafetyReport(limit = 200) {
  const response = await fetchWithAuth(`${API_BASE}/reports/safety?limit=${limit}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchFinopsReport(days = 30) {
  const response = await fetchWithAuth(`${API_BASE}/reports/finops?days=${days}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchAiopsReport(hours = 24) {
  const response = await fetchWithAuth(`${API_BASE}/reports/aiops?hours=${hours}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchGatewayHealth() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/health`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchGatewayModels() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/models`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchModelCatalog() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchAvailableModels(provider, query = '') {
  const params = query ? `?q=${encodeURIComponent(query)}` : ''
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/providers/${encodeURIComponent(provider)}/available${params}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function addCatalogModel(payload) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/models`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  })
  return parseResponse(response)
}

export async function deleteCatalogModel(modelId) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/models/${encodeURIComponent(modelId)}`, { method: 'DELETE', headers: authHeaders() })
  return parseResponse(response)
}

export async function testCatalogModel(modelName) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/models/${modelName}/test`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

// ---- Proxy Manager -----------------------------------------------------------
export async function fetchProxyOverview() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/admin/overview`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchGatewaySettings() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/settings`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function updateGatewaySetting(key, value) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/settings`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ key, value }) })
  return parseResponse(response)
}

export async function toggleProvider(provider, action) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/providers/${encodeURIComponent(provider)}/${action}`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function storeProviderCredential(provider, apiKey, extra) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/providers/${encodeURIComponent(provider)}/credential`, {
    method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ api_key: apiKey, extra: extra || null })
  })
  return parseResponse(response)
}

export async function deleteProviderCredential(provider) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/providers/${encodeURIComponent(provider)}/credential`, { method: 'DELETE', headers: authHeaders() })
  return parseResponse(response)
}

export async function toggleModel(modelName, action) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/catalog/models/${modelName}/${action}`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

// Governed passthrough to LiteLLM's management API (allow-listed on the gateway).
export async function litellmAdmin(method, path, body, params) {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  const response = await fetchWithAuth(`${API_BASE}/gateway/admin/litellm/${path.replace(/^\//, '')}${query}`, {
    method,
    headers: body !== undefined ? jsonHeaders() : authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined
  })
  return parseResponse(response)
}

export async function fetchLitellmConfig() {
  const response = await fetchWithAuth(`${API_BASE}/gateway/admin/litellm-config`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function seedLitellmDefaults(force = false) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/admin/litellm-config/seed?force=${force ? 'true' : 'false'}`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function rotateLitellmKey(token) {
  const response = await fetchWithAuth(`${API_BASE}/gateway/admin/litellm-keys/${encodeURIComponent(token)}/rotate`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

// ---- Workflow Apps (Activepieces control plane; docs/ACTIVEPIECES_INTEGRATION.md) ----
export async function fetchWorkflowStatus() {
  const response = await fetchWithAuth(`${API_BASE}/workflows/status`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function bootstrapWorkflows(force = false) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/bootstrap?force=${force ? 'true' : 'false'}`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchWorkflowApps() {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function createWorkflowApp(payload) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(payload) })
  return parseResponse(response)
}

export async function publishWorkflowApp(appId) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/publish`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

export async function setWorkflowAppStatus(appId, enabled) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/status`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ enabled }) })
  return parseResponse(response)
}

export async function deleteWorkflowApp(appId) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}`, { method: 'DELETE', headers: authHeaders() })
  return parseResponse(response)
}

export async function fetchWorkflowAppRuns(appId, limit = 20) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/runs?limit=${limit}`, { headers: authHeaders() })
  return parseResponse(response)
}

export async function chatWithWorkflowApp(appId, message, sessionId) {
  const response = await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/chat`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ message, session_id: sessionId || '' }) })
  return parseResponse(response)
}

export async function syncWorkflowUsage() {
  const response = await fetchWithAuth(`${API_BASE}/workflows/usage/sync`, { method: 'POST', headers: authHeaders() })
  return parseResponse(response)
}

// ---- Workflow Studio (our own builder over the engine API through the gateway) ----
const studioUrl = (appId, suffix) => `${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/studio${suffix}`
export async function fetchStudioPieces(search = '', all = false) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/studio/pieces?search=${encodeURIComponent(search)}${all ? '&all=true' : ''}`, { headers: authHeaders() })) }
export async function fetchStudioStepSample(appId, stepName, kind = 'OUTPUT') { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/studio/steps/${encodeURIComponent(stepName)}/sample?kind=${kind}`, { headers: authHeaders() })) }
export async function fetchStudioPiece(name) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/studio/pieces/${name}`, { headers: authHeaders() })) }
export async function fetchStudioCatalogue() { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/studio/catalogue`, { headers: authHeaders() })) }
export async function updateStudioCatalogue(pieces) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/studio/catalogue`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ pieces }) })) }
export async function fetchStudioFlow(appId) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/flow'), { headers: authHeaders() })) }
export async function applyStudioOperation(appId, type, request) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/operations'), { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ type, request }) })) }
export async function fetchStudioOptions(appId, body) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/options'), { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) })) }
export async function fetchStudioVersions(appId) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/versions'), { headers: authHeaders() })) }
export async function fetchStudioConnections(appId) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/connections'), { headers: authHeaders() })) }
export async function createStudioConnection(appId, body) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/connections'), { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) })) }
export async function deleteStudioConnection(appId, connectionId) { return parseResponse(await fetchWithAuth(studioUrl(appId, `/connections/${encodeURIComponent(connectionId)}`), { method: 'DELETE', headers: authHeaders() })) }
export async function studioOAuthUrl(appId, body) { return parseResponse(await fetchWithAuth(studioUrl(appId, '/oauth2/authorization-url'), { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) })) }
export async function testStudioStep(appId, stepName) { return parseResponse(await fetchWithAuth(studioUrl(appId, `/steps/${encodeURIComponent(stepName)}/test`), { method: 'POST', headers: authHeaders() })) }
export async function fetchStudioRun(appId, runId) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/runs/${encodeURIComponent(runId)}`, { headers: authHeaders() })) }
export async function retryStudioRun(appId, runId, strategy = 'ON_LATEST_VERSION') { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/apps/${encodeURIComponent(appId)}/runs/${encodeURIComponent(runId)}/retry?strategy=${strategy}`, { method: 'POST', headers: authHeaders() })) }

// ---- MCP publishing (workflow apps exposed as MCP tools for external agents) ----
export async function fetchMcpInfo() { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/mcp`, { headers: authHeaders() })) }
export async function issueMcpKey(name) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/mcp/keys`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ name }) })) }
export async function revokeMcpKey(keyId) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/mcp/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE', headers: authHeaders() })) }
export async function updateMcpTool(appId, body) { return parseResponse(await fetchWithAuth(`${API_BASE}/workflows/mcp/tools/${encodeURIComponent(appId)}`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify(body) })) }

