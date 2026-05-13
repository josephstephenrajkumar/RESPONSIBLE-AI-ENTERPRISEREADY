You are working on my existing Responsible AI Chat Agent project.

Goal:
Upgrade the Safety pillar from hardcoded Guardrails AI policies in guardrails_safety.py into an enterprise-grade SQLite-backed policy governance system.

Current state:
- Safety policies are hardcoded in backend/app/framework_mode/guardrails_safety.py
- The app uses FastAPI backend, React frontend, SQLite/SQLAlchemy, Guardrails AI, Langfuse, OpenTelemetry, and Jaeger

Required changes:

1. Move hardcoded safety policies into SQLite
- Create SQLAlchemy models for:
  - safety_policies
  - safety_policy_patterns
  - policy_audit_events
  - runtime_policy_decisions
- Add seed script to migrate the current hardcoded policies into the database

2. Replace hardcoded policy loading
- Refactor guardrails_safety.py so it no longer depends on _SAFETY_POLICIES
- Load enabled and approved policies from SQLite
- Compile regex patterns at runtime
- Cache compiled policies in memory
- Add reload support without restarting backend

3. Add FastAPI policy APIs
Create APIs:
- GET /policies
- POST /policies
- PUT /policies/{id}
- DELETE /policies/{id}
- POST /policies/{id}/approve
- POST /policies/{id}/activate
- POST /policies/reload
- POST /policies/test

4. Add governance workflow
Policy statuses:
- draft
- review
- approved
- active
- deprecated

Rules:
- New policies must start as draft
- Imported policies must never auto-activate
- Only approved policies can become active
- Every policy change must be written to policy_audit_events

5. Add React UX
Create:
- PolicyManager.jsx
- PolicyEditor.jsx
- PolicyTable.jsx
- PolicyApprovalModal.jsx
- PolicyTestLab.jsx
- GovernanceDashboard.jsx

UX must allow:
- create policy
- edit policy
- disable policy
- approve policy
- activate policy
- test sample prompt against policies
- view matched category, severity, regex, and blocked status

6. Add policy test lab
User enters sample text.
Backend returns:
- blocked
- risk_level
- matched categories
- matched patterns
- policy version
- validator engine

7. Add Guardrails AI runtime integration
- Build Guardrails validators dynamically from active DB policies
- Use regex-based validation first
- Keep graceful fallback if Guardrails AI is unavailable

8. Add observability
- Add Langfuse tracing for safety evaluation, policy reload, policy test
- Add OpenTelemetry spans:
  - chat.request
  - policy_load
  - policy_match
  - guardrails_validate
  - audit_insert

9. Add documentation
Update README with:
- architecture
- policy lifecycle
- how to seed policies
- how to create policies from UX
- how to test policies
- how to reload runtime policies

10. Important design rules
- Do not store raw user prompts in audit tables
- Store only hashed user input where needed
- Do not auto-import production policies from external websites
- External sources such as Guardrails Hub, NIST, OWASP must enter as draft policies only
- Keep the implementation simple, maintainable, and working locally

Please inspect the current project structure first, then implement the changes incrementally.
After implementation, provide:
- files changed
- how to run migrations/seed
- how to start backend/frontend
- how to test the new policy manager