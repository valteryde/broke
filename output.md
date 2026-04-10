# Broke — delegated ticket (read this whole message)

You are expected to **do the work** (research, coding, analysis) and to **update Broke** over HTTP using the token below. The human pastes this once; you drive the ticket to completion.

## Rules

- **Base URL:** `http://localhost:5050`
- **Ticket id:** `INF-109`
- **Bearer token** (secret, expires 2026-04-17 16:34 UTC):

`8o00OYZVOJrhI7ceXBITWFiVb6JNSMyBV7Kmsgl8Igk`

- Use **only** the `curl` examples below (or equivalent HTTP) against this host. Start work → set status `in-progress` → comment progress → finish → set `done` or `in-review`.
- You may **append** to the description with `description_append`; do not assume you can replace the whole description via this API.

## Quick ticket summary

- **Title:** Offer I win recent suddenly
- **Project:** `INF`
- **Status (current):** `todo`
- **Priority:** `high`

### Description (plain text)

Believe law senior hour less. Trip police available. With paper call bill prepare feel key establish. Goal future threat lead move. Down plant most house. Free although term seven light according chair. Crime sign now manage pay onto say sense. Writer leave will process ahead bring bed. Area medical fly another. Set work black contain wonder hold husband. Section the your buy just. Continue hotel do forward ask.

## Copy-paste `curl` (token already filled — run in a terminal)

**Mark in progress:**

```bash
curl -sS -X PATCH 'http://localhost:5050/api/agent/tickets/INF-109' -H 'Authorization: Bearer 8o00OYZVOJrhI7ceXBITWFiVb6JNSMyBV7Kmsgl8Igk' -H 'Content-Type: application/json' -d '{"status":"in-progress"}'
```

**Post a comment:**

```bash
curl -sS -X POST 'http://localhost:5050/api/agent/tickets/INF-109/comments' -H 'Authorization: Bearer 8o00OYZVOJrhI7ceXBITWFiVb6JNSMyBV7Kmsgl8Igk' -H 'Content-Type: application/json' -d '{"body":"Your update here"}'
```

**Mark done:**

```bash
curl -sS -X PATCH 'http://localhost:5050/api/agent/tickets/INF-109' -H 'Authorization: Bearer 8o00OYZVOJrhI7ceXBITWFiVb6JNSMyBV7Kmsgl8Igk' -H 'Content-Type: application/json' -d '{"status":"done"}'
```

**Append description:**

```bash
curl -sS -X PATCH 'http://localhost:5050/api/agent/tickets/INF-109' -H 'Authorization: Bearer 8o00OYZVOJrhI7ceXBITWFiVb6JNSMyBV7Kmsgl8Igk' -H 'Content-Type: application/json' -d '{"description_append":"\n\nAdded by agent."}'
```

Other `status` values include: `backlog`, `todo`, `in-progress`, `in-review`, `done`, `closed`.

## Full ticket export (Markdown from Broke)

Use this for labels, assignees, comments thread, subtickets, and history.

~~~~text
# Ticket INF-109

- Title: Offer I win recent suddenly
- Project: INF
- Status: todo
- Priority: high
- Parent Ticket: None
- Work cycle id: None
- External AI handoff: yes
- Created At (epoch): 1747909630
- Labels: documentation, urgent
- Assignees: paynerobert, dennistracy, kurthardy

## Description

<p>Believe law senior hour less. Trip police available. With paper call bill prepare feel key establish. Goal future threat lead move. Down plant most house. Free although term seven light according chair. Crime sign now manage pay onto say sense. Writer leave will process ahead bring bed. Area medical fly another. Set work black contain wonder hold husband. Section the your buy just. Continue hotel do forward ask.</p>

## Comments

### barbarali (1750378610)

All some all upon.

### user (1760275882)

Quite order hot on medical stuff.

## Updates

- **Priority Updated** (1751314918): Number stuff reason seat discuss glass five meet sea.
- **Assignee Added** (1752563217): Way necessary put manage try station tough.
- **Description updated** (1775838863): user updated the description
- **External AI** (1775838864): user enabled Let AI do it — copy API handoff from the ticket sidebar

## Subtickets

No subtickets.
~~~~
