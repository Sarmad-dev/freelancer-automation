# Freelancer OS --- Product Blueprint & AI Build Prompt Playbook

> **Purpose:** A staged, copy-ready set of prompts for building
> Freelancer OS with an AI coding agent. Use the prompts in order. The
> MVP prompts establish a working product; the post-MVP prompts expand
> it into a robust, full-fledged automation platform.

------------------------------------------------------------------------

## How to use this playbook

1.  Create a repository and commit the empty scaffold.
2.  Give your coding agent **Prompt 0** first. Ask it to inspect the
    repository and return a plan before changing files.
3.  Run each prompt separately and review the result before moving to
    the next one. Do not ask an agent to implement the entire document
    in one enormous pass.
4.  Keep a living `PROJECT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and
    `IMPLEMENTATION_STATUS.md`. Require the agent to update them after
    each phase.
5.  Run formatting, type checks, tests, migrations, and the application
    after each milestone. Fix failures before proceeding.
6.  Start with mocked integrations and seeded demo data. Connect real
    accounts only after OAuth, permissions, token storage, and error
    handling have been reviewed.
7.  Never put API keys, OAuth secrets, or production credentials in
    prompts, source code, client bundles, screenshots, or committed
    `.env` files.

**Product name:** Freelancer OS (working name; make it configurable).

**Core promise:** Help freelancers find suitable prospects, manage
relationships, create thoughtful outreach, automate repeatable business
workflows, and track conversations through a won/lost outcome---while
keeping the freelancer in control.

------------------------------------------------------------------------

# Part I --- Application definition

## 1. Product overview

Freelancer OS is an AI-assisted business development and workflow
automation workspace for independent freelancers, consultants, small
studios, and service businesses.

It combines five connected capabilities:

1.  **Freelancer business profile and knowledge:** A structured source
    of truth for services, skills, niche, experience, case studies,
    portfolio links, preferred clients, pricing guidance, tone of voice,
    and business goals.
2.  **Lead and relationship management:** Discover or import potential
    clients, enrich records from permitted sources, score fit, organize
    companies and contacts, and move opportunities through a pipeline.
3.  **AI-assisted outreach and inbox workflows:** Draft contextual
    emails, manage campaigns and follow-ups, classify incoming replies,
    summarize conversation history, recommend next actions, and create
    reminders. Sending must respect user approval and provider rules.
4.  **Visual workflow automation:** Build workflows from triggers,
    conditions, AI steps, actions, delays, approval gates, and
    error-handling branches. View execution history and safely retry
    failed runs.
5.  **Integrations and insights:** Connect email, calendars,
    spreadsheets, storage, and other business tools; monitor outreach,
    workflow reliability, and pipeline performance.

This is not intended to be an uncontrolled bulk-email tool. It should
prioritize relevant prospects, truthful personalization, consent and
applicable outreach requirements, provider policies, deliverability,
unsubscribe/suppression handling where required, rate limits, and human
review for consequential actions.

## 2. Target users and jobs to be done

-   **Independent freelancer:** Find suitable work, keep a clear view of
    prospects, send personalized outreach, and follow up consistently.
-   **Consultant or specialist:** Manage a longer sales cycle,
    proposals, meetings, and next steps.
-   **Small studio:** Share leads and workflows with teammates, assign
    ownership, and maintain consistent processes.
-   **Automation power user:** Connect business apps with triggers,
    filters, branching, delays, AI, and actions without writing code.

Primary user outcome: "I know who to contact, why they are a good fit,
what to say, what happened, and what to do next."

## 3. Product principles

-   **Human-in-the-loop by default:** Drafting and recommendations can
    be automated early; external side effects such as sending an email,
    changing a deal, or modifying a third-party record require explicit
    permission and configurable approval.
-   **Explainable AI:** Show the evidence behind fit scores, extracted
    facts, classifications, and recommendations. Distinguish sourced
    facts from guesses and never invent a portfolio result or client
    relationship.
-   **Reliable automation:** Durable jobs, idempotency, retry limits,
    timeouts, execution logs, and visible failure states.
-   **Privacy and least privilege:** Request only the OAuth scopes
    needed, encrypt secrets, isolate tenants, redact sensitive logs, and
    provide disconnect/export/delete controls.
-   **Progressive complexity:** Make the main CRM and inbox approachable
    while allowing advanced workflow controls when needed.
-   **One design system:** Web and desktop use the same visual language,
    terminology, interaction patterns, and core domain model.
-   **Accessible and responsive:** Keyboard access, visible focus,
    semantic labels, sufficient contrast, reduced-motion support, and
    layouts that work on laptop and smaller screens.
-   **Honest integrations:** Clearly distinguish connected, demo,
    unavailable, rate-limited, and permission-denied states.

## 4. Themes and visual design system

### Brand direction

Create a premium, calm, focused, professional SaaS product. It should
feel like a combination of a polished productivity app and a capable
automation studio---not a generic admin template.

-   **Default theme:** Dark neutral workspace.
-   **Light theme:** A fully designed alternative, not merely inverted
    colors.
-   **Canvas/background:** `#101114`
-   **Sidebar:** `#141519`
-   **Panels/cards:** `#181A20`
-   **Elevated surface:** `#20232B`
-   **Primary text:** `#F3F4F6`
-   **Secondary text:** `#A1A1AA`
-   **Borders/dividers:** `#2B2E36`
-   **Accent:** `#A8E66B` (use sparingly for primary action, success,
    active workflow state, and selected highlights)
-   **Warning/error/info:** Accessible semantic colors that remain
    legible in both themes; do not use the accent as the only status
    signal.
-   **Typography:** Geist or Inter, with a consistent scale and strong
    hierarchy.
-   **Icons:** Lucide-style consistent stroke icons. Avoid emoji as
    interface icons.
-   **Shapes:** Subtle radii, restrained shadows, clear spacing, tidy
    alignment, data-dense tables, and generous breathing room on
    overview pages.
-   **Motion:** Brief, purposeful transitions; no distracting perpetual
    animation. Honor reduced-motion preferences.
-   **Charts:** Clear labels, useful tooltips, accessible contrast, and
    no chart that depends on color alone.
-   **Workflow canvas:** A distinctive node editor with curved
    connectors, grid/dot background, compact but readable node cards,
    clear branch labels, minimap, zoom controls, and a contextual
    inspector.

### Layout system

-   Persistent left sidebar with workspace switcher, primary navigation,
    integration/automation status, and user profile.
-   Top bar with breadcrumbs or page title, global search/command
    palette, contextual actions, notifications, and help.
-   Main content area with clear page-level hierarchy and consistent
    loading, empty, error, and success states.
-   Use tables for operational data, cards for summaries, drawers for
    quick edits, and dedicated pages for complex tasks.
-   The workflow editor may use a full-screen workbench layout with a
    top toolbar, left node library, central canvas, right inspector, and
    bottom execution panel.
-   Do not make every screen a dashboard of cards. Choose layouts based
    on the job being done.

## 5. Main navigation and information architecture

1.  **Home**
    -   Overview, recommended next actions, recent activity, upcoming
        follow-ups, performance snapshot.
2.  **Leads**
    -   Lead list, lead detail, companies, contacts, imports,
        enrichment, saved views, duplicate review.
3.  **Inbox**
    -   Unified email conversations, reply classification, draft review,
        follow-up queue, suppression/unsubscribe status.
4.  **Campaigns**
    -   Campaign list, sequence builder, recipients, drafts, approvals,
        delivery and reply analytics.
5.  **Pipeline**
    -   Opportunities, stages, activities, proposals, deal value,
        win/loss reasons.
6.  **Automations**
    -   Workflow list, workflow editor, templates, runs, schedules,
        errors, audit trail.
7.  **Tasks & Calendar**
    -   Tasks, reminders, meetings, deadlines, due/overdue follow-ups.
8.  **AI Workspace**
    -   AI assistant, freelancer profile/knowledge, reusable prompts,
        generation history.
9.  **Integrations**
    -   Connected apps, available connectors, permissions, connection
        diagnostics.
10. **Analytics**
    -   Leads, campaign outcomes, reply rates, pipeline conversion,
        workflow reliability, usage/cost.
11. **Settings**
    -   Profile, workspace, team, security, notification preferences, AI
        providers, billing/usage, data export and deletion.

MVP can expose fewer top-level destinations, but the data model and
navigation should not paint the product into a corner.

## 6. Feature catalogue

### A. Account, workspace, and onboarding

