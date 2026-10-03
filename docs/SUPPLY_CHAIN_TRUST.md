# Supply-Chain Trust: SBOM, Provenance and Signing for AI-Assisted Software

| | |
|---|---|
| Status | Agreed 2026-10-03 and recorded in the [backlog](BACKLOG.md) as BL-01 and BL-02 (not on the roadmap by decision of the repo owner); section 8 keeps the roadmap text for when it is scheduled |
| Scope | Everything this repository ships: the gateway container image, the LiteLLM proxy image we run, the frontend bundle, Terraform/Terragrunt infrastructure, and the AI models and guardrails the product depends on at run time |
| Related | [ROADMAP.md](ROADMAP.md), [TECH_DEBT.md](TECH_DEBT.md), [NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md), [claude-development-cycle](claude-development-cycle/README.md), [MODEL_CATALOG.md](MODEL_CATALOG.md) |

## 1. Why this exists

A large share of this codebase is written with an AI coding assistant (18 of the first 25 commits carry the
Claude co-author trailer). That is a feature of how we build, and customers will ask two questions about it:
*what exactly is in the software* and *how do we know a human stood behind it*. A Software Bill of Materials
(SBOM) answers the first. Build provenance, signatures and review evidence answer the second. This document
describes how we produce all four so that we, and our customers, can trust every release.

An SBOM on its own is an inventory. Trust comes from the combination:

| Question a customer asks | What answers it |
|---|---|
| What is inside this release? | SBOM (CycloneDX JSON, SPDX on request) per artifact |
| Was it built from the source you say, by the pipeline you say? | SLSA build provenance |
| Is this file the one you published? | Sigstore signature on image, SBOM and provenance |
| Which vulnerabilities apply, and which do not? | Scanner report plus VEX statements |
| Which AI models and guardrails shape the product's behaviour? | AI-BOM (model components with model cards) |
| Who reviewed the AI-written code? | Signed commits, required review, development-cycle records, disclosure in release notes |

## 2. Where the repository stands (2026-10-03)

| Area | State | Gap for a trustworthy SBOM |
|---|---|---|
| Backend Python dependencies | `backend/requirements.txt`: 25 packages, none version-pinned, no hashes (TD-21) | SBOM changes on every build; slopsquatting exposure |
| Container base image | `python:3.11-slim` referenced by tag | Tag moves; shipped image may not match the scanned one |
| Gateway image tag in Terraform | `image_tag = latest` (TD-13) | Deployed artifact not reproducible from the SBOM |
| LiteLLM proxy image | floating `main-stable` tag (TD-27) | Third-party component changes without a release |
| Vendored binaries | `backend/vendor/`: spaCy model wheel, Guardrails tarball, no recorded source or checksum (TD-20) | Opaque blobs an auditor cannot verify |
| Runtime package installs | Guardrails Hub validators installed from an API call (TD-19) | Image contents change after the SBOM is produced |
| Frontend | `package-lock.json` committed, 4 dependencies | None |
| Terraform providers | `.terraform.lock.hcl` committed per live module | None; this is already an infrastructure BOM |
| CI pipeline | none (TD-16) | SBOMs must come from the build, not from a laptop |
| Secrets | scanner and hooks in place ([NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md)) | None; becomes evidence in the provenance |
| AI provenance | co-author trailer on AI-assisted commits | No enforced human review gate, no model/tool version recorded |

Five open debt items (TD-13, TD-16, TD-19, TD-20, TD-21, TD-27) are prerequisites of this work. Doing it
gives them one owner and one exit criterion.

## 3. Layer 1: deterministic inputs

Nothing downstream is meaningful until the inputs stop moving.

1. **Python**: generate a hash-pinned lock file with pip-tools and install with hashes required.

   ```bash
   pip-compile --generate-hashes --output-file backend/requirements.lock backend/requirements.txt
   pip install --require-hashes -r backend/requirements.lock
   ```

   Keep `requirements.txt` as the human-edited intent and `requirements.lock` as the build input. Renovate or
   Dependabot refreshes the lock on a schedule, through a reviewed pull request.
2. **Base image**: reference `python:3.11-slim@sha256:<digest>` in `backend/Dockerfile`. Dependabot keeps the digest current.
3. **Vendored files**: record source URL and sha256 for the spaCy wheel and the Guardrails tarball in
   `backend/vendor/CHECKSUMS.txt` and verify them in the Dockerfile, or move them to CodeArtifact / S3 and
   download at build time with checksum verification.
4. **Guardrails validators**: install at image build (TD-19). After this, the image is immutable in production.
5. **Images we deploy**: Terraform `image_tag` becomes the git SHA (or digest); the LiteLLM proxy image is pinned to a release tag.

