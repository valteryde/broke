# Anonymous intake spec

A reporter can file a triage ticket from `/anon` only after one email address is confirmed, and staff can tell that address what happened next. Behavior below is the contract. The narrative and file-level plan is `docs/anon-intake-plan.md`.

## Scope

- In: `/anon`, `/api/anon/review`, `/api/anon/submit`, `/anon/verify/<token>`, `/anon/track/<secret>`, reporter emails, the public timeline, and a staff “reply to reporter” action.
- In: tickets that already have `anonymous_secret`. New public rows apply from this change forward.
- Out: `/api/tickets/intake/ai/chat`, `/api/tickets/intake/ai/suggest`, the triage chat UI, and `suggest_intake_from_message`.
- In: a report check before submit that writes nothing and says what must be added.
- In: one intake-assist pass after the ticket row is created.
- Out: creating a Broke user from a confirmed address.
- Out: a settings form-builder. The questions are fixed.
- Out: resend, and out: a reply box on the public tracking page.

## Form

- The first screen asks one question, with three choices: Problem, Feature, Improvement.
- Nothing else is on that screen. Choosing one opens the follow-ups for that kind.
- Going back to the choice keeps answers already entered for each kind.
- The follow-up screen is a narrow column. The kind’s first question is the heading. Each answer starts as a short line and grows. One example sits in the field as placeholder text.
- The short title comes after the answers, prompted as “What should we call this?”. It is required, 10–140 characters after trim. Each answer is required, 30–4000 characters.
- A picture and extra emails stay closed until the sender opens “Add a picture” or “Also notify someone”.
- The reply address is one line, asked as where to reply. Extra emails are optional, at most five.
- One image, optional: png, jpeg, webp, or gif, at most 2 MB.
- Problem asks “What is broken?” The example is a login page that rejects a reset password. The check still wants what was expected, where it happens, and who is affected.
- Problem also asks “What system is this on?” The example names a browser, operating system, and app version. That answer is required, 8–400 characters. The check wants a device, operating system, browser, or app version. “My computer” is not enough. Feature and improvement do not ask this.
- Feature asks “What is missing?”, “Why isn't the current system enough?”, and “What broken thing must this not copy?”. Each answer is required, 30–4000 characters. The check wants a thing that does not exist yet, the job people do today because it is missing, and the existing screen or workaround this must not repeat.
- Improvement asks “What do you do today?”, “What is actually wrong with that?”, and “What should change in the work?”. Each answer is required, 30–4000 characters. The check wants the current steps, the specific failure of those steps, and a change in the work. A new label or an extra screen that keeps the same steps is not enough.
- The form does not list projects, project ids, or a project picker. The tracking page does not show a project name or project id.
- No priority control.
- No rich-text editor.
- The form stays usable when outbound mail is not configured. Send files the ticket without asking for a confirmation.
- Anonymous mode off: `GET /anon` stays 403.

## Report check

- `POST /api/anon/review` writes nothing and sends no mail. It does not read or return emails.
- Limited to 30 requests an hour per IP. Anonymous mode off: 403.
- Structural failures return `ready: false` and one note per failed field. The model is not called.
- AI not configured, and the structure passes: `ready: true` and a review token. No model call.
- AI configured, and the structure passes: the model returns `ready`, a `headline` of at most 12 words, and one note per checked field, including fields that pass. A note is `{ field, ok, message }`.
- `message` is one sentence, at most 160 characters, with no line breaks and no markdown. When `ok` is false it says the one thing to add. When `ok` is true it says what is already clear.
- The response has no combined paragraph, no rewritten title, and no rewritten description.
- A problem report stays not ready while nobody could tell what broke and where it shows up, or while the system is only “my computer” with no product. An expected result, a version, and who else is affected are useful, and their absence does not fail a report that already has the break and a named app, site, browser, or device.
- A feature report stays not ready while the missing thing or the current job is still only a wish. It passes the “must not copy” answer when that answer names one real flaw, or says there is nothing existing to copy.
- An improvement report stays not ready while the current steps, one real cost of those steps, or the change in the work is missing. A new label or color that keeps the same steps stays not ready.
- The check does not ask again for a fact the current text already contains, and it does not ask for a fact the sender cannot know.
- A failed or unusable model call returns `ready: false` and one note with an empty `field`. The form shows that sentence as a form error and does not point it at a question. The keyword fallback is not used.
- A ready response includes `review_token`, valid for 30 minutes, bound to `kind` and that kind’s text answers. Emails and the image are outside the token.
- The submit button calls this check first. Submit is not called while `ready` is false.
- The form shows the headline as one line, then one row per note. Needs-work rows come first, then passing rows.
- A row is an icon, the question label, and that note’s sentence. The icon has no colored box. The list has no shadow.
- The same sentence appears under the matching input. Activating the row focuses that input.
- The notes are not concatenated into one block, and they are not shown in an alert.
- While the check runs, the list is replaced by the line “Reading your report”.
- A ready result keeps the passing rows visible, then submits. Editing an answer clears the list and the token.