-   Sign up, sign in, sign out, session management, password reset or
    supported identity provider.
-   Create a personal workspace; keep the data model ready for teams and
    organizations.
-   Onboarding wizard for role, services, skills, niche, ideal client,
    geography/time zone, portfolio, writing style, and business goal.
-   Connect email as an optional step; allow users to skip and explore
    demo mode.
-   Import sample leads and run a guided first workflow.
-   Onboarding progress that can be resumed.

### B. Freelancer profile and knowledge base

-   Structured profile: services, skills, years of experience,
    industries, portfolio URLs, case studies, differentiators, target
    customer, excluded customer types, rate/pricing guidance, tone, and
    preferred call to action.
-   Upload or enter reference material, with clear source attribution
    and processing status.
-   Review and edit AI-extracted facts before they become reusable
    knowledge.
-   Versioned profile and knowledge entries; ability to delete or
    disable an item.
-   AI may use only approved profile facts when drafting outreach.
    Missing facts must be omitted or flagged for review.

### C. Leads, companies, and contacts

-   Create manually, CSV import, sample data, and supported connector
    import.
-   Fields: name, company, role, email, website, source, location,
    industry, notes, tags, owner, fit score, status, last activity, next
    action.
-   Search, filters, sorting, saved views, bulk selection, custom tags,
    and duplicate detection.
-   Company and contact relationships, activity timeline, notes, tasks,
    and email history.
-   Lead source and data freshness fields.
-   Enrichment only through authorized sources and connectors; record
    provenance and timestamps.
-   Fit score with criteria and evidence; let users tune the criteria.
-   Suppression list and do-not-contact status that cannot be bypassed
    by automation.

### D. Email and inbox

-   Connect a provider using secure OAuth and least-privilege scopes.
-   Unified conversation list, thread view, search, labels, attachments
    metadata, unread state, and assignment-ready structure.
-   AI reply categories such as interested, question, objection, not
    now, referral, out of office, unsubscribe, and irrelevant.
-   Confidence score and explanation; low-confidence classification goes
    to review.
-   Suggested reply with editable draft, supporting profile facts, and
    approval status.
-   Follow-up reminders and stop conditions.
-   Sending queue with provider limits, idempotency, bounce/error
    handling, and audit logs.
-   Never send a reply to a contact who opted out or is suppressed.
    Automatically stop sequences on replies, opt-out, bounce, or
    configured stop condition.

### E. Campaigns and sequences

-   Create a campaign, define audience, exclusions, sending identity,
    schedule, and sequence steps.
-   Email steps, delays, conditional branches, and manual-review steps.
-   Template variables and fallback behavior for missing data.
-   Preview each email with real test data and plain-text alternative.
-   Test mode and approval mode before activation.
-   Per-provider rate limits, daily caps, quiet hours, and
    time-zone-aware scheduling.
-   Campaign pause/resume/stop; remove a recipient from future sends.
-   Metrics with clearly defined denominators: queued, sent, delivered
    if available, bounced, replies, positive replies, opt-outs, and
    booked meetings.
-   Avoid misleading open-rate assumptions; explain provider measurement
    limitations.

### F. CRM pipeline and proposals

-   Configurable stages such as New, Contacted, Replied, Qualified,
    Meeting, Proposal, Negotiation, Won, and Lost.
-   Deal value/currency, probability, expected close date, next action,
    and owner.
-   Kanban and table views.
-   Timeline with messages, calls, meetings, notes, tasks, and status
    changes.
-   Proposal brief and AI-generated proposal draft using approved facts,
    scope, assumptions, and exclusions.
-   Human approval before sharing externally.
-   Win/loss reasons and conversion reporting.

### G. Visual workflow automation

-   Trigger types: manual, schedule, new lead, lead updated, new
    email/reply, stage changed, task due, webhook, and supported app
    event.
-   Nodes: trigger, condition/filter, branch, delay, AI classify, AI
    extract, AI draft, approval gate, create/update record, create task,
    send email, notify, call connector, and end.
-   Typed input/output schemas and validated connections.
-   Variables panel with searchable workflow context, trigger payload,
    lead fields, profile facts, prior step outputs, and safe defaults.
-   Branch labels and explicit fallback paths.
-   Save draft, validate, test with sample payload, activate, pause,
    duplicate, version, and rollback.
-   Run history with status, node-by-node inputs/outputs, duration,
    retries, redacted logs, and correlation ID.
-   Retry failed steps safely; never repeat an external side effect
    without idempotency protection.
-   Manual approval queues and timeouts.
-   Workflow templates, folders, tags, and ownership.
-   Version snapshots: an active run should continue against the version
    it started with.
-   Execution limits, concurrency limits, cancellation, and dead-letter
    handling.

### H. AI and model providers

-   Provider abstraction so the app can use a configured model gateway
    such as Jev or another supported provider without coupling domain
    logic to one vendor.
-   Model routing by task: classification, extraction, drafting,
    summarization, and complex reasoning.
-   Structured outputs with schema validation and safe fallback
    behavior.
-   Prompt templates with versioning and test cases.
-   Context assembly that uses only relevant approved data.
-   Token/usage accounting where provider data permits; estimate costs
    transparently.
-   Redaction controls, provider settings, model availability checks,
    timeout handling, and fallback policies.
-   Treat email content, imported documents, and connector payloads as
    untrusted input. Do not follow instructions embedded in those
    sources that conflict with system policy.
-   Never expose hidden system prompts, secrets, or other tenants' data.

### I. Integrations

Build a connector framework rather than hard-coding every provider into
UI logic. Potential integrations, subject to API availability and
provider approval:

-   Email: Gmail and Microsoft Outlook.
-   Calendar: Google Calendar and Microsoft Outlook Calendar.
-   Spreadsheets/data: Google Sheets and Airtable.
-   Documents/storage: Google Drive and other supported file stores.
-   Notifications: in-app and email; later Slack or similar.
-   Webhooks and generic HTTP connector for advanced users, with domain
    controls, secret management, request validation, and SSRF
    protection.
-   Later: billing, proposal/e-signature, task tools, and lead sources
    where terms permit.

Every connector needs a capability declaration, OAuth scope manifest,
connection state, health check, rate-limit handling, retries, test
action, disconnect/revoke flow, and user-visible error messages. Never
imply a connector is implemented just because its logo appears.

### J. Tasks, calendar, and notifications

-   Create tasks from leads, conversations, deals, and workflows.
-   Due date, priority, owner, status, reminders, and source link.
-   Daily follow-up queue and overdue view.
-   Calendar events only after the user connects a calendar and grants
    the required scope.
-   In-app notification center with preferences and read state.

### K. Analytics and reporting

-   Lead volume and fit distribution.
-   Campaign delivery/reply/positive-reply/opt-out metrics with clear
    definitions.
-   Pipeline by stage, value, aging, conversion, and win/loss.
-   Workflow success/failure rate, average duration, retry count, and
    most-failing steps.
-   AI usage and estimated cost.
-   Date filters and CSV export with permissions.
-   Empty states that explain when there is not enough data.

### L. Team, billing, and governance (post-MVP)

-   Organizations, invitations, roles, and workspace membership.
-   Role-based access control and audit events.
-   Usage quotas, plans, invoices, metering, and payment-provider
    abstraction.
-   Data retention, export, deletion, and privacy requests.
-   Admin settings, support diagnostics, feature flags, and service
    status.
-   Shared workflow ownership, reusable templates, and approval
    policies.

## 7. Recommended architecture and stack

Treat these as initial defaults. Inspect the repository and existing
conventions before changing them.

### Monorepo

Use a Turborepo-style monorepo with shared TypeScript packages:

``` text
freelancer-os/
  apps/
    web/                 # Next.js web application
    desktop/             # Electron shell; reuse web UI/domain packages
    api/                 # Python FastAPI service
  packages/
    ui/                  # shared UI primitives/design tokens where practical
    contracts/           # OpenAPI-generated or shared API contracts
    workflow-core/       # workflow schema, validation, node metadata
    workflow-editor/     # React Flow editor components
    shared-config/       # linting, TypeScript, formatting
  services/
    worker/              # durable background job worker if separately deployed
  infra/
    docker/
    scripts/
  docs/
    PROJECT.md
    ARCHITECTURE.md
    DECISIONS.md
    IMPLEMENTATION_STATUS.md
  .env.example
  package.json
  turbo.json
```

