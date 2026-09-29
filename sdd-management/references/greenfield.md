# Greenfield: from zero to production

The first thing a new product delivers is not a feature: it is a **walking skeleton** — the thinnest end-to-end slice (UI → API → data) built on the chosen stack, covered by unit, integration and E2E tests, running through CI and **deployed by the pipeline to staging and production**. Every feature after that is a small, safe, fast increment on a path that already works.

## 1. Product framing

Before choosing any technology, ask the user what cannot be inferred. Track each question in the foundation epic's *Questões em Aberto* until answered, then reflect the answers in Visão, Escopo and NFRs:

- **Domain/industry** and the 3–5 core user journeys.
- **Users:** who, how many at launch and in 12 months, where (regions, latency), which clients (web, mobile, desktop, API consumers).
- **Data:** volume, sensitivity (personal, payment, health), retention, residency.
- **Compliance:** LGPD/GDPR, PCI-DSS, HIPAA, SOC 2, sector regulators; audit needs.
- **Integrations:** payments, identity, ERPs, messaging, third-party APIs.
- **Targets:** availability, latency, peak patterns, RPO/RTO.
- **Team:** size, languages and frameworks it already masters, who operates production.
- **Constraints:** budget, cloud/on-prem preference, company standards, time to first release.
- **Tracking:** where the work will be followed — repository only, Jira, GitHub, Linear, other (recorded in `tracker`).

## 2. Stack selection — best fit for the domain

One ADR per layer decision (`origin: decision`, MADR format), with **Opções Consideradas**, the weighted **Prós e Contras** matrix and sources under **Mais Informações**.

| Layer | Decide |
|---|---|
| UI | web framework and rendering model (SPA, SSR/SSG, hybrid), mobile approach (native, cross-platform), component library/design system, state and data fetching |
| Backend | language/runtime, framework, API style (REST, GraphQL, gRPC, events), validation, background jobs |
| Data | primary database, migrations tool, cache, search, object storage |
| Async | queue/stream/event bus, scheduling |
| Identity | authentication (managed IdP vs self-hosted), authorization model (RBAC/ABAC), multi-tenancy |
| Infrastructure | hosting model (static/CDN, PaaS, managed containers, serverless, Kubernetes), IaC tool, regions |
| Delivery | repository layout (mono/poly), CI/CD platform, trunk-based flow, feature flags, secrets management |
| Observability | structured logs, metrics, traces, error tracking, alerting, uptime checks |
| Testing | unit, integration (real dependencies), contract, E2E, performance, security scanning |

Rules:

- **Fit over fashion.** Score options against criteria weighted by the framing: domain fit; maturity, LTS and maintenance activity; ecosystem for this domain; performance and scalability for the stated load; security/compliance support; team skill and hiring market; operational cost and complexity; hosting fit; lock-in and license.
- **Two or three real options per layer**, including the team's current stack when it has one — familiarity is a legitimate, heavily weighted criterion.
- **Verify currency.** Training data goes stale. When web search or documentation tools are available, confirm current stable/LTS versions, support windows and maintenance status from official sources and record them under *Mais Informações* with the date. Never recommend end-of-life or deprecated technology. If verification isn't possible, say so explicitly in the ADR and to the user.
- **Prefer managed services and proven technology** unless a requirement demands otherwise: fewer moving parts means faster delivery and cheaper operation.
- **Evaluate the stack as a whole**: typed contracts end to end, shared tooling, one way to run everything locally.
- The human approves the stack at H1 of the foundation epic, before any code.

Domain drivers and their usual implications (starting points for the matrix, not rules):

| Driver | Implication |
|---|---|
| Payments / finance | strong consistency (relational DB, transactions), idempotency keys, immutable audit log, minimize PCI scope with provider tokenization, ledger/double-entry where money moves |
| Health / sensitive data | encryption at rest and in transit, fine-grained access control, access audit trail, data residency |
| E-commerce / content / SEO | SSR/SSG, CDN, image optimization, Core Web Vitals budgets |
| B2B SaaS | tenancy isolation strategy, SSO (OIDC/SAML), RBAC, per-tenant limits, audit log |
| Real-time / collaboration | WebSockets/SSE, pub/sub, presence, conflict resolution |
| Data / analytics heavy | separate OLTP and OLAP, event streaming, batch pipelines |
| Mobile-first | offline support and sync, push notifications, API versioning for old app versions |
| High or spiky traffic | stateless services, autoscaling, caching, queues for load leveling |