## Submit

- Submit requires a `review_token` that matches the answers and has not expired. A missing, expired, or mismatched token stores nothing.
- Submit does not call the model.

- `POST /api/anon/submit` is limited to 10 requests an hour per IP.
- Anonymous mode off: 403, nothing stored.
- Outbound mail not configured: the ticket is created immediately. No draft, no contact rows, and the email fields are ignored.
- `kind` is required and is `problem`, `feature`, or `improvement`. A missing or unknown kind is rejected.
- The server requires the title and each required answer for the kind that was sent. A problem report requires what is broken and the system. A feature report requires what is missing, why the current system is not enough, and what broken thing it must not copy. An improvement report requires what people do today, what is wrong with that, and what should change in the work.
- Answers that belong to another kind are ignored. A system answer on a feature or improvement is ignored.
- Validation runs before any draft is written. Failures name the field.
- Emails are trimmed and lowercased. Reject values that are not a plain address. The same address once per draft. The primary is not also a copy.
- A client-supplied priority or project is ignored.
- At most three unconsumed, unexpired drafts for one primary address. The fourth is rejected and tells them a confirmation is already waiting.
- The server escapes the answers and stores the description HTML on the draft. The description starts with a summary, then each question and that question’s answer. The kind is marked on that HTML. The markup is headings and paragraphs, so the staff editor keeps it.
- The image, when present, is stored under uploads and referenced from that HTML.
- Primary mail is sent first and includes the title and a confirm link. If that send fails, the draft and its contacts are deleted and the request errors.
- Each extra address gets its own mail. That mail contains no title, no description, and no ticket id. If one of those sends fails, the draft remains and that contact stays unconfirmed.
- When outbound mail is not configured, submit creates the ticket immediately. It stores no draft, ignores email fields, and returns `{ "success": true, "pending": false, "track": "/anon/track/<secret>" }`. The browser opens that page.
- When outbound mail is configured, the success body is `{ "success": true, "pending": true }`.
- The success body contains no ticket id, no tracking secret, and no duplicate information.
- The browser shows a check-email step. It does not write a tracking secret to `localStorage` until the tracking page loads.

## Drafts and contacts

- A draft holds the payload, `created_at`, `expires_at` (24 hours), `consumed_at`, and later `ticket_id`.
- Each contact holds the draft, the email, role `primary` or `copy`, a SHA-256 of the mail token, `verified_at`, and later the ticket id.
- The raw token is only in the email.
- A draft is not a ticket and does not appear in intake.

## Confirm

- `GET /anon/verify/<token>` never creates a ticket, never sets `verified_at`, and never consumes the draft.
- Unknown token: invalid-link page.
- Expired, unconsumed draft: ask them to submit again.
- Valid token: a page with a confirm button.
- `POST /anon/verify/<token>` is limited to 30 requests an hour per IP.
- Primary confirm, draft still open and unexpired:
  - Exactly one ticket is created.
  - Id follows the existing `TRIAGE-N` sequence.
  - `project` is `TRIAGE`, `status` is `intake`, `priority` is `medium`, and `estimate_minutes` is unset.
