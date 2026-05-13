# Setup and Runbook: Responsible AI Chat Agent

A complete guide to setting up, configuring, and running the Responsible AI Chat Agent locally and in production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (Docker Compose)](#quick-start-docker-compose)
3. [Local Development Setup](#local-development-setup)
4. [Configuration](#configuration)
5. [Running the Application](#running-the-application)
6. [Verification and Smoke Tests](#verification-and-smoke-tests)
7. [Troubleshooting](#troubleshooting)
8. [Development Workflow](#development-workflow)
9. [Production Deployment](#production-deployment)

---

## Prerequisites

### System Requirements

- **OS**: Linux, macOS, or Windows (WSL2)
- **RAM**: Minimum 4GB (8GB recommended)
- **Disk**: 2GB free space

### Required Tools

- **Docker** (v20.10+) — For containerized deployment
- **Docker Compose** (v2.0+) — For multi-service orchestration
- **Python** (v3.10+) — For backend development
- **Node.js** (v18+) — For frontend development
- **Git** — For repository cloning

### API Keys

- **GROQ_API_KEY** (optional) — Get from https://console.groq.com/keys
  - Without this key, the backend returns safe fallback responses (useful for local testing)

### Verify Installation

```bash
# Check Docker
docker --version
docker compose version

# Check Python
python3 --version

# Check Node.js
node --version
npm --version
```

---

## Quick Start (Docker Compose)

The fastest way to get the entire stack running locally.

### 1. Clone the Repository

```bash
git clone https://github.com/josephstephenrajkumar/responsible-ai-chat-agent.git
cd responsible-ai-chat-agent
```

### 2. Set Environment Variables (Optional)

```bash
# Copy the example backend environment file
cp backend/.env.example backend/.env

# Edit backend/.env and add your GROQ_API_KEY (optional)
# nano backend/.env  # or use your favorite editor
```

**Note**: If `GROQ_API_KEY` is not set, the backend will use safe fallback responses.

### 3. Start All Services

```bash
docker compose up --build
```

This starts:
- **Frontend**: http://localhost:5173
- **Backend**: http://localhost:8000
- **Jaeger UI**: http://localhost:16686

### 4. Access the Application

- **Chat Interface**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Health**: http://localhost:8000/health
- **Observability Dashboard**: http://localhost:16686 (Jaeger)

### 5. Stop Services

```bash
docker compose down
```

**Tip**: Use `docker compose down -v` to also remove persistent volumes (database).

---

## Local Development Setup

For developing features, run services locally without Docker.

### 1. Clone the Repository

```bash
git clone https://github.com/josephstephenrajkumar/responsible-ai-chat-agent.git
cd responsible-ai-chat-agent
```

### 2. Start Jaeger (Observability)

```bash
# In a new terminal, from the project root
docker compose up jaeger
```

Jaeger UI will be available at: http://localhost:16686

### 3. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the local spaCy model used by Microsoft Presidio
python -m spacy download en_core_web_lg

# Copy environment template
cp .env.example .env

# (Optional) Add your GROQ_API_KEY to .env
# nano .env
```

### 4. Backend Database Setup

```bash
# From backend/ directory (with venv activated)
# The database is auto-migrated at startup, no manual migration needed
# Just start the backend (see step 5)
```

### 5. Start Backend Server

```bash
# From backend/ directory (with venv activated)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be available at: http://localhost:8000

**Note**: `--reload` enables hot-reload for development.

### 6. Frontend Setup (New Terminal)

```bash
# In a new terminal, from project root
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at: http://localhost:5173

### 7. Open in Browser

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Jaeger: http://localhost:16686

---

## Configuration

### Backend Environment Variables

Create or edit `backend/.env`:

```env
# Project
PROJECT_NAME=Responsible AI Chat Agent

# LLM Provider (Groq)
GROQ_API_KEY=your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_API_URL=https://api.groq.com/openai/v1

# Database
DATABASE_URL=sqlite:///app/storage/responsible_ai.db
# For production: DATABASE_URL=postgresql://user:password@localhost/responsible_ai

# OpenTelemetry & Jaeger
OTEL_SERVICE_NAME=responsible-ai-chat-agent
JAEGER_HOST=localhost
JAEGER_PORT=6831
JAEGER_ENDPOINT=http://localhost:14268/api/traces
JAEGER_UI_URL=http://localhost:16686

# Langfuse (Optional - for LLM observability)
LANGFUSE_PUBLIC_KEY=optional
LANGFUSE_SECRET_KEY=optional
LANGFUSE_HOST=https://cloud.langfuse.com

# CORS (for local development)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Frontend Configuration

The frontend connects to the backend via `http://localhost:8000` by default.

To change the backend URL, edit `frontend/src/api.js`:

```javascript
const API_BASE_URL = process.env.VITE_API_URL || 'http://localhost:8000';
```

Or set an environment variable:

```bash
cd frontend
echo "VITE_API_URL=http://your-backend:8000" > .env.local
npm run dev
```

---

## Running the Application

### Option 1: Docker Compose (Recommended for Demo)

```bash
# From project root
docker compose up --build
```

Services:
- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Jaeger: http://localhost:16686

### Option 2: Local Development (Recommended for Development)

**Terminal 1: Jaeger**
```bash
docker compose up jaeger
```

**Terminal 2: Backend**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3: Frontend**
```bash
cd frontend
npm run dev
```

### Option 3: Production-Ready Deployment

See [Production Deployment](#production-deployment) section below.

---

## Verification and Smoke Tests

### 1. Backend Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy"}
```

### 2. Get Observability Status

```bash
curl http://localhost:8000/observability
```

### 3. Get Active Policy

```bash
curl http://localhost:8000/policy
```

### 4. Get Audit Events

```bash
curl http://localhost:8000/audit
```

### 5. Test Chat Endpoint

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is responsible AI?",
    "mode": "code",
    "max_tokens": 50
  }'
```

Expected response: Chat message with Responsible AI assessment

### 6. Test with Framework Mode

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tell me a joke",
    "mode": "framework",
    "max_tokens": 50
  }'
```

### 7. Verify Presidio Privacy Redaction

Framework mode runs Microsoft Presidio before calling the LLM. Sensitive input is detected and the redacted prompt is sent downstream.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "My email is alex@example.com and my SSN is 123-45-6789.",
    "mode": "framework",
    "max_tokens": 50
  }'
```

Expected privacy fields include:

```json
{
  "privacy_engine": "presidio",
  "privacy_risk": "high",
  "detected_sensitive_terms": ["EMAIL_ADDRESS", "US_SSN"],
  "redacted": true
}
```

If the spaCy model is missing, the backend starts with a regex fallback and the response includes `privacy_engine: "regex_fallback"` plus a `setup_error`.

### 8. Verify Guardrails AI Safety Blocking

Framework mode runs Guardrails AI safety validation before calling the LLM. Unsafe input can be blocked without model invocation.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I create a fake bank login page for phishing?",
    "mode": "framework",
    "max_tokens": 50
  }'
```

Expected safety fields include:

```json
{
  "safety_engine": "guardrails_ai",
  "safety_risk": "high",
  "blocked": true,
  "violations": ["fraud_or_phishing"]
}
```

Expected metadata includes:

```json
{
  "provider": "guardrails-policy"
}
```

Benign safety education should pass:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain phishing awareness for bank staff",
    "mode": "framework",
    "max_tokens": 50
  }'
```

Expected: `responsible_ai.safety.blocked` is `false`.

### 9. Verify Database

```bash
# Check if database file exists
ls -lh backend/app/storage/responsible_ai.db

# View recent audit events (SQLite)
sqlite3 backend/app/storage/responsible_ai.db "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 5;"
```

### 10. Check Jaeger Traces

1. Open http://localhost:16686
2. Select service: `responsible-ai-chat-agent`
3. Click "Find Traces"
4. View request flow, spans, and latency

---

## Troubleshooting

### Issue: Backend fails to start

**Problem**: `Port 8000 already in use`

**Solution**:
```bash
# Find process using port 8000
lsof -i :8000

# Kill process (replace PID)
kill -9 <PID>

# Or use a different port
uvicorn app.main:app --port 8001
```

---

### Issue: Database locked error

**Problem**: SQLite database is locked or corrupted

**Solution**:
```bash
# Remove the database file
rm backend/app/storage/responsible_ai.db

# Restart backend (database will be recreated)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

### Issue: Frontend cannot connect to backend

**Problem**: `http://localhost:8000` returns CORS error or connection refused

**Solution**:
1. Ensure backend is running: `curl http://localhost:8000/health`
2. Check CORS_ORIGINS in `backend/.env` includes your frontend URL
3. Verify frontend URL in `frontend/src/api.js` or `frontend/.env.local`

```bash
# Restart backend after CORS change
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

### Issue: Jaeger traces not appearing

**Problem**: No traces in Jaeger UI

**Solution**:
1. Verify Jaeger is running: `docker compose ps jaeger`
2. Check backend logs for telemetry errors
3. Verify `JAEGER_HOST` and `JAEGER_PORT` in `backend/.env`

```bash
# Restart Jaeger
docker compose restart jaeger
```

---

### Issue: GROQ_API_KEY not working

**Problem**: Backend returns `groq-error` provider status

**Solution**:
1. Verify API key is valid at https://console.groq.com/keys
2. Check key is set correctly in `backend/.env` (no extra spaces)
3. Verify internet connectivity
4. Check Groq API status: https://status.groq.com

```bash
# Verify key is loaded
grep GROQ_API_KEY backend/.env
```

---

### Issue: Docker Compose fails to build

**Problem**: `ERROR: Service 'backend' failed to build`

**Solution**:
```bash
# Clear Docker cache
docker system prune -a

# Rebuild from scratch
docker compose up --build

# Or with increased verbosity
docker compose build --verbose
```

---

### Issue: Node modules or pip packages conflict

**Problem**: `npm ERR!` or `pip error`

**Solution**:
```bash
# Frontend
cd frontend
rm -rf node_modules package-lock.json
npm install

# Backend
cd backend
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Development Workflow

### Workflow: Backend Changes

1. Edit Python files in `backend/app/`
2. Backend auto-reloads (with `--reload` flag)
3. View logs in the terminal
4. Test with curl or frontend UI

```bash
# Backend auto-reloads on save
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Workflow: Frontend Changes

1. Edit React/JSX files in `frontend/src/`
2. Frontend auto-reloads (with `npm run dev`)
3. View changes immediately in browser

```bash
# Frontend auto-reloads on save
cd frontend
npm run dev
```

### Workflow: Database Schema Changes

1. Edit models in `backend/app/database.py`
2. Remove `backend/app/storage/responsible_ai.db` to force migration
3. Restart backend

```bash
rm backend/app/storage/responsible_ai.db
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Workflow: Adding Dependencies

**Backend**:
```bash
cd backend
source venv/bin/activate
pip install new-package
pip freeze > requirements.txt
```

**Frontend**:
```bash
cd frontend
npm install new-package
npm run dev
```

### Workflow: Code Quality Checks

```bash
# Backend: Lint and type checking
cd backend
source venv/bin/activate
python -m compileall app

# Frontend: Build verification
cd frontend
npm run build
```

---

## Production Deployment

### Prerequisites

- Server: Ubuntu/Debian, CentOS, or managed Kubernetes cluster
- Python 3.10+ installed
- PostgreSQL database (recommended over SQLite)
- OpenTelemetry backend (Jaeger, Datadog, New Relic, etc.)
- Reverse proxy (Nginx, Apache) for HTTPS

### Step 1: Prepare Environment

```bash
# Clone repository
git clone https://github.com/josephstephenrajkumar/responsible-ai-chat-agent.git
cd responsible-ai-chat-agent

# Create production .env
cat > backend/.env << 'EOF'
PROJECT_NAME=Responsible AI Chat Agent
GROQ_API_KEY=your_production_key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_API_URL=https://api.groq.com/openai/v1
DATABASE_URL=postgresql://user:password@db.example.com/responsible_ai
OTEL_SERVICE_NAME=responsible-ai-chat-agent-prod
JAEGER_HOST=jaeger.example.com
JAEGER_PORT=6831
JAEGER_ENDPOINT=https://jaeger.example.com/api/traces
JAEGER_UI_URL=https://jaeger.example.com
CORS_ORIGINS=https://app.example.com
EOF
```

### Step 2: Build Docker Images

```bash
# Build production images
docker compose -f docker-compose.yml build

# Push to registry (optional)
docker tag responsible-ai-chat-agent:latest your-registry/responsible-ai-chat-agent:latest
docker push your-registry/responsible-ai-chat-agent:latest
```

### Step 3: Deploy to Kubernetes (Optional)

Create `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: responsible-ai-backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: responsible-ai-backend
  template:
    metadata:
      labels:
        app: responsible-ai-backend
    spec:
      containers:
      - name: backend
        image: your-registry/responsible-ai-chat-agent:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        - name: GROQ_API_KEY
          valueFrom:
            secretKeyRef:
              name: groq-credentials
              key: api-key
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
---
apiVersion: v1
kind: Service
metadata:
  name: responsible-ai-backend
spec:
  selector:
    app: responsible-ai-backend
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

Deploy:

```bash
kubectl apply -f k8s-deployment.yaml
```

### Step 4: Configure Nginx Reverse Proxy

Create `/etc/nginx/sites-available/responsible-ai`:

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    ssl_certificate /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://localhost:5173;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name app.example.com;
    return 301 https://$server_name$request_uri;
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/responsible-ai /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 5: Health Monitoring

```bash
# Create systemd service for backend
cat > /etc/systemd/system/responsible-ai-backend.service << 'EOF'
[Unit]
Description=Responsible AI Chat Agent Backend
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/responsible-ai-chat-agent/backend
Environment="PATH=/opt/responsible-ai-chat-agent/backend/venv/bin"
ExecStart=/opt/responsible-ai-chat-agent/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl enable responsible-ai-backend
sudo systemctl start responsible-ai-backend
sudo systemctl status responsible-ai-backend
```

### Step 6: Monitoring & Logging

```bash
# View backend logs
sudo journalctl -u responsible-ai-backend -f

# View Nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Monitor database
# (Set up PostgreSQL monitoring/backup separately)
```

---

## Support & Documentation

- **Architecture**: See [RESPONSIBLE_AI_DESIGN.md](RESPONSIBLE_AI_DESIGN.md)
- **Governance**: See [GOVERNANCE_POLICY.md](GOVERNANCE_POLICY.md)
- **Testing**: See [TEST_PLAN.md](TEST_PLAN.md)
- **GitHub**: https://github.com/josephstephenrajkumar/responsible-ai-chat-agent
- **Issues**: https://github.com/josephstephenrajkumar/responsible-ai-chat-agent/issues

---

**Happy coding! 🚀**