## 3. Architecture defaults

- Start with a **modular monolith** — modules with explicit public contracts, enforced by architecture tests — unless requirements justify separate deployables (independent scaling, independent teams, different runtimes). With enforced boundaries, extracting a module later is cheap; distributed-first is expensive to build, test and operate.
- Organize by feature/domain (vertical slices or modules), not only by technical layer.
- Contracts between modules are the specs' contracts; G3 architecture tests enforce the boundaries from day one.
- Twelve-factor basics: configuration from the environment, stateless processes, disposable instances, dev/prod parity, logs as event streams.

## 4. Foundation epic

Create an epic with `type: foundation`. Adapt the children to the product, but never drop testing, pipeline, deploy or observability:

| # | Child spec (type foundation) | Delivers |
|---|---|---|
| 1 | Repository & tooling | structure, build, lint/format, `sdd-config.yml` (incl. `tracker`), `vendor --agents --pr-template --hooks --changelog`, conventions in the root docs (Conventional Commits, Keep a Changelog, SemVer) |
| 2 | Test harness | unit + integration (real dependencies) + E2E running locally and in CI with one example each; architecture test suite enforcing the foundation ADRs |
| 3 | CI pipeline | on every push/PR: build, lint, unit, integration, architecture, E2E, dependency and secret scanning, artifact/container build, plus the SDD job (`vendor --ci`) required in branch protection; main always green and deployable |
| 4 | Environments & IaC | staging and production as code, secrets management, database migrations executed by the pipeline |
| 5 | Walking skeleton | the thinnest real journey (e.g. sign in → see an empty dashboard) through every layer, with its E2E test, deployed to staging and production by the pipeline |
| 6 | Observability baseline | structured logs, metrics, traces, error tracking, health checks, an alert on the skeleton journey |
| 7 | Security baseline | authentication/authorization skeleton, HTTPS, security headers, dependency policy, no secrets in the repo |

Typical dependencies: 2 and 3 depend on 1; 4 consumes 3's contract; 5 depends on 2, 3 and 4; 6 and 7 consume 5's contract. Declare them in the frontmatter and let `waves` compute the order. Feature epics start only after the foundation epic is implemented.

## 5. Path to production

Choose by workload and record it in an ADR:

| Workload | Usual best fit |
|---|---|
| Static site / SPA | static hosting behind a CDN (e.g. Cloudflare Pages, Vercel, Netlify, S3 + CloudFront, Azure Static Web Apps) |
| SSR web app | a platform with first-class support for the framework's SSR, or a container |
| API / web service | managed containers (e.g. Cloud Run, AWS App Runner or ECS Fargate, Azure Container Apps, Fly.io, Render) |
| Event-driven or spiky jobs | serverless functions + managed queues |
| Many services, dedicated platform team, special networking | managed Kubernetes (EKS, GKE, AKS) — only when justified |
| Mobile apps | store pipelines (e.g. Fastlane, EAS, Codemagic), staged rollout, OTA updates where allowed |
| Libraries / CLIs | package registry publishing with semantic versioning and signed releases |

Databases: managed service with automated backups and point-in-time recovery.

Release practices — fast **and** safe:

- Trunk-based development, short-lived branches, small batches; main is always deployable.
- Every merge to main deploys to staging automatically and runs smoke + E2E; production goes through the same pipeline, with human confirmation (G6).
- Decouple deploy from release with feature flags; progressive delivery (canary, blue-green) for risky changes.
- Database changes are backward compatible (expand → migrate → contract), so any version can roll back.
- Rollback is a single, rehearsed action.
- Track DORA metrics: deployment frequency, lead time for changes, change failure rate, time to restore service.
