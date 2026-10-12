# Freelancer OS — Project

> Working name; the display name is configurable via `NEXT_PUBLIC_APP_NAME`.

## Product
Freelancer OS is an AI-assisted business-development and workflow-automation workspace for independent
freelancers, consultants and small studios. It combines a freelancer profile/knowledge base, lead and
relationship management, AI-assisted outreach and inbox workflows, visual workflow automation, and
integrations/insights — with the freelancer in control (human-in-the-loop by default).

The full blueprint and the staged build prompts live in
[`freelancer_os_build_prompt_playbook.md`](../freelancer_os_build_prompt_playbook.md).

## Users
Independent freelancer, consultant/specialist, small studio, automation power user.

## MVP scope (one freelancer, personal workspace)
Authentication, onboarding and profile; leads/companies/contacts with CSV import; small pipeline; email
adapter (real OAuth only when credentials exist, otherwise a labelled demo connector); inbox with AI reply
classification and draft suggestions; approval-first sending with suppression checks; a small visual workflow
builder with durable runs; tasks/reminders; basic analytics and audit trail; tests, Docker dev environment, docs.

## Explicit non-goals for the MVP
Complex team permissions and billing, dozens of live integrations, autonomous prospect discovery from arbitrary
sites, unrestricted bulk sending, a custom distributed workflow engine, desktop-only features, e-signing,
advanced forecasting and enterprise governance.

## Principles (summary)
Human-in-the-loop · explainable AI (sourced facts vs guesses) · reliable automation (idempotency, retries,
visible failures) · privacy and least privilege · honest integrations (never show "Connected" without a
successful test) · one accessible, responsive design system.

## Build plan
Follow the playbook's MVP prompts in order; each phase ends with updated docs and passing checks.

| # | Phase | Status |
|---|-------|--------|
| 1 | Repository scaffold and local development | **Done** |
| 2 | Design system, app shell, navigation | **Done** |
| 3 | Authentication, workspace, onboarding | **Done** |
| 4 | Domain model and API foundations | **Done** |
| 5 | Freelancer profile and approved knowledge | **Done** |
| 6 | Leads, contacts, companies, CSV import, fit scoring | **Done** |
| 7–16 | Pipeline, AI, email, inbox, workflows, approvals, integrations, analytics, release readiness | Not started |

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for details.