Do not force Python code into the JavaScript workspace; manage Python
dependencies with `pyproject.toml` and a modern Python package manager.

### Frontend

-   Next.js App Router, React, TypeScript, Tailwind CSS, and a
    consistent component system.
-   TanStack Query or a well-defined server/client data-fetching
    approach; avoid duplicate caches and ad hoc request patterns.
-   React Hook Form plus schema validation where appropriate.
-   React Flow for the visual workflow canvas.
-   XState only where explicit, non-trivial UI state machines materially
    help; do not use it as a substitute for backend workflow durability.
-   Accessible primitives, icon library, chart library, and a rich-text
    editor only when needed.
-   Shared domain contracts and UI patterns between web and Electron.

### Backend and data

-   FastAPI, Pydantic, SQLAlchemy 2.x or SQLModel, Alembic migrations,
    PostgreSQL.
-   Redis for cache, rate limits, lightweight coordination, and queue
    support where appropriate.
-   A durable job/execution system selected deliberately. Start with a
    database-backed queue for a small MVP only if its recovery, locking,
    retries, and observability are adequate; adopt a durable workflow
    engine such as Temporal or an equivalent when long-running
    multi-step workflows require it.
-   Object storage for uploads when required; virus scanning and content
    limits before processing.
-   OpenAPI as the API contract source; generate or validate client
    types.
-   Structured logs, error tracking, health/readiness endpoints,
    metrics, and request IDs.

### Desktop

-   Electron with a secure preload bridge and explicit IPC allowlist.
-   `contextIsolation: true`, `nodeIntegration: false`, restrictive
    navigation, Content Security Policy, safe external-link handling,
    and signed/reproducible packaging.
-   Keep OAuth callbacks, refresh tokens, and secrets out of renderer
    code. Prefer server-side OAuth/token handling where feasible.
-   Desktop may add system notifications and tray behavior later, but
    the core product must work in the web app.

### Core entities (initial model)

-   User, Workspace, Membership (organization-ready), FreelancerProfile,
    KnowledgeItem.
-   Lead, Company, Contact, Tag, Activity, Task, Opportunity,
    PipelineStage.
-   EmailAccount, Conversation, Message, Draft, Campaign, Sequence,
    SequenceStep, RecipientState, SuppressionEntry.
-   IntegrationConnection, OAuthCredentialReference, ConnectorAction.
-   Workflow, WorkflowVersion, WorkflowNode, WorkflowEdge, WorkflowRun,
    WorkflowStepRun, ApprovalRequest.
-   AIRequest, UsageRecord, Notification, AuditEvent.

Use UUID/ULID identifiers, timestamps, workspace ownership on
tenant-owned records, foreign keys, indexes, unique constraints, and
explicit deletion/retention behavior. Model secrets separately from
ordinary configuration. Do not persist access tokens in browser local
storage.

### Security and reliability baseline

-   Validate all input at the API boundary.
-   Enforce workspace isolation in every relevant query and background
    job.
-   Store secrets in a managed secret store in production; encrypt
    credential material at rest.
-   OAuth state/PKCE, refresh-token rotation where supported, minimal
    scopes, and revocation.
-   CSRF protections appropriate to the authentication model, secure
    cookies, strict CORS, rate limiting, and safe file upload limits.
-   Prevent SSRF in webhook/HTTP nodes; block metadata/private network
    destinations by default and revalidate redirects.
-   Treat imported content as untrusted; sanitize rendered HTML and
    protect against prompt injection.
-   Redact secrets and unnecessary personal data from logs.
-   Idempotency keys for sends and connector writes.
-   Tests for permissions, tenant isolation, opt-out enforcement,
    workflow retries, and duplicate sends.

------------------------------------------------------------------------

# Part II --- Global instructions for the coding agent

## Prompt 0 --- Establish project context and execution rules

**Run this first.**

``` text
You are the lead engineer and product-minded architect for Freelancer OS, an AI-assisted freelancer CRM and visual automation platform. Read this complete playbook before implementation.

First inspect the existing repository, installed tools, package managers, conventions, and any existing code. Do not overwrite working code or assume the repository is empty.

Before coding:
1. Summarize the product, users, MVP scope, and explicit non-goals.
2. Propose a monorepo architecture consistent with this document and explain important trade-offs.
3. Identify unknowns and choose safe, reversible defaults. Do not block on non-critical questions.
4. Produce or update docs/PROJECT.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, and docs/IMPLEMENTATION_STATUS.md.
5. Create a phased implementation plan with acceptance criteria and test strategy.

Engineering rules:
- Implement real, connected functionality, not just static mockups, unless a phase explicitly asks for a prototype.
- Use strict TypeScript and typed API contracts. Use Pydantic validation in FastAPI.
- Keep business logic out of React components and UI concerns out of domain services.
- Add migrations for schema changes; never silently mutate production schema.
- Add tests with each meaningful feature.
- Never hard-code credentials. Create .env.example with names and explanations only.
- Never claim an integration works until a real test or a clearly labeled mock has verified it.
- Use feature flags or disabled states for unfinished functionality.
- Preserve accessibility, responsive layouts, dark/light themes, and loading/empty/error/success states.
- Do not run destructive commands, delete user data, or rewrite project history.
- After each task, run the relevant formatter, linter, type checker, tests, and build. Fix failures caused by your changes.
- Update implementation status and document migrations, commands, environment variables, and known limitations.

Return the plan and then begin only the first requested phase. Do not attempt to build every phase in one pass.
```

## Prompt 1 --- Work in small, verifiable increments

``` text
Implement only the phase described in my latest instruction. Start by identifying the exact files and existing behavior affected. Then:
1. State a short implementation plan.
2. Make the smallest coherent set of changes.
3. Add or update tests for success cases, failure cases, permissions, and edge cases.
4. Run formatting, lint, type checks, tests, and relevant build commands.
5. Report changed files, migrations, commands run, results, remaining issues, and how I can verify the feature manually.
6. Update docs/IMPLEMENTATION_STATUS.md and relevant architecture/decision documents.

Do not silently skip a failing check. If a dependency or external credential is unavailable, implement a clearly isolated adapter/mock and describe exactly what remains for a real integration.
```

## Prompt 2 --- Product design and implementation discipline

``` text
Use the Freelancer OS design system from this playbook: premium, calm, focused SaaS; dark neutral theme with #101114 background, #141519 sidebar, #181A20 surfaces, #F3F4F6 primary text, #A1A1AA secondary text, #2B2E36 borders, and #A8E66B restrained accent. Build a complete light theme as well.

Use Geist or Inter, consistent spacing and radii, Lucide-style icons, clear information hierarchy, accessible contrast, visible keyboard focus, responsive behavior, and reduced-motion support.

Do not create a generic dashboard template. Use layouts suited to the task: operational tables for leads, thread layouts for email, Kanban for pipeline, and a full workbench for workflow editing. Every data page must include realistic loading, empty, error, success, and permission-denied states. Use realistic seeded demo data in development, clearly separated from production data.

Before implementing a new page, identify its route, data requirements, actions, permission requirements, empty state, error state, and mobile/responsive behavior. Reuse existing components and tokens instead of creating inconsistent one-off styling.
```

------------------------------------------------------------------------

# Part III --- MVP build prompts

## MVP definition and guardrails

The MVP should let one freelancer sign in, configure a professional
profile, manage leads, connect an email account or use demo mode, draft
and review outreach, track replies, use a small visual workflow builder,
and see basic activity and metrics.

### Include in MVP

-   Authentication and a personal workspace.
-   Onboarding and editable freelancer profile.
-   Lead/companies/contacts CRUD, CSV import, search, filtering, and
    sample data.
-   Pipeline with a small set of stages.
-   Email provider adapter with a real OAuth integration only when
    credentials and provider setup are available; otherwise a fully
    labeled demo connector.
-   Inbox/conversation records and AI reply classification/draft
    suggestions using a provider abstraction.
-   Manual send and approval-first sending; opt-out/suppression checks.
-   Basic visual workflow builder with a limited set of node types.
-   Background job execution, workflow runs, step logs, retries, and
    idempotency.
-   A few workflows: new lead → fit assessment → draft outreach →
    approval; reply received → classify → suggest next action; follow-up
    due → create task/approval item.
-   Tasks and reminders.
-   Basic analytics, audit trail for key actions, and security baseline.
-   Tests, local setup, migrations, seed data, Docker development
    environment, and documentation.

### Explicitly defer until after MVP

