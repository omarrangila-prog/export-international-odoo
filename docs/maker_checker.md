# Maker-checker approvals (`ei_approvals`)

The client's confirmed process (10 November 2026): **one person enters and submits; a different authorised person approves, returns it for correction, or rejects it.** This replaces the 9 November decision to keep approval off by default. An administrator can still switch approval off for a workflow under *Settings › Export International*.

## The flow

```
DRAFT --Submit for Approval--> PENDING APPROVAL --Approve--> APPROVED --> next stage (FINALIZED)
                               PENDING APPROVAL --Return for correction--> back to the maker --> corrected, resubmitted (round 2, 3 ...)
                               PENDING APPROVAL --Reject--> cancelled / rejected
```

- **Requests:** each submission is an approval request (`ei.approval.request`) with its own timeline (`ei.approval.event`).
- **History:** a resubmission is a new round, and earlier rounds and their reasons stay visible.
- **"Submit" is not "post":** submitting an entry never creates an accounting effect. Accounting effects come only from the document's own approval step, run as the checker (for example, a cash voucher is posted to the books only when its checker approves it).

## Where the approval boundary is, per document

| Document | Submit | Checker must hold | After approval (next stage) |
|---|---|---|---|
| Contract | Submit for Approval (draft → reviewed) | Contract approver | Becomes **active** |
| Delivery advice (DA) | Submit for Approval (desk or form) | Contract approver | Approved. A DA fed in the feeding desk also prepares **today's daily order request**; other DAs keep the order desk's "Generate daily order" step. |
| Daily order request | Submit for Approval (a desk-fed DA submits its order by itself) | Order approver | Approved: print or email it to the parent company |
| Cash voucher | Submit for Approval (draft → submitted) | Cash approver | **Posted** to the cash book |
| Truck loading | Submit for Approval | Lifting reviewer | Verified: it can be invoiced |

**Why the daily order is approved separately:** the order request is a separate commitment, sent to the mill. It bundles the day's approved DAs, and its quantities can be split across days. Approving it is not a repeat of the DA approval.

**The second-person steps that already existed in other modules are in the same centre too (10 Nov 2026).** Their own rules are unchanged. A request opens by itself when the document reaches its waiting state, and the checker decides in the centre or on the document; either way the document's own method runs, as the checker.

| Document | Waits when | The checker's step (role) | Reject from the centre |
|---|---|---|---|
| Bank statement | lines checked, nothing open | Approve (bank approver) | Yes (rejects the batch) |
| Supplier invoice mismatch | the checks found a mismatch | Accept, with the note as the reason (invoice approver) | Yes (cancels the intake) |
| Parent statement | every exception resolved | Sign off (reconciliation approver) | No: return it |
| Daily cash count | counted, not closed | Close the day (cash approver) | No: return it |
| Rate formula | draft with steps and test cases | Approve (formula approver) | No: return it |
| Day / month-end close | checked, no open blocker | Sign off (accounting manager) | No: return it |

**Not routed through the centre:**
- **Bank statement posting:** the second step on an approved statement stays on the statement and in My Work, by a person with posting rights, never the importer.
- **Customer invoices, credit notes and accounting corrections:** these are Odoo journal entries. They keep Odoo's own posting rights. Putting a second person in front of Odoo's posting on the live ledger is a separate decision for the client.

## What is enforced on the server

- **Never the maker:** the checker is never the person who entered or submitted the entry. This holds even when they also hold the approver role, and there is no small-amount exception (the cash-box "self-approval limit" no longer applies while cash approval is on).
- **The right role:** the checker holds the role the document itself needs, plus the rule's role or named checkers when a rule sets them, and has access to the document's company.
- **One decision:** the request must still be pending. Its row is locked, so two checkers cannot both decide it.
- **No stale versions:** the document must be what was submitted (a fingerprint of its figures). An entry changed after submission cannot be approved; its request ends as "Changed after submission" and the maker resubmits.
- **Reasons:** a reason is required to return or reject.
- **The document's own checks still run:** rates, quantities, customer codes, exchange rate and posting rights.
- **No way around it:** the old Approve / Verify buttons and direct server calls go through the same request and the same rules.
- **Audit trail:** the timeline cannot be edited or deleted. Requests are visible to the people involved, to management, auditors and administrators, and only within their companies.
- **Nobody qualified:** if no eligible checker exists, the request says **Assignment required**, administrators are notified, and nothing is approved by itself. An administrator or manager reassigns it once someone holds the role.

## Who checks: approval rules

The rules are under *Approvals › Approval rules*, and only administrators can change them. Each rule has:
- the document type and, optionally, a company;
- an optional maker role;
- the checker role, and optional named checkers (the least busy is chosen; a business user before an administrator);
- an optional amount from which the rule applies;
- the hours before a request counts as overdue, and who is told then (management by default; an hourly job marks it once).

One checker per document, as the client confirmed (10 Nov 2026). There is no two-checker option.

## Notifications and screens

- **Top bar:** "Approvals (n)" shows what waits for the signed-in checker. A bell shows unread notifications (new request, approved, returned, rejected, overdue, assignment required). It updates live through Odoo's bus, re-checks every minute, and shows one quiet toast for each new event. On a phone, the count appears on the bottom bar's Approvals button.
- **Approvals centre** (*Approvals › Approvals centre*):
  - Tabs: Pending for me, Urgent, Returned, Approved, Rejected, My submissions, All I can see, History.
  - The list supports search, document type, status, date range, sorting and paging.
  - The review shows the entry, its lines and rates (with CN and spread), totals, source documents, earlier rounds, the timeline and comments.
  - Actions: Approve, Return for correction, Reject (with confirmation and a required reason); the maker can Withdraw; an administrator or manager can Reassign.
- **Home:** an Approvals block with three groups:
  - *My entries*: returned, waiting, recently approved, drafts.
  - *My approvals*: pending, urgent, overdue, recently reviewed, team submissions.
  - *Approvals across the company* (management): total pending, oldest, average approval time, returned, unresolved exceptions, pending by type.
- **On each document:** a status line (pending with the checker's name, returned with the reason, rejected, assignment required) and "Open in Approvals".

In-app notifications only. E-mail or WhatsApp notifications are not active; they need a working configuration and the client's consent.

## Tests

- **Code tests:** `ei_approvals/tests/test_approvals.py` covers the brief's TEST 01–19 and 21–23, plus rules, thresholds, overdue escalation and the audit trail.
- **Real browser:** `tests/e2e/specs/25_maker_checker.js` covers maker → checker → maker, return and resubmit, reject, an unauthorised user, a self-approval attempt, the live counter, and a phone.
