import { useEffect, useState } from 'react'

// Landing page for OAuth2 redirects (/oauth/callback). Relays the authorization code to the
// Studio window that opened the popup, then closes. Nothing is stored here.
export default function OAuthCallback() {
  const [state, setState] = useState('Finishing sign-in…')
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const payload = { type: 'rai-oauth-callback', code: params.get('code'), state: params.get('state'), error: params.get('error') || params.get('error_description') }
    if (window.opener) {
      window.opener.postMessage(payload, window.location.origin)
      setState(payload.error ? `Authorization failed: ${payload.error}` : 'Authorization received. You can close this window.')
      setTimeout(() => window.close(), 800)
    } else {
      setState('Open this page from the Workflow Studio connection dialog.')
    }
  }, [])
  return <div className="app-shell"><section className="panel"><h2>Connection</h2><p>{state}</p></section></div>
}