-   Complex team permissions and multi-workspace billing.
-   Dozens of live integrations.
-   Fully autonomous prospect discovery from arbitrary websites.
-   Unrestricted bulk sending, advanced deliverability optimization, and
    complex multichannel sequences.
-   A custom distributed workflow engine.
-   Native desktop-only features.
-   Sophisticated proposal e-signing, advanced forecasting, and
    enterprise governance.

## MVP Prompt 1 --- Repository scaffold and local development

``` text
Build the initial Freelancer OS monorepo scaffold after inspecting the repository.

Create:
- apps/web: Next.js App Router + React + strict TypeScript + Tailwind.
- apps/api: FastAPI + Pydantic + SQLAlchemy 2.x + Alembic.
- packages/ui: shared frontend tokens and reusable primitives where practical.
- packages/contracts: API schemas/client generation strategy.
- packages/workflow-core: initial workflow schema and validation types.
- docs: PROJECT.md, ARCHITECTURE.md, DECISIONS.md, IMPLEMENTATION_STATUS.md.
- Docker Compose for local PostgreSQL and Redis, plus app services if useful.
- Root scripts for development, formatting, linting, type checking, tests, and builds.
- .env.example with safe placeholders and descriptions.

Use a coherent package manager for the JS workspace and pyproject.toml for Python. Add health endpoints and a basic web-to-API connectivity check. Configure environment validation at startup with actionable errors. Add a seed command and migration workflow.

Acceptance criteria:
- A new developer can follow the README to start the project.
- Web app and API health endpoints work.
- Database migrations can be applied from a clean database.
- No secrets are committed.
- CI-ready checks exist and pass.
- Architecture choices and known limitations are documented.
Do not implement business features yet.
```

## MVP Prompt 2 --- Design system, app shell, and core navigation

``` text
Implement the Freelancer OS design system and authenticated application shell.

Create:
- Dark and light themes using centralized design tokens.
- Typography, spacing, radii, border, focus, status, and elevation tokens.
- Accessible buttons, inputs, selects, checkboxes, dialogs, dropdowns, tabs, badges, tooltips, toasts, skeletons, empty states, error states, and confirmation dialogs.
- Responsive sidebar with workspace selector, primary navigation, collapse behavior, and profile menu.
- Top bar with page title/breadcrumbs, global search placeholder, command palette, notifications placeholder, and contextual actions.
- Route-level loading and error boundaries.
- Sign-in, sign-up, and onboarding visual shells; keep auth behavior for the auth phase.
- A consistent table toolbar, filter chips, pagination, drawer, and page-header pattern.

Use realistic product copy and restrained animation. Ensure keyboard navigation, focus visibility, semantic labels, and reduced motion. Avoid decorative charts or buttons that do nothing; unfinished features must be visibly disabled or clearly marked.

Acceptance criteria: app shell works at desktop and tablet/mobile widths, theme preference persists safely, and reusable components have basic tests or a documented verification checklist.
```

## MVP Prompt 3 --- Authentication, workspace, and onboarding

``` text
Implement secure MVP authentication and personal workspace onboarding.

Requirements:
- Use a maintained authentication approach compatible with Next.js and FastAPI; document whether identity/session validation is handled by the API or a trusted identity provider.
- Secure cookies or another documented secure session mechanism. Never store long-lived tokens in localStorage.
- Sign up, sign in, sign out, session refresh/expiry handling, and password reset if supported by the selected approach.
- Create a personal workspace on first sign-in. Design the schema for future organization membership without implementing complex team management yet.
- Protect application routes and API endpoints.
- Enforce workspace ownership on every workspace-scoped query.
- Onboarding steps: role, services, skills, target clients, industries, portfolio links, experience, preferred tone, timezone, and primary business goal.
- Allow skip-and-return behavior and demo mode.
- Persist onboarding progress and validate all fields server-side.
- Add basic audit events for authentication-sensitive actions without logging credentials.

Tests must cover unauthorized access, session expiry, workspace isolation, invalid input, and onboarding resume. Document local test users only if they are restricted to development.
```

## MVP Prompt 4 --- Database domain model and API foundations

``` text
Implement the first stable database schema and API conventions for the MVP.

Create models and migrations for:
User, Workspace, Membership (owner-only MVP behavior), FreelancerProfile, KnowledgeItem, Company, Contact, Lead, Tag, LeadTag, Activity, Task, Opportunity, PipelineStage, EmailAccount metadata, Conversation, Message metadata, Draft, SuppressionEntry, IntegrationConnection metadata, Workflow, WorkflowVersion, WorkflowNode, WorkflowEdge, WorkflowRun, WorkflowStepRun, ApprovalRequest, UsageRecord, Notification, and AuditEvent.

Do not store raw OAuth tokens in general-purpose tables. Use a credential reference or a dedicated encrypted credential store abstraction.

Requirements:
- UUID or ULID identifiers, created_at/updated_at, appropriate foreign keys and indexes.
- Workspace ownership on tenant-scoped entities.
- Constraints for unique provider IDs and duplicate protection where appropriate.
- Soft deletion only where justified; document retention and deletion behavior.
- Pydantic request/response schemas separate from ORM models.
- Pagination, filtering, sorting, and consistent error response conventions.
- OpenAPI documentation and generated/validated frontend types.
- Seed fixtures for a fictional freelancer and clearly fictional companies/contacts.
- Migration rollback guidance and tests for constraints and tenant isolation.

Avoid over-engineering every future field. Include only necessary MVP fields, but document a safe evolution path.
```

## MVP Prompt 5 --- Freelancer profile and approved knowledge

``` text
Build the Freelancer Profile and Knowledge area.

UI:
- Profile editor for services, skills, experience, industries, target customer, excluded customer types, differentiators, portfolio URLs, case studies, pricing guidance, preferred tone, and call to action.
- Preview of the public-facing professional summary.
- Knowledge-item list with source, type, status, last updated, and enabled/disabled state.
- Add/edit/delete knowledge items and review extracted facts before approval.

Backend:
- Workspace-scoped CRUD endpoints and validation.
- Track provenance, approval status, and version/timestamps for knowledge items.
- Make approved facts available to the AI context builder; do not use unreviewed extraction as authoritative truth.
- Never invent case studies, client names, certifications, or measurable outcomes. Missing facts should be omitted or marked for review.
- Sanitize URLs and rendered content.

Seed a fictional profile. Add tests for workspace isolation, approval status, deletion, invalid URLs, and AI context selection. Make the area useful without an AI provider connected.
```

## MVP Prompt 6 --- Leads, contacts, companies, CSV import, and fit scoring

``` text
Implement the MVP lead-management system end to end.

Features:
- Lead, company, and contact list/detail/create/edit/archive flows.
- Search, sorting, pagination, filters, saved views if time allows, and bulk tagging.
- Company/contact relationships and an activity timeline.
- CSV import wizard: upload, column mapping, preview, validation errors, duplicate strategy, confirmation, progress, and downloadable error report.
- CSV export with authorization checks.
- Seeded demo data clearly labeled as sample data.
- Lead status and next action; basic pipeline-stage association.
- Configurable fit scoring based on user-defined criteria such as industry, service match, company type, budget signals, and geography. Show a score breakdown and source evidence; avoid false precision.
- Manual entry must remain fully usable without any external lead source.

Do not scrape sites or bypass access controls. Enrichment must use an approved API or user-supplied data and must record provenance and retrieval time. Add tests for CSV edge cases, duplicate handling, permissions, filtering, and score explanation.
```

## MVP Prompt 7 --- Pipeline, tasks, and activity timeline

``` text
Build the basic CRM pipeline and follow-up task system.

Pipeline:
- Default stages: New, Contacted, Replied, Qualified, Meeting, Proposal, Won, Lost.
- Table and Kanban views with drag-and-drop stage changes, accessible alternatives, and confirmation where needed.
- Opportunity value/currency, expected close date, probability, owner, source lead, and next action.
- Timeline of notes, emails, tasks, stage changes, and meetings.

Tasks:
- Create tasks from a lead, conversation, or opportunity.
- Due date/time, timezone, priority, status, reminders, and linked record.
- Today, upcoming, and overdue views.
- Complete, reschedule, and dismiss reminder actions.
- In-app notifications for due tasks.

Use optimistic UI only with rollback/error handling. Ensure all changes are workspace-scoped and audited. Tests cover invalid stage changes, duplicate task submission, timezone boundaries, and tenant isolation.
```

## MVP Prompt 8 --- AI provider abstraction and safe structured outputs