- The confirm response does not wait on a model call.
  - `anonymous_secret` is generated at creation.
  - Description is the HTML stored on the draft.
  - The draft is consumed and points at that ticket.
  - The primary contact is verified and points at that ticket.
  - A second confirm of the same token redirects to the same tracking URL and does not create another ticket.
- Copy confirm before a ticket exists: set `verified_at` only.
- Copy confirm after a ticket exists: set `verified_at`, attach the ticket, and mail the tracking link once.
- Repeating a copy confirm does not send another mail.
- Expired and unknown tokens create nothing.

## Ticket side effects at creation

- An internal update row records creation and names the kind. Duplicate candidate ids, when the existing matcher finds them, are written only on that internal row.
- A public row says the report was received.
- `ANON_TICKET_SUBMITTED` is emitted to admins only after the ticket exists.
- The tracking mail goes to the primary and to every copy already verified. It includes the title and the tracking URL.

## Intake assist

- Runs only after primary confirm has created the ticket. The form, the draft, and a confirm that does not create a ticket do not call the model.
- Runs asynchronously. A second delivery for the same ticket does not score again.
- Does not rewrite the title or the description. Does not change status. Status stays `intake`.
- Does not call `suggest_intake_from_message` or `review_anon_report`, and does not use the keyword fallback.
- Does not show its reason to the reporter. The report check is the only model text the reporter sees, and that text is about their draft before submit.
- AI unconfigured, missing client, failed call, or unusable JSON: leave priority `medium`, estimate unset, and project `TRIAGE`. Write one internal row that scoring did not happen.
- A successful result may set:
  - Priority, only while the ticket is still `medium`, and only to `urgent`, `high`, `medium`, or `low`.
  - Estimate, only while `estimate_minutes` is null. Unparseable values and values over the existing four-week cap are skipped.
  - Project, only while the ticket is still `TRIAGE`, the id is an active project, and confidence is at least 0.8. Otherwise the project stays `TRIAGE` and the suggestion stays in the internal note.
- One internal row titled “Intake assist” records what was set, what was suggested, and the one-sentence reason.
- Confirmed addresses are not mailed about this pass.
- The public tracking page does not show that row, the estimate, or the reason. It continues to show the ticket’s stored priority.

## Tracking page

- `/anon/track/<secret>` 404s on an unknown secret, as today.
- It shows the title, the kind, status, created time, and the assembled description.
- Activity is public update rows only, oldest first.
- It does not show staff usernames, internal comments, the intake-assist note, the estimate, estimate or description edits, or duplicate candidate ids.
- The page tells the holder to keep the URL, and that confirmed addresses are mailed on status changes.

## Status mail

- Any status change on a ticket with `anonymous_secret` writes a public row: “Status is now {label}.” The label is the human form of the slug.
- That row contains no username.
- The same change still writes the existing internal row.
- Confirmed contacts for that ticket receive one status mail: label, one sentence, tracking link.
- The status mail contains no actor name and no project id.
- Tickets without `anonymous_secret` send no reporter mail.
- The ticket API, bot updates, and the agent API all do this.
- If `APP_BASE_URL` is unset when there is no request to copy a host from, the public row is still written, the mail is skipped, and a warning is logged.

## Reply to reporter

- Staff on a ticket with `anonymous_secret` can send a reply, up to 4000 characters.
- The reply is a public timeline row and an email to confirmed contacts.
- The email contains the reply text and the tracking link.
- The reply does not create a comment and does not emit the comment event.
- The staff ticket shows which addresses will receive it.
- Bots and the agent API have no public-reply action in this delivery.

## Mail configuration

- Configured means: relay with base URL and token, or SMTP with a host.
- The anonymous settings screen shows whether outbound mail is configured.
- Saving “anonymous enabled” does not require mail to be configured. The public form enforces it.

## Security

- Confirm tokens are stored only as SHA-256.
- Public description HTML is produced by the server from escaped text plus the stored image URL.
- Copy-confirm mail cannot be used to learn whether a report exists, what it says, or its id.
- Submit and verify responses do not reveal duplicate tickets.
- Rate limits above apply in addition to the draft cap.
