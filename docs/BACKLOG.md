# Backlog — candidates not yet on the roadmap

Items here are agreed as worth doing but are **not scheduled**. They move to [ROADMAP.md](ROADMAP.md) at a sprint
planning session, at which point the Activate AI Platform Word specifications in `docs/AI platform /` are updated
in the same change (new rows carry †). Until then they also appear in section 5 (Beyond Phase 4 backlog) of the
*Activate AI Platform Overall Roadmap* so the commercial plan and this repository stay aligned.

Effort uses the same scale as [TECH_DEBT.md](TECH_DEBT.md): S < 1 day, M 1–3 days, L > 3 days. Man-days (MD) are
split Design / Development / Testing. Section 5 of the Word roadmap carries indicative figures **including its 20%
buffer**, so BL-01 + BL-02 (9 MD) appear there as one 11 MD row (Overall Roadmap release 1.5, 3 October 2026).

| ID | Item | Why it matters | Effort | MD (D / Dev / T) | Earliest sensible sprint | Depends on | Retires | Source |
|---|---|---|---|---|---|---|---|---|
| BL-01 | **Reproducible build and signed SBOM** (supply-chain trust, slice A): hash-pinned `backend/requirements.lock`, base image by digest, checksums for `backend/vendor/`, Guardrails validators installed at image build, CI workflow that builds, generates CycloneDX SBOMs with Syft, scans with Grype (critical fails the build), signs and attests with cosign keyless, pushes to ECR, deploys `image_tag` = git SHA. | Customers and auditors ask what is in the software; an SBOM is only trustworthy when the build is reproducible. Also the slopsquatting control for AI-suggested dependencies. | M | 3 (0.5 / 2 / 0.5) | Sprint 2 (hardening) | — | TD-13 (image tag), TD-16 (CI), TD-19, TD-20, TD-21 | [SUPPLY_CHAIN_TRUST.md](SUPPLY_CHAIN_TRUST.md) §3–4, §5 (signing) |
| BL-02 | **Provenance, AI-BOM and customer trust package** (supply-chain trust, slice B): SLSA Build L2 provenance, VEX statements for non-affecting findings, licence allow-list, AI-BOM rendered from the model catalogue (models, guardrails, judges, proxy version), branch protection with signed commits and required human review, release checklist that publishes SBOM + provenance + VEX + AI-BOM + trust statement, customer verification guide. | Makes AI-assisted development defensible to enterprise buyers; lines up with EU Cyber Resilience Act SBOM obligations (from Dec 2027) and US self-attestation requirements. | L | 6 (1.5 / 3 / 1.5) | Sprint 4 (governance and compliance) | BL-01 | TD-27 (pinned proxy image) | [SUPPLY_CHAIN_TRUST.md](SUPPLY_CHAIN_TRUST.md) §5–8 |

## Decisions

- 2026-10-03: supply-chain trust (BL-01, BL-02) recorded here rather than on the roadmap, by decision of the repo owner.
  The milestone proposal (M16) in [SUPPLY_CHAIN_TRUST.md](SUPPLY_CHAIN_TRUST.md) §8 stays as the ready-to-paste text for
  when it is scheduled.