``` text
Implement an AI service layer for Freelancer OS without coupling the domain model to a single vendor.

Create interfaces for:
- classify_reply
- assess_lead_fit
- extract_profile_facts
- draft_outreach
- summarize_conversation
- recommend_next_action

Requirements:
- Provider adapter configured through server-side environment variables, supporting the chosen gateway/provider (Jev if its current API and credentials are available) through a replaceable adapter.
- If the provider cannot be verified, implement a mock adapter for local development and label all mock results.
- Typed request/response schemas, structured output validation, timeouts, bounded retries, rate limits, and safe failure behavior.
- Prompt templates with versions and a small evaluation fixture set.
- Build context from approved profile facts, lead data, and relevant conversation history only.
- Treat emails, imported text, documents, and tool results as untrusted content; ignore embedded instructions that attempt to override system policy or reveal secrets.
- Never make unsupported claims in personalized outreach.
- Record model/provider, task type, latency, success/failure, and usage when available. Redact message bodies and sensitive data from logs by default.
- Avoid sending unnecessary personal data to the model.

Add tests for malformed output, provider timeout, injection-like email content, missing profile facts, and fallback behavior. Document how to configure a real provider securely.
```

## MVP Prompt 9 --- Email integration framework and demo mode

``` text
Build the email integration foundation with a clear separation between provider capabilities and UI/domain logic.

First inspect the current official provider APIs and the credentials available in the environment. Do not assume OAuth scopes or API behavior. Implement one provider for MVP only if setup and credentials are available; Gmail is the preferred first connector if feasible. Otherwise build a complete demo adapter and leave real connection explicitly marked as not configured.

Requirements:
- Connector interface for authorize, callback, refresh, list/sync threads, fetch message metadata/body as needed, create draft, send approved message, disconnect, and health check.
- OAuth state validation and PKCE where applicable, minimal scopes, secure server-side token storage, refresh/revocation handling, and clear reconnect state.
- Do not put provider refresh tokens in browser storage or logs.
- Store external provider IDs and sync cursors idempotently.
- Handle provider pagination, rate limits, expired credentials, revoked access, and transient errors.
- Separate a local seeded/demo mailbox from real provider data.
- A send action must require an approved draft, check suppression status, apply rate limits, record an idempotency key, and create an audit event.
- Clearly indicate whether a message is demo-only, queued, sent, failed, or unknown due to provider timeout.

Add tests using mocked provider responses and document the exact steps required to configure OAuth. Do not claim live email sync until verified end to end.
```

## MVP Prompt 10 --- Inbox, reply classification, and draft review

``` text
Build the Inbox experience using the email connector abstraction.

UI:
- Conversation list with search, unread state, sender, subject, last activity, lead/company association, and AI category.
- Thread detail with message chronology, source timestamps, attachments metadata, and safe rendering of HTML email.
- AI classification categories: interested, question, objection, not now, referral, out of office, unsubscribe, and irrelevant.
- Classification confidence, explanation, and source snippets where useful.
- Suggested response editor with regenerate, edit, save draft, approve, and discard.
- Show which approved profile facts informed the draft.
- Low-confidence classification or uncertain intent must be sent to review.
- Clear stop status when a contact unsubscribes, bounces, or requests no further contact.

Backend:
- Idempotent sync and message upsert.
- AI classification jobs run asynchronously.
- Draft generation never sends automatically.
- Reply detection can stop related follow-up sequences.
- Suppression check enforced server-side at send time, not just in the UI.
- Audit important actions and redact sensitive data from logs.

Tests cover thread ordering, malformed email, unsafe HTML, duplicate sync events, classification failure, suppression enforcement, and draft approval.
```

## MVP Prompt 11 --- Workflow schema, validator, and execution engine

``` text
Implement the MVP workflow engine before building the visual editor. Treat workflow execution as a backend concern, not merely a React Flow canvas.

Supported MVP node types:
1. Manual or event trigger.
2. Condition/filter.
3. AI lead-fit assessment.
4. AI reply classification.
5. AI draft creation.
6. Create/update lead or opportunity.
7. Create task.
8. Approval gate.
9. Send approved email.
10. Delay.
11. Notify user.
12. End/success/failure.

Requirements:
- Versioned workflow definition with nodes, edges, node config schemas, typed ports, and validation.
- Validate missing required config, invalid edges, unreachable nodes, cycles not explicitly supported, unhandled branches, and unsafe actions.
- Define execution states: queued, running, waiting_approval, waiting_delay, succeeded, failed, cancelled.
- Persist a workflow run and step run before/while executing. Capture start/end time, attempts, status, safe output summary, error category, and correlation ID.
- Use a background worker/queue. Long delays must not hold a web request open or depend on an in-memory timer.
- Retries with backoff only for retryable errors; define maximum attempts and timeout per node.
- Idempotency keys for external side effects, especially sending email and writing connector data.
- Pin each run to a specific workflow version.
- Support cancellation and safe manual retry of failed steps where possible.
- Human approval pauses the run durably and resumes it only after an authorized decision.
- Prevent duplicate concurrent execution of the same event.
- Enforce workspace limits and permissions.

Provide unit tests for branching, invalid graphs, retries, delay resumption, approval resumption, duplicate events, cancellation, and idempotency. Document whether the MVP queue is database-backed or Redis-backed and its recovery limitations.
```

## MVP Prompt 12 --- Visual workflow editor

``` text
Build the Freelancer OS visual workflow editor on top of the validated workflow schema and execution API.

Visual design:
- Full workbench layout with top toolbar, left node library, central dotted canvas, right configuration inspector, and collapsible bottom run/debug panel.
- Distinct node designs for trigger, AI, action, logic, delay, approval, notification, and end/error.
- Curved edges, labeled true/false branches, zoom controls, minimap, fit-to-view, multi-select, keyboard navigation, and clear selection states.
- Compact, legible node summaries; avoid plain generic rectangles.
- Node library with categories and search.
- Inspector uses schema-driven forms with validation, contextual descriptions, and examples.
- Variable picker for trigger payload, lead fields, profile facts, prior step outputs, and constants.
- Undo/redo for editor changes where practical, draft autosave with conflict handling, and unsaved-change indicators.
- Validate button with actionable errors and canvas highlighting.
- Test workflow using a sample payload; display node-by-node outputs in a safe debug view.
- Activate, pause, duplicate, and view run history.
- Show a clear approval gate before enabling any workflow that can send messages or change external systems.

Create a starter template: “New Lead → Assess Fit → If Fit Is High, Draft Outreach → Approval → Send → Create Follow-up Task; Otherwise Tag for Review.” It must start in draft/test mode, never auto-send by default.

Persist the workflow definition through the API; do not keep the only copy in React state. Add integration tests that create a workflow in the UI and execute it through the backend.
```

## MVP Prompt 13 --- Starter automations and approval center

``` text
Implement three useful starter automations using the workflow engine:
1. New lead → assess fit → draft outreach → human approval.
2. New email reply → classify → suggest next action → create task for uncertain or positive replies.
3. Follow-up due → prepare draft or reminder → approval if sending is enabled.

Create an Approval Center showing pending actions, target record, proposed change/message, supporting context, requester/workflow, and expiration status. Actions: approve, edit then approve, reject, and cancel where applicable.

Safety rules:
- Approval must bind to the exact proposed action and draft version; if the payload changes, require approval again.
- Approval expires or becomes invalid when the recipient is suppressed, the account is disconnected, or the workflow version/config changes in a way that affects the action.
- Rejecting an action must not silently requeue it.
- Record who approved/rejected, when, and why if provided.
- Default workflows to draft/test mode and approval-first sending.
- Include pause-all-automations control and per-workflow pause.

Test approval races, changed drafts, revoked connections, suppression changes, expiry, and unauthorized approval attempts.
```

## MVP Prompt 14 --- Integrations page and connector status

``` text
Build the Integrations area around a connector registry, not a hard-coded grid of logos.

For MVP, show only the email connector actually implemented and demo connectors clearly labeled as demo. Each connector card/detail page must show:
- Available capabilities.
- Connection status and account identity where appropriate.
- Permissions/scopes requested and why.
- Last successful sync/health check.
- Rate-limit or authentication warnings.
- Test connection, reconnect, and disconnect actions.
- Data-sync status and last error in user-friendly language.
- Links to provider setup instructions.

Define a connector interface and capability manifest so future integrations such as Outlook, Google Calendar, Google Sheets, Airtable, and Drive can be added without changing workflow-engine core logic. Ensure disconnect revokes tokens when supported and clears or disables credential references safely. Do not display “Connected” unless a real connection test has succeeded.
```

