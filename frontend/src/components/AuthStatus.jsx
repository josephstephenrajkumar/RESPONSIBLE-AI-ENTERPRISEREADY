import { useEffect, useState } from 'react'
import { clearAuthToken, fetchAuthConfig, fetchMe, getAuthToken, setAuthToken } from '../api'

function randomString() {
  const bytes = new Uint8Array(32)
  window.crypto.getRandomValues(bytes)
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

function base64Url(buffer) {
  const bytes = new Uint8Array(buffer)
  const binary = Array.from(bytes, byte => String.fromCharCode(byte)).join('')
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function sha256(value) {
  return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
}

function cleanCallbackUrl() {
  const url = new URL(window.location.href)
  url.searchParams.delete('code')
  url.searchParams.delete('state')
  window.history.replaceState({}, document.title, url.toString())
}

export default function AuthStatus({ onUserChange }) {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('Loading auth...')

  const loadUser = async () => {
    if (!getAuthToken()) {
      setUser(null)
      onUserChange?.(null)
      setStatus('Signed out')
      return
    }
    try {
      const currentUser = await fetchMe()
      setUser(currentUser)
      onUserChange?.(currentUser)
      setStatus('')
    } catch (error) {
      clearAuthToken()
      setUser(null)
      onUserChange?.(null)
      setStatus(error.message)
    }
  }

  useEffect(() => {
    async function initialize() {
      const nextConfig = await fetchAuthConfig()
      setConfig(nextConfig)

      const params = new URLSearchParams(window.location.search)
      const code = params.get('code')
      const state = params.get('state')
      const expectedState = window.sessionStorage.getItem('cognito_login_state')
      const verifier = window.sessionStorage.getItem('cognito_pkce_verifier')

      if (code && state && verifier && state === expectedState && nextConfig?.cognito?.domain) {
        const tokenResponse = await fetch(`${nextConfig.cognito.domain}/oauth2/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            grant_type: 'authorization_code',
            client_id: nextConfig.cognito.app_client_id,
            code,
            redirect_uri: window.location.origin + window.location.pathname,
            code_verifier: verifier
          })
        })
        const tokenPayload = await tokenResponse.json()
        if (!tokenResponse.ok) {
          throw new Error(tokenPayload.error_description || tokenPayload.error || 'Login failed')
        }
        setAuthToken(tokenPayload.id_token || tokenPayload.access_token)
        window.sessionStorage.removeItem('cognito_login_state')
        window.sessionStorage.removeItem('cognito_pkce_verifier')
        cleanCallbackUrl()
      }

      await loadUser()
    }

    initialize().catch(error => setStatus(error.message))
  }, [])

  const login = async () => {
    if (!config?.cognito?.domain || !config?.cognito?.app_client_id) {
      setStatus('Cognito Hosted UI is not configured.')
      return
    }
    const verifier = randomString()
    const state = randomString()
    const challenge = base64Url(await sha256(verifier))
    window.sessionStorage.setItem('cognito_pkce_verifier', verifier)
    window.sessionStorage.setItem('cognito_login_state', state)

    const authorizeUrl = new URL(`${config.cognito.domain}/oauth2/authorize`)
    authorizeUrl.searchParams.set('client_id', config.cognito.app_client_id)
    authorizeUrl.searchParams.set('response_type', config.cognito.response_type || 'code')
    authorizeUrl.searchParams.set('scope', (config.cognito.scopes || ['openid', 'email', 'profile']).join(' '))
    authorizeUrl.searchParams.set('redirect_uri', window.location.origin + window.location.pathname)
    authorizeUrl.searchParams.set('state', state)
    authorizeUrl.searchParams.set('code_challenge_method', 'S256')
    authorizeUrl.searchParams.set('code_challenge', challenge)
    window.location.assign(authorizeUrl.toString())
  }

  const logout = () => {
    clearAuthToken()
    setUser(null)
    onUserChange?.(null)
    setStatus('Signed out')
    if (config?.cognito?.domain && config?.cognito?.app_client_id) {
      const logoutUrl = new URL(`${config.cognito.domain}/logout`)
      logoutUrl.searchParams.set('client_id', config.cognito.app_client_id)
      logoutUrl.searchParams.set('logout_uri', window.location.origin + window.location.pathname)
      window.location.assign(logoutUrl.toString())
    }
  }

  return (
    <div className="auth-status">
      <div>
        <strong>{user?.email || user?.username || 'Guest'}</strong>
        <span>{status || (user?.permissions?.manage_policies ? 'Policy manager' : 'Signed in')}</span>
      </div>
      {user ? (
        <button type="button" className="ghost" onClick={logout}>Logout</button>
      ) : (
        <button type="button" onClick={login}>Login</button>
      )}
    </div>
  )
}
