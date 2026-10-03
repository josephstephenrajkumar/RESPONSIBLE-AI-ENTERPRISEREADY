import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import OAuthCallback from './OAuthCallback'
import './theme.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(window.location.pathname === '/oauth/callback' ? <OAuthCallback /> : <App />)
