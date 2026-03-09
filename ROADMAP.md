# Broke Product Roadmap (March 2026)

## Product Direction
This roadmap reflects the current product philosophy:
- One team, mostly equal roles (keep permissions simple).
- Stay lightweight and focused (do not become Jira/Zapier).
- SQLite remains a valid primary database target for small/medium teams.
- Prioritize practical quality-of-life and operational confidence.

## Confirmed Scope Decisions
- Roles: Keep simple. Maintain current admin/non-admin model, avoid complex RBAC for now.
- Security hardening: Yes, high priority.
- Subtasks/subtickets: Yes, high priority.
- Automation: Useful, but only lightweight built-in rules (not a full automation platform).
- Public API: Nice to have, not required for this roadmap.
- Error tracking depth: Major focus area.
- Reporting + ticket export: High value.
- Multi-org: Out of scope.
- Polish: In scope and important.

---

## Priority Buckets

## P0 (Do First)
1. Security hardening baseline
2. Subtickets (MVP)
3. Error tracking improvements (phase 1)
4. Reporting + ticket export (MVP)

## P1 (Do Next)
1. Lightweight automation rules
2. Error tracking improvements (phase 2)
3. UX polish pass

## P2 (Later, optional)
1. Public API foundation
2. Advanced reporting and analytics depth

---

## Phase Plan

## Phase 1: Foundation and Safety (2-3 weeks)
Goal: make production usage safer without changing product complexity.

### 1) Security Hardening Baseline
- Replace hardcoded app secret with environment-based secret.
- Enforce secure cookie/session defaults.
- Add CSRF protection for form and JSON mutation endpoints.
- Add stricter authorization checks on destructive/admin-sensitive routes.
- Add basic security headers (CSP-lite, X-Frame-Options, etc.).
- Expand tests for authz boundaries and CSRF behavior.

Definition of done:
- No hardcoded secret in runtime app config.
- Mutation routes reject invalid/absent CSRF.
- Existing auth tests pass and new authz tests cover key admin and destructive flows.

### 2) Reporting + Export MVP
- Add ticket export from ticket detail page:
  - Markdown export
  - JSON export
- Add basic report page with:
  - Tickets created/closed over time
  - Triage backlog size and age
  - Error groups unresolved/resolved trend
- Add CSV export for report tables where useful.

Definition of done:
- Any single ticket can be exported from UI in at least Markdown + JSON.
- Report page loads quickly and works for all projects + project-specific view.

---

## Phase 2: Workflow Depth (2-4 weeks)
Goal: improve team execution quality with minimal added complexity.

### 3) Subtickets (MVP)
Data model direction:
- Add parent-child relationship on tickets (e.g. `parent_ticket_id` nullable).
- Restrict depth to 1 level initially (ticket -> subtickets) to keep UI/querying simple.

Feature scope:
- Create subticket from ticket detail.
- Show subticket list on parent ticket with status and assignee.
- Progress indicator on parent (e.g. `3/5 subtickets done`).
- Optional auto-close suggestion: if all subtickets closed, prompt to close parent.

Definition of done:
- Subtickets can be created, edited, searched, and navigated.
- Parent ticket clearly shows child status rollup.
- No regressions in existing ticket flows.

### 4) Lightweight Automation (Not Zapier)
Answer to necessity question:
- Full automation engine is not necessary.
- A few built-in rules provide most value with low complexity.

MVP automation rules:
- On GitHub PR opened referencing ticket -> status `in-review`.
- On PR merged or commit `fixes #ID` -> status `closed`.
- On anonymous intake -> always `triage` (already present, keep).
- Optional: when ticket moved out of `triage` and no assignee, auto-assign actor.

Implementation style:
- Keep rule set hardcoded/config-light in app settings.
- No generic workflow builder UI.

Definition of done:
- 3-5 high-value automations are reliable and test-covered.

---

## Phase 3: Error Tracking Depth + Polish (3-4 weeks)
Goal: improve debugging effectiveness and daily product feel.

### 5) Error Tracking Improvements (Large Todo)
Phase 1 enhancements:
- Better filters (project, part, environment, release, status).
- Error triage actions (ignore/unignore, resolve/reopen) from list and detail views.
- Link error groups to tickets more visibly and bi-directionally.
- Improve grouping confidence with additional fingerprint heuristics where needed.

Phase 2 enhancements:
- Regression detection (error resolved then reappears).
- Basic alerting thresholds (e.g. spike in occurrences in last N minutes).
- Release-aware views for “new in release” style tracking.

Definition of done:
- Teams can triage error queues quickly and identify regressions with low manual effort.

### 6) Product Polish Pass
- Improve nav discoverability and in-page empty states.
- Add keyboard shortcuts for common actions (new ticket, search, status change).
- Reduce UI friction on ticket detail edits and comment interactions.
- Improve loading/feedback states for async actions.
- Tighten copy consistency across settings/tickets/errors/changelog.

Definition of done:
- Core workflows feel fast, coherent, and predictable.

---

## Optional Phase 4: API (If Demand Appears)
Goal: enable integrations without overcommitting maintenance burden.

Minimal API slice:
- Read tickets, create ticket, update status, add comment.
- Token auth using existing token model.
- Basic pagination + filtering.
- Versioned path prefix (e.g. `/api/v1`).

Only start if:
- At least one real integration need exists (internal script, CI integration, external dashboard).

---

## Suggested Execution Order (Backlog Seeds)
1. `security`: move app secret to env + cookie/session hardening.
2. `security`: CSRF support + tests for mutation endpoints.
3. `reporting`: ticket export (markdown/json) from ticket detail.
4. `reporting`: reports page (created/closed, triage aging, unresolved errors).
5. `tickets`: DB migration for subtickets (`parent_ticket_id`).
6. `tickets`: subticket UI on ticket detail + create flow.
7. `tickets`: parent rollup progress and optional close prompt.
8. `automation`: implement 3-5 built-in rules + tests.
9. `errors`: filter and triage UX improvements.
10. `errors`: regression/spike detection baseline.
11. `polish`: UX quality pass and consistency cleanup.

---

## Risks and Guardrails
- Avoid feature creep: no custom workflow builder, no multi-org in this cycle.
- Keep schema changes incremental and migration-backed.
- Preserve performance on SQLite by indexing new query paths.
- Require test coverage for every new mutation path.

---

## Success Criteria (Roadmap Complete)
- Product is safer to run in production (security hardening complete).
- Team can decompose work with subtickets without adding process overhead.
- Error triage is significantly faster and regression-aware.
- Managers/contributors can export tickets and view useful operational reports.
- UX feels polished in daily use.