## MVP Prompt 15 --- Home dashboard, analytics, and audit trail

``` text
Build the MVP home dashboard and basic analytics from real application data.

Dashboard sections:
- Recommended next actions: overdue follow-ups, pending approvals, promising leads to review, failed workflow runs.
- Lead counts and fit distribution.
- Pipeline count/value by stage.
- Outreach activity and reply classifications, with metric definitions and date range.
- Workflow run success/failure and recent errors.
- Recent activity timeline.

Requirements:
- Use actual database queries; never hard-code production metrics.
- Provide useful empty states for a new workspace.
- Explain metric denominators and avoid implying delivery/open tracking when the provider does not supply it.
- Date filters respect workspace timezone.
- CSV export must honor permissions and filters.
- Audit trail for sends, approvals, suppression changes, integration connect/disconnect, workflow activation, and major CRM mutations.
- Redact secrets and unnecessary message content from audit/log records.

Add tests that compare aggregates to known fixtures and verify workspace isolation.
```

## MVP Prompt 16 --- Quality, security, accessibility, and release readiness

``` text
Perform a release-readiness pass on the entire MVP. Do not add major new features.

Inspect and test:
- Authentication/session security, CSRF strategy, CORS, rate limits, request validation, and secure headers.
- Workspace/tenant isolation on all API routes, background jobs, exports, and workflow runs.
- OAuth state/PKCE, secret storage, refresh/revocation, and disconnect behavior.
- HTML email rendering, uploaded files, CSV formula injection on exports, URL validation, and prompt injection boundaries.
- Suppression/opt-out enforcement at every send path.
- Duplicate sends, retry idempotency, job crash/recovery behavior, and workflow version pinning.
- Error handling, timeouts, loading states, keyboard accessibility, reduced motion, color contrast, mobile/tablet layouts, and light/dark themes.
- Database migrations, seed data separation, backups/restore notes, logs, metrics, health checks, and deployment configuration.
- Dependency vulnerabilities and license constraints using available project tooling.

Create unit, integration, and end-to-end smoke tests for critical journeys:
sign up → onboarding → create lead → create draft → approve → demo/real send adapter → receive or simulate reply → classify → create task → complete task; create workflow → validate → test → activate → inspect run.

Fix issues found, run all checks, and produce docs/RELEASE_CHECKLIST.md with verified items, unverified external prerequisites, rollback steps, and known limitations. Do not claim production readiness if provider credentials, backups, monitoring, or critical security checks remain unverified.
```

### MVP completion gate

Do not start broad post-MVP work until these are true:

-   A freelancer can sign in and complete onboarding.
-   Profile facts can be reviewed and used in a draft without invention.
-   Leads and tasks persist correctly and are workspace-isolated.
-   Demo mode works end to end; any live email integration is explicitly
    verified or marked unconfigured.
-   Suppression is enforced server-side.
-   A workflow can be built, validated, tested, activated, and inspected
    through durable run history.
-   Failures are visible and do not cause duplicate sends.
-   Tests, local setup, migrations, and documentation are usable by
    another developer.

------------------------------------------------------------------------

# Part IV --- Post-MVP prompts for the full-fledged application

## Full product roadmap

Build these phases incrementally, based on user feedback and reliability
data:

1.  Production-grade workflow execution and observability.
2.  Expanded integrations.
3.  Campaigns and sequence management.
4.  Advanced lead research/enrichment with compliant sources.
5.  Proposals and deal conversion.
6.  Team workspaces and permissions.
7.  Advanced AI workspace and evaluations.
8.  Desktop application.
9.  Analytics, billing, and governance.
10. Performance, accessibility, security, and operational hardening.

## Full Prompt 1 --- Durable workflow execution at production scale

``` text
Upgrade the MVP workflow engine into a production-grade execution system. First measure current failure modes and document why the current queue is insufficient or sufficient. Select a durable orchestration solution appropriate for long-running workflows—evaluate Temporal or an equivalent rather than adopting it blindly.

Implement:
- Durable timers and waiting states.
- Version-pinned runs, workflow replay strategy, retries, cancellation, timeouts, and compensation where possible.
- Concurrency controls per workspace, connector, and workflow.
- Rate limits and quotas by connector/action.
- Idempotency ledger for external side effects.
- Dead-letter queue, retry UI, safe replay, and failure categorization.
- Worker heartbeats and crash recovery.
- Pause/resume, scheduled runs, manual runs, webhook triggers, and event deduplication.
- Run retention policy and archival.
- Distributed tracing/correlation IDs and metrics.
- Secrets-safe structured logs.
- Backpressure and overload behavior.
- Schema migration strategy for workflow definitions and node versions.
- Per-workspace usage controls and kill switch.

Prove correctness with fault-injection tests: kill a worker between steps, expire a credential mid-run, timeout after a provider accepted a send, duplicate a webhook, and resume an approval after a deployment. Demonstrate that external actions are not duplicated and ambiguous outcomes are surfaced honestly.
```

## Full Prompt 2 --- Workflow builder power features and template library

``` text
Expand the workflow editor into a polished automation studio.

Add:
- Reusable subflows with typed inputs/outputs.
- Workflow folders, tags, search, ownership, favorites, duplicate, import/export, and template gallery.
- Node versions and migration notices.
- Branch merging where semantics are unambiguous, parallel branches with explicit join policies, loops only with hard iteration limits, and reusable error handlers.
- Expressions with a safe, sandboxed expression language; do not evaluate arbitrary JavaScript.
- Data mapping, transformations, text/date/number helpers, and schema validation.
- Secret references that are masked and cannot be read back to the browser.
- Webhook trigger management, signature verification, replay protection, and secret rotation.
- Schedule editor with timezone, daylight-saving behavior, and missed-run policy.
- Test fixtures, mock connector responses, dry-run mode, and environment-specific test data.
- Execution timeline, node-level duration, inputs/outputs, retry attempt history, and log search.
- Version comparison, rollback, activation confirmation, and impact preview.
- Collaboration-safe autosave and conflict resolution.

Use a capability-driven node registry. Every node must declare config schema, input/output schema, required permissions, retry/idempotency behavior, side-effect level, and test strategy. Add comprehensive tests for graph validation, upgrades, and concurrency.
```

## Full Prompt 3 --- Expanded integration framework

``` text
Expand integrations through a reusable connector SDK. Prioritize only providers with verified API access, stable documentation, and user demand.

Initial candidates:
- Microsoft Outlook email and calendar.
- Google Calendar.
- Google Sheets.
- Airtable.
- Google Drive.
- Slack or equivalent notifications.
- Generic webhook and HTTP request action for advanced users.

For every provider:
1. Review official documentation and terms before implementation.
2. Define minimum OAuth scopes and capability manifest.
3. Implement server-side authorization, callback validation, token refresh/revocation, secret storage, health checks, and disconnect.
4. Implement pagination, cursor sync, webhook verification, retries, rate limits, and idempotency.
5. Map provider records into normalized domain models while preserving external IDs and provenance.
6. Provide test mode, connector diagnostics, and useful errors.
7. Add mocked contract tests and sandbox/live smoke tests where available.
8. Document setup, scopes, provider limitations, rate limits, and data retention.

Do not create fake working states or silently use demo data when a live provider fails. Each connector must declare which triggers, actions, and search capabilities it actually supports.
```

## Full Prompt 4 --- Campaigns and multi-step outreach sequences

``` text
Build a complete campaign and sequence module on top of the CRM, email provider, approval center, and durable workflow engine.

Features:
- Campaign creation wizard: goal, audience, filters, exclusions, sender, schedule, sequence steps, approval mode, and review.
- Sequence editor for email steps, delays, conditions, manual tasks, and stop rules.
- Template library with variables, fallbacks, plain-text alternative, and preview against real lead data.
- Recipient enrollment state machine and event history.
- Global and campaign-specific suppression; opt-out, bounce, reply, and stop-condition handling.
- Sending windows, timezone-aware scheduling, daily limits, provider throttles, and pause/resume.
- Test sends to verified internal addresses.
- Approval queue and immutable approval snapshot per message.
- Per-recipient timeline and campaign audit history.
- Metrics: attempted, accepted by provider, delivered if confirmed, bounced, replies, positive replies, opt-outs, and booked meetings where measured.
- Clear explanation of measurement limitations; do not overstate opens or deliverability.
- Prevent duplicate enrollment and duplicate send attempts.
- Enforce relevant laws, provider policies, suppression, and unsubscribe requirements.

Default new campaigns to draft and approval-required. Do not add features designed to evade spam detection, rotate identities to bypass limits, or conceal sender identity.
```