## 4. Layer 2: generate SBOMs in the pipeline

Run in CI on every build of `main` and every release tag. Syft is the generator; CycloneDX 1.6 JSON is the
primary format because it carries licences, vulnerabilities, VEX and machine-learning components in one schema.
SPDX 2.3/3.0 is produced on request.

| Artifact | Command (illustrative) | Output |
|---|---|---|
| Gateway container image | `syft <ecr-image>@<digest> -o cyclonedx-json` | `sbom/gateway-image.cdx.json` |
| Source tree | `syft dir:. -o cyclonedx-json` | `sbom/source.cdx.json` |
| Frontend bundle | `syft dir:frontend -o cyclonedx-json` | `sbom/frontend.cdx.json` |
| Infrastructure | Terraform lock files (already committed) plus Terragrunt module list | `sbom/infra.cdx.json` (generated from the lock files) |

Alternative: `docker buildx build --sbom=true --provenance=true` produces SBOM and provenance as OCI
attestations in one step. AWS Inspector can also export an SBOM for an ECR image, which gives customers an
independent second source to compare against ours.

SBOMs are stored in three places: attached to the image in ECR as an OCI attestation, attached to the GitHub
release, and archived in S3 with the deployment snapshot under `docs/aws-snapshots/`.

## 5. Layer 3: sign and attest

- **Signing**: cosign with keyless Sigstore. GitHub Actions authenticates with its OIDC identity, so there is no
  signing key to protect or rotate, and the certificate names the exact workflow that produced the artifact.
- **Provenance**: SLSA Build Level 2 from the start (hosted builder, signed provenance), Level 3 when the build
  moves to the SLSA GitHub generator or a hardened CodeBuild project. Provenance records source commit, builder,
  parameters and the materials (base image digest, lock file hash).
- **Controls as evidence**: the provenance predicate references the gates that ran: secret scan, unit tests,
  scenario tests, vulnerability scan result. Customers see the controls, not just the claim.

Customer verification, one command against the image in ECR:

```bash
cosign verify-attestation --type cyclonedx \
  --certificate-identity-regexp 'https://github.com/josephstephenrajkumar/RESPONSIBLE-AI-ENTERPRISEREADY/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  767141477889.dkr.ecr.ap-southeast-1.amazonaws.com/responsible-ai-dev-ai-gateway@sha256:<digest>
```

## 6. Layer 4: scan, triage, explain

- Grype (or Trivy) scans the SBOM at build time and nightly against fresh advisories. Critical findings fail the build;
  high findings open an issue with an owner and a date.
- ECR enhanced scanning (Amazon Inspector) stays on as the continuous in-account scanner.
- Findings that do not affect us get a VEX statement (CycloneDX VEX or OpenVEX) with the justification, for example
  "vulnerable function not in execution path". Customers receive analysis, not a raw count.
- Licence data from Syft is checked against an allow-list (permissive licences allowed, copyleft reviewed). If a
  customer requires snippet-level assurance against licensed code reproduced by an AI assistant, ScanCode is added.

## 7. What AI-assisted development changes

### 7.1 AI-BOM: the models and guardrails are components

The product's behaviour depends on components that never appear in a package manifest. CycloneDX models them as
`machine-learning-model` components with a model card. The existing model catalogue ([MODEL_CATALOG.md](MODEL_CATALOG.md))
and `litellm/config.yaml` are the source of truth; the pipeline renders them into `sbom/ai-bom.cdx.json`.

| Component | Example entries | Model-card fields we record |
|---|---|---|
| Inference models | Groq Llama family, Bedrock Claude models, judge models | provider, model id and version, purpose (chat, judge, fast), data-handling terms, region |
| Guardrails | Guardrails AI v0.10.0 and installed Hub validators, Presidio | version, which checks run on which path |
| NLP models | spaCy `en_core_web_sm` 3.8.0 | version, licence, source |
| Evaluation | Ragas, TruLens versions and the judge model they call | version, sampling policy |
| Proxy | LiteLLM release tag | version, config hash |

### 7.2 Hallucinated and typosquatted packages

AI assistants sometimes propose package names that do not exist; attackers register those names ("slopsquatting").
Unpinned requirements plus AI suggestions is the risky combination. Controls, in order of value:

1. Hash-pinned lock files (section 3) so an unknown name cannot enter a build unreviewed.
2. A rule in the development cycle: every new dependency is checked by a human for an existing, maintained upstream
   repository, download history and maintainers before it enters `requirements.txt` or `package.json`.
3. Optionally CodeArtifact as the only package source, with an allow-list of upstream packages.