## Full Prompt 5 --- Compliant lead research, import, and enrichment

``` text
Build a lead research and enrichment workspace that improves data quality without bypassing access controls or source terms.

Features:
- Import from CSV and verified integrations.
- Research brief from user-provided company domains, notes, or authorized data providers.
- Source citations/URLs, retrieved timestamp, and confidence for each enrichment field.
- Separate confirmed facts, inferred signals, and unknown values.
- Fit score explanation based on the freelancer's profile and configured criteria.
- Duplicate detection across emails, domains, and normalized names, with merge preview and undo strategy.
- Data freshness indicators and re-enrichment schedule.
- User-configurable exclusions and do-not-contact controls.
- Manual review before a lead enters an active outreach sequence.
- Export and correction workflow.

Use official APIs or sources whose terms permit the intended use. Do not scrape login-protected pages, defeat rate limits, circumvent robots/access controls, or infer sensitive personal attributes. Never fabricate a source or present a model guess as a fact. Add provenance tests and a way to delete imported data.
```

## Full Prompt 6 --- Advanced inbox and conversation intelligence

``` text
Upgrade the Inbox into a reliable conversation workspace.

Add:
- Provider sync health and conflict resolution.
- Unified thread view across supported connected accounts.
- Labels, assignments, saved views, bulk archive/mark read, and search.
- AI summaries, intent classification, objection extraction, urgency, and suggested next action.
- Suggested replies grounded in approved freelancer facts and conversation context.
- Confidence thresholds, explainability, source snippets, and human correction feedback.
- Conversation-to-lead/company/opportunity matching with a review queue for ambiguous matches.
- Follow-up reminders based on user-defined policies, not opaque autonomous assumptions.
- Rules for out-of-office, unsubscribe, bounce, referral, not-now, and negative responses.
- Stop conditions and global suppression checks across every campaign and workflow.
- Thread timeline and audit history.
- Privacy settings controlling whether message content is sent to each AI provider.

Build an evaluation dataset with representative, anonymized examples. Measure classification precision/recall and draft quality. Allow the user to correct categories and exclude those corrections from training/provider retention where supported. Keep the send button and approval status explicit.
```

## Full Prompt 7 --- Opportunity management, proposals, and deal closure

``` text
Expand Pipeline into a full opportunity and proposal workspace.

Features:
- Custom pipelines and stage definitions per workspace.
- Deal value/currency, probability, target close date, source, owner, and next action.
- Stage-specific required fields and automation triggers.
- Proposal brief generated from approved profile facts, discovery notes, scope, deliverables, assumptions, exclusions, milestones, and payment terms supplied by the user.
- Reusable proposal templates and version history.
- Human review before export or sharing.
- Export to PDF or document formats using a maintained document-generation approach.
- Proposal status and activity tracking; integrate e-signature only through a verified provider.
- Meeting notes and follow-up tasks.
- Won/lost reasons, loss competitor only if user-entered, and feedback loop for lead-fit criteria.
- Revenue forecast with transparent assumptions.

Do not invent pricing, guarantees, references, legal terms, or project outcomes. Mark missing required proposal facts. Add permissions, versioning, audit history, and tests for currency/date handling.
```

## Full Prompt 8 --- AI workspace, knowledge retrieval, and evaluations

``` text
Build the advanced AI Workspace.

Features:
- Freelancer knowledge library with source links, tags, approval, versioning, and deletion.
- Document ingestion only for supported formats, with file size/type limits, malware scanning, and visible processing state.
- Chunking and retrieval strategy appropriate to the data size; cite source items used in generated content.
- Reusable prompt templates and task-specific model configuration.
- Model/provider routing and fallback policy.
- Evaluation suite for lead scoring, reply classification, extraction, summaries, and outreach drafts.
- Prompt version history, regression tests, golden examples, and review of model changes.
- Usage and estimated-cost dashboard by task and provider.
- Redaction controls, retention configuration, and provider-specific data handling disclosures.
- Feedback controls for useful/not useful and correction capture.
- Structured outputs and deterministic validation for any action-driving result.

Treat retrieved documents and emails as untrusted data. Prevent cross-workspace retrieval. Do not let a retrieved document authorize actions or override system rules. Make citations traceable to actual knowledge items. Add adversarial tests for prompt injection and data leakage.
```

## Full Prompt 9 --- Team workspaces, roles, and approvals

``` text
Introduce organizations and multi-user workspaces without breaking personal workspaces.

Features:
- Create organization, invite member, accept/decline invitation, remove member, transfer ownership, and leave workspace.
- Roles such as Owner, Admin, Member, and Read-only; document the permission matrix before implementation.
- Resource-level checks for leads, conversations, campaigns, workflows, approvals, integrations, exports, billing, and audit logs.
- Shared versus personal workflows and profile/knowledge boundaries.
- Team task assignment, ownership transfer, and activity attribution.
- Approval policies configurable by action type, workflow, and role.
- Audit log with actor, action, target, timestamp, and redacted change summary.
- Workspace-level integration ownership and explicit reconnect policy.
- Invite rate limits, invitation expiry, and safe handling of departed members.
- Tests for privilege escalation, cross-workspace IDs, revoked membership, and approval authorization.

Do not rely on hidden UI controls for security. Enforce all permissions on the server and in background workers.
```

## Full Prompt 10 --- Electron desktop application

``` text
Create the Electron desktop app as a secure companion to the Next.js web application, sharing domain contracts, design tokens, and reusable UI where practical.

Features:
- Sign-in and session handling consistent with the web app.
- Main app navigation and responsive desktop layouts.
- Safe deep links and OAuth callback handling.
- System notifications for approved notification categories.
- Optional tray/minimize behavior and startup preference, with explicit user controls.
- Secure updater and signed packaging strategy.
- Crash reporting with consent and redaction.
- Online/offline status and clear sync/error states.
- Desktop-specific settings only where they provide real value.

Security requirements:
- contextIsolation enabled, nodeIntegration disabled, restrictive Content Security Policy, minimal preload bridge, explicit IPC allowlist, validated IPC payloads, safe external URL handling, and no arbitrary renderer-to-main command execution.
- Never expose API secrets or unrestricted Node APIs to the renderer.
- Do not persist access tokens in plain text.
- Document OAuth flow and platform-specific storage.
- Test packaged builds on supported operating systems and keep signing/notarization requirements explicit.

Reuse the web product; do not fork the business logic into a separate desktop implementation.
```

## Full Prompt 11 --- Billing, usage, plans, and entitlements

``` text
Add a billing and usage subsystem only after product usage and pricing assumptions are validated.

Requirements:
- Payment-provider abstraction so the application is not hard-wired to one vendor.
- Plans, entitlements, limits, subscription state, invoices/receipts metadata, and usage records.
- Meter AI usage and workflow actions consistently, using provider-reported usage where available and labeled estimates otherwise.
- Workspace-level quotas, alerts, and graceful limit handling.
- Idempotent webhook processing, signature verification, reconciliation jobs, and audit history.
- Upgrade/downgrade/cancel states and clear effective dates.
- Do not store card details; rely on the payment provider's compliant hosted flows.
- Keep internal usage records as the source for product enforcement while reconciling with billing-provider records.
- Handle failed payments, grace periods, refunds, and webhook reordering.

Do not assume a specific payment processor is available in every country. Verify regional availability, payout support, tax requirements, and legal obligations before enabling live billing. Test proration and race conditions before production.
```

## Full Prompt 12 --- Advanced analytics and reporting

``` text
Expand analytics with trustworthy definitions and drill-downs.

Add:
- Funnel from lead created → qualified → replied → meeting → proposal → won.
- Campaign performance with consistent event definitions and cohort/date filters.
- Pipeline aging, stage conversion, expected revenue, and win/loss analysis.
- Workflow reliability, failure reasons, node latency, retries, and connector health.
- AI task usage, latency, evaluation scores, and estimated costs.
- Team workload and follow-up completion if team features are enabled.
- Saved reports and scheduled delivery only after notification/email permissions are implemented.
- CSV export with server-side authorization and audit.
- Data freshness indicators and explicit handling of missing provider events.

Keep raw event definitions documented. Prevent double counting from duplicate webhooks and retries. Add fixture-based tests for each aggregate and timezone boundary tests. Avoid causal claims unless the data and methodology support them.
```