### 7.3 Provenance of AI-written code

- Keep the `Co-Authored-By: Claude …` commit trailer; it is the honest record of AI involvement.
- Branch protection on `main`: pull requests only, at least one human approval, signed commits, required status checks
  (tests, secret scan, SBOM, vulnerability scan).
- Record the assistant and model version per change in `docs/claude-development-cycle/records/`.
- Add an AI-development disclosure to SBOM metadata (`metadata.properties`) and to release notes: which parts were
  AI-assisted, which review gates applied. Customers accept AI-assisted code when the review gate is explicit and
  verifiable, and reject it when it is hidden.

### 7.4 Secrets

The no-secrets rule and its hooks ([NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md)) are the first supply-chain control already
enforced. The CI job runs `scripts/check_no_secrets.py --all` as a required check and the provenance records the result.

## 8. Delivery plan and roadmap placement

**Decision 2026-10-03: recorded in [BACKLOG.md](BACKLOG.md) as BL-01 (slice A) and BL-02 (slice B) and in section 5 of the Activate Overall Roadmap, not on the sprint roadmap yet.** The recommendation below stands for the next planning session: schedule it as its own cross-cutting theme and milestone (M16), delivered in two slices.
It is not optional for a product sold to enterprises: the EU Cyber Resilience Act requires an SBOM for products with
digital elements from December 2027, US federal buyers require secure-development self-attestation (OMB M-22-18) and
the CISA minimum elements, and most enterprise security questionnaires already ask for SBOM, signing and
vulnerability-disclosure practice. The Sprint 6 exit criterion (a second application onboards) and any customer
pilot will need slice A at minimum.

| Slice | Content | Effort | Suggested sprint | Retires |
|---|---|---|---|---|
| A. Reproducible build and SBOM | Hash-pinned Python lock, base image by digest, vendor checksums, Guardrails at build time, CI workflow that builds, generates SBOMs with Syft, scans with Grype, fails on critical, pushes to ECR with cosign keyless signature and SBOM attestation, `image_tag` = git SHA | M (2–3 days) | Sprint 2 (hardening) | TD-13 (image tag), TD-16 (CI), TD-19, TD-20, TD-21 |
| B. Provenance, AI-BOM and customer package | SLSA provenance, VEX workflow, licence allow-list, AI-BOM rendered from the model catalogue, branch protection and signed commits, release checklist that publishes the trust package, customer verification guide | L (5–7 days) | Sprint 4 (governance and compliance) | TD-27 (pinned proxy image) |

Proposed roadmap text, ready to paste:

> **Theme: Supply-chain trust.** Every release ships with a signed SBOM, build provenance and an AI-BOM that a customer can verify with one command. See [SUPPLY_CHAIN_TRUST.md](SUPPLY_CHAIN_TRUST.md).
>
> Sprint 2 bullet: **Reproducible build and SBOM** (slice A): hash-pinned `requirements.lock`, base image by digest, vendor checksums, Guardrails validators at image build, CI that produces CycloneDX SBOMs with Syft, scans with Grype, signs and attests with cosign keyless, deploys `image_tag` = git SHA (TD-13, TD-16, TD-19, TD-20, TD-21).
>
> Sprint 4 bullet: **Provenance, AI-BOM and customer trust package** (slice B): SLSA Build L2 provenance, VEX statements, licence allow-list, AI-BOM from the model catalogue, branch protection with signed commits and required review, release checklist publishing SBOM + provenance + VEX + AI-BOM + trust statement (TD-27).
>
> Milestone row: `| M16 Signed SBOM, provenance and AI-BOM on every release | Sprints 2, 4 | M2 |`

Because every roadmap requirement is mirrored into the Activate AI Platform Word specifications
(`docs/AI platform /`), adding M16 also means new † rows in the Overall Roadmap with Design / Development / Testing
man-days, attributed S (shared core), and recomputed phase totals.

## 9. Standards and references

- CycloneDX 1.6 specification (SBOM, VEX, ML-BOM / model cards, formulation). SPDX 2.3 and 3.0 (AI and Dataset profiles).
- SLSA v1.0 build levels; in-toto attestation framework; Sigstore cosign keyless signing.
- NTIA minimum elements for an SBOM (2021); CISA SBOM guidance and VEX use cases.
- US Executive Order 14028 and OMB M-22-18 secure software self-attestation.
- EU Cyber Resilience Act (Regulation (EU) 2024/2847), SBOM and vulnerability-handling obligations from 2027.
- Tools: Syft, Grype, Trivy, cosign, pip-tools, Dependabot/Renovate, ScanCode, Amazon Inspector SBOM export, ECR enhanced scanning.