## Full Prompt 13 --- Security, privacy, compliance, and administration

``` text
Conduct a security and privacy engineering phase for the full product.

Review:
- Threat model, trust boundaries, tenant isolation, and role permissions.
- OAuth scopes, credential storage/encryption, rotation, revocation, and access logs.
- Session security, CSRF, CORS, CSP, secure headers, and rate limiting.
- SSRF defenses in webhook/HTTP nodes, DNS rebinding, redirects, private IP ranges, and cloud metadata endpoints.
- Prompt injection and data exfiltration paths through email, documents, webhooks, and connector payloads.
- XSS and unsafe HTML rendering, file upload validation, malware scanning, and CSV formula injection.
- Data retention, deletion, export, backups, and restore drills.
- Logging redaction, audit integrity, incident response, and secret scanning.
- Dependency and container scanning, least-privilege service accounts, and production configuration.
- Abuse prevention, email suppression, unsubscribe handling, and provider policies.

Produce a threat model, data inventory, retention matrix, incident response checklist, and security test suite. Do not claim legal compliance merely because features exist; identify jurisdiction-specific obligations for qualified review.
```

## Full Prompt 14 --- Production deployment, observability, and operations

``` text
Prepare Freelancer OS for production deployment with a documented, repeatable operating model.

Implement or document:
- Separate development, staging, and production environments.
- Secret management, environment validation, database migrations, and deployment ordering.
- CI for lint, type checks, unit/integration tests, dependency scanning, and builds.
- Health/readiness endpoints and worker health monitoring.
- Structured logs, metrics, traces, alert thresholds, and request/run correlation IDs.
- Error tracking with sensitive-data scrubbing.
- Database backups, retention, restore drills, and recovery objectives.
- Queue depth, job age, retry rate, connector error rate, AI latency/cost, and email send outcomes dashboards.
- Safe deploy/rollback strategy and workflow schema compatibility.
- Feature flags, maintenance mode, global automation pause, and provider circuit breakers.
- Capacity testing, load testing, and performance budgets.
- Runbooks for provider outage, OAuth expiry, queue backlog, duplicate send risk, data incident, and database restore.

Use infrastructure appropriate to the chosen host and budget; do not introduce unnecessary services. State exactly which operational controls are implemented and which remain manual.
```

## Full Prompt 15 --- Performance, accessibility, UX polish, and product feedback

``` text
Perform a product-quality pass using real usage flows and representative data.

Review:
- Large lead tables, search/filter latency, pagination, database indexes, and query plans.
- Inbox sync, workflow canvas rendering, long run histories, and analytics queries.
- Client bundle size, caching, server rendering, and network waterfall.
- Accessibility using keyboard-only workflows, screen-reader labels, contrast checks, and reduced-motion behavior.
- Responsive layouts and usability at laptop/tablet widths.
- Empty/error/loading states and actionable error messages.
- Bulk operations, undo where safe, destructive confirmations, and unsaved changes.
- Onboarding completion and time-to-first-value.
- Product feedback capture and feature flags for experiments.

Measure before optimizing. Add realistic large fixtures and performance budgets. Do not remove safety checks or weaken authorization to improve speed. Summarize measurable improvements and any remaining bottlenecks.
```

------------------------------------------------------------------------

# Part V --- End-to-end validation prompts

## Validation Prompt A --- Critical user journeys

``` text
Act as a QA lead. Build an end-to-end test plan and automate the highest-risk user journeys:
1. New user → workspace → onboarding → approved profile facts.
2. CSV import → duplicate review → lead detail → task creation.
3. Lead fit assessment → draft generation → approval → demo send.
4. Reply event → idempotent sync → classification → suggested response → follow-up task.
5. Build workflow → validation errors → fix graph → test payload → activate → run → inspect logs.
6. Pause workflow → cancel a run → retry a safe failure.
7. Add suppression entry → attempt to send from every available path → confirm every path is blocked.
8. Disconnect email account during a queued run → verify safe failure and no credential leakage.
9. Attempt cross-workspace access using guessed IDs → confirm access is denied.
10. Simulate provider timeout after an ambiguous send result → confirm the system avoids blind duplicate sending.

Use deterministic fixtures, isolate tests from real external services, and run real-provider smoke tests only in a controlled sandbox with explicit configuration. Report flaky tests and gaps honestly.
```

## Validation Prompt B --- AI quality and safety

``` text
Create an AI evaluation suite using synthetic or anonymized cases for lead fit, reply classification, extraction, summaries, and outreach drafting.

Include:
- Missing data and conflicting data.
- Unsubscribe and negative replies.
- Out-of-office and referrals.
- Sarcasm, short replies, and ambiguous intent.
- Prompt-injection attempts inside emails and documents.
- Unsupported portfolio claims and requests for invented credentials.
- Cross-workspace retrieval attempts.
- Malformed structured outputs and provider timeouts.
- Different writing tones and languages supported by the product.

Score classification precision/recall, schema validity, factual grounding, safe abstention, and draft usefulness. Establish acceptance thresholds before changing prompts/models. Ensure low-confidence cases route to review. Store evaluation fixtures without unnecessary real personal data.
```

## Validation Prompt C --- Documentation and handoff

``` text
Prepare a developer and operator handoff package:
- Product overview and scope.
- Architecture diagram in Mermaid and domain glossary.
- Local setup, environment variables, migrations, seed data, and test commands.
- Authentication, workspace isolation, OAuth, and secret-storage explanation.
- API contract and error conventions.
- Workflow graph schema, node registry, run states, retries, idempotency, and versioning.
- How to add a connector and an AI provider.
- Deployment, rollback, backup/restore, observability, and incident runbooks.
- Known limitations, external setup prerequisites, and roadmap.
- Manual verification guide for the main journeys.

Check every documented command against the repository. Remove stale instructions and do not document unimplemented features as complete.
```

------------------------------------------------------------------------

# Part VI --- Suggested implementation order

  ------------------------------------------------------------------------
                         Order Phase                 Outcome
  ---------------------------- --------------------- ---------------------
                             1 Prompt 0 + MVP 1      Architecture and
                                                     runnable scaffold

                             2 MVP 2--4              Design system, auth,
                                                     workspace,
                                                     database/API

                             3 MVP 5--7              Profile, leads,
                                                     pipeline, tasks

                             4 MVP 8--10             AI adapter, email
                                                     connector, inbox

                             5 MVP 11--13            Durable MVP
                                                     workflows, editor,
                                                     approval center

                             6 MVP 14--16            Integrations UI,
                                                     analytics,
                                                     security/release gate

                             7 Full 1--3             Production
                                                     orchestration and
                                                     integrations

                             8 Full 4--7             Campaigns, lead
                                                     research, inbox
                                                     intelligence,
                                                     proposals

                             9 Full 8--10            AI knowledge, teams,
                                                     desktop

                            10 Full 11--15           Billing, analytics,
                                                     governance,
                                                     operations, polish

                            11 Validation A--C       End-to-end
                                                     verification and
                                                     handoff
  ------------------------------------------------------------------------

## Recommended weekly cadence

-   **Planning:** Pick one prompt-sized milestone and define acceptance
    criteria.
-   **Implementation:** Have the agent make a small, reviewable change.
-   **Verification:** Run checks and manually test the feature.
-   **Hardening:** Add edge cases, permissions, failure states, and
    observability.
-   **Documentation:** Update status and decisions.
-   **Checkpoint:** Commit only after the milestone passes.

## Final instruction to the coding agent

``` text
Treat this playbook as the product direction, not permission to implement everything at once. Always prioritize a coherent, testable vertical slice over a broad collection of disconnected screens. Keep the web app, API, workflow engine, and future desktop client aligned through shared contracts. Make external side effects explicit, observable, permission-checked, and idempotent. Prefer honest limitations and safe defaults over fake functionality. After each phase, summarize what works, what was verified, what remains, and the exact next step.
```

------------------------------------------------------------------------

## Final note

The most important architectural boundary is this: **React Flow edits
workflow definitions; the backend validates and executes them.** The
browser must never be responsible for keeping long delays alive,
enforcing suppression, storing provider secrets, or guaranteeing that an
external action runs exactly once. Build these boundaries into the MVP
so the full product can grow without rewriting its foundation.
