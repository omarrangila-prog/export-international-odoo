# Release status - 26 Oct 2026

**State: functional first build for UAT preparation. Not production-ready. No client data beyond the code list has been loaded.**

## Verified (reproducible)
* 320 automated unit tests green on a fresh Odoo 20 database across 17 modules (`docs/test_results.md`), plus a real-browser suite of 15 specs (full run 26 Oct: 851 checks passed, 0 failed, 1 intentional skip; `docs/e2e_results.md`).
* 639 legacy codes load from the real workbook and the CSV with identical content; re-import creates nothing new; codes keep their displayed text form.
* New Home page and card views for every role; screens reviewed in `docs/ui/final/` (desktop admin/CEO/cash clerk, mobile dispatch). 25+ screens open in headless Chromium without error dialogs or console errors (`docs/screenshots/`).
* Backup/restore round trip verified.

## Mocked or simulated in tests only
FBR/other gateway (a patched test gateway), statements, contracts and parties (synthetic), the generic chart of accounts.

## Pending third parties or approvals
Accountant approval of tax/commission formulas, stock ownership, mapping of the 22 flagged codes, FBR/PRAL access, bank statement formats/feeds, OCR provider, opening balances.

## Not built
AI assistants (M14), Urdu labels, Docker Compose, performance tests, external security review, production monitoring/backup automation, owned-stock valuation, LC settlement, foreign-currency bank allocation, bank-specific statement parsers.

## Next actions
1. Client confirms the five questions (entities, ownership, commission/tax base, balances, bank/FBR access) and supplies the full PDF.
2. Accountant works the mapping queue (22 `needs_review` codes first) and approves formulas.
3. Load opening balances from independently signed statements and run T11 for real.
4. UAT with one user per role; then production hosting, backups and monitoring.

## Interface (ei_ui_theme) - 26 Oct 2026
**Built and verified in a real browser:** Home as a command centre per role (compact header, figures with basis and drill-down, alerts that are only raised by real problems, My Work with priority, age, assignee, assign / snooze / escalate / close-my-reminder, contract-to-payment pipeline, trend charts with a table alternative, grouped launcher); universal search and Odoo's Ctrl+K searching records and old codes with permission filtering; light and dark themes (the whole app, not only Home); right-to-left layout; Party 360 compact on a phone; keyboard operation of menus and dialogs; WCAG 2 A/AA automated checks with zero serious findings on our screens at six widths.
**Not done:** Urdu text (Odoo ships none; plan and string export in `docs/urdu_plan.md`), a language model behind the assistant, automation recipes beyond A17, A18, A19 and A24 (see below), the page-by-page redesign of the remaining screens (they carry the new tokens, dark theme and plain labels but not new layouts), supervised screen-reader pass, measured usability testing with staff, performance at 50k+ lines.

## Upgrade 25-26 Oct 2026 (branch `exi-one-upgrade`; every item is itemised in `AUDIT_AND_GAP_REPORT.md`, D1 to D26)
* New: Party 360, My Work engine, universal search, dark theme, role profiles (7 personas), design system document, real-browser suite.
* Fixed (each found by running the real screens, with a test that failed first): the Home money tiles crashing for every role; all three import wizards failing on screen in Odoo 20; the invoice wizard failing on save; Cancel order request and Reverse lifting always refused; first Print interrupted by a layout wizard; the CEO and accountant unable to open figures they could see; the missing-asset blank page (root cause, not a cache clear); no PDF engine on the machine.
* Honest limits unchanged: no FoxPro data, no bank/FBR/OCR connector, no supervised user test, 50k+ line performance unmeasured, demo data is synthetic.

## Reminders and payment matching - 26 Oct 2026 (`ei_automation`, `ei_matching`)
**Reminders (`ei_automation`):** four read-only rules (A17 supplier invoice still missing after an order was approved, A18 approved material not lifted, A19 customer invoice overdue, A24 anomalies such as duplicate bank lines) under Setup > Automation rules. **Every rule ships switched OFF**: the business owner turns a rule on and sets the days (the defaults are PROPOSED, not agreed). A rule can only give a colleague an internal reminder; it never contacts a customer, never posts and never changes a record. "Show what it finds now" creates nothing; "Run now" creates exactly what was previewed; a reminder is not repeated while one is open or inside the repeat window; a cap limits one run; every run and finding is logged. Customer-chasing wording is a DRAFT inside the reminder for a person to use. A daily scheduled job runs the rules that are on.
**Payment matching (`ei_matching`):** Money > Match bank payments. Four lists (To check, Waiting for allocation, Unidentified, Duplicates); for one line the decision (who paid, then which invoices) and the evidence and effect beside it. A suggestion is shown as "Suggestion, not confirmed" with why and how sure; only a bank officer's click confirms it (with an evidence note unless the name is an approved alias). Invoice proposals are never saved by themselves. Money another staged line already claims is shown and refused. The "what posting would do" preview was checked against the real posting. The screen approves and posts nothing: a bank approver and then a different person still do that.
**Bank defects found on the way and fixed (each with a test that failed first):** D19 two staged lines could claim the same invoice money; D20 an officer could not take an allocation back; D21 choosing another party kept the old party's allocations.
**Not done / needs a decision:** a "this is not a duplicate" action and an "advance / on account" status (no such control exists in the bank module; the client should decide them), foreign-currency allocation, A01, A15, A23 and the remaining automations, a supervised pass with the bank officers, 50k-line queue speed.

## Ask, the read-only assistant - 26 Oct 2026 (`ei_assistant`)
**What it is:** an "Ask" button in the top bar of every screen. Type a question in plain English; the answer comes from your own records, lists its sources (each one opens the record), says how it was worked out and when it was read. It understands what is waiting for you, whether anything is wrong, the key figures, who owes us money, what is overdue, what we owe suppliers (finance, management and the auditor only), how much is left to lift (everything, one delivery advice or one party), bank payments to check, bank balances, and a party name, document number or old code. Two parties that fit are offered as a choice. A question it does not understand is answered "I did not understand that" with questions that work.
**What it is not:** a language model. It cannot make anything up and sends nothing outside the server. It cannot change anything: a request to approve, post, pay, send or delete is refused with the reason, and a test asks dozens of questions as four roles and compares every business table before and after. A role that may not see ledger figures is not offered those questions and is told why if it asks.
**Recorded for management:** every question, who asked it and whether it could be answered (Setup > Assistant questions), so management can see what people really need. Users are told this on the screen.
**Not done / needs a decision:** a language model behind a provider flag, Urdu and Roman-Urdu questions, follow-up questions that refer to the previous answer, a supervised test with real staff (`docs/open_decisions.md` 20-22).

## The Overview on Home - 26 Oct 2026 (redesign from a reference the user supplied)
**What changed:** Home now opens as an "Overview": a large title, a period choice (last 7 / 14 / 30 days or this month) with a real "compared to the days before", the contract-to-payment pipeline as gradient columns (real counts), what customers owe by how late, the question box (Ask), then period cards for Invoiced, Received in the bank and Material lifted (big number, change chip, "Before: ...", a day-by-day chart with hover, a table view, and an arrow to the records behind it), bank balances with whether the bank confirmed them, who owes most, and recent invoices. Cards are rounder and softer, with a brand-tinted shadow, in light and dark. Every earlier feature (My Work with assign / snooze / escalate, alerts, the figures strip, the launcher, search, light/dark, right-to-left) is kept and still tested.
**Honesty rules kept:** a card the role cannot see is absent; a change is a percentage only when there is something to compare ("New" / "No activity" otherwise); nothing is invented for the picture. The reference's own figures and wording were not used.
**DEMO history:** `migration/seed_dashboard_history.py` adds about eight weeks of clearly labelled DEMO invoices, bank receipts and truck loadings to the staging copy so the charts, the comparison and the ageing have something real to show. It is deterministic, idempotent and acts through the real role users. Never run it on production.
**Not changed on purpose:** the dark top bar and every other screen (a light floating top bar like the reference's would touch the whole application, so it is a separate decision).

## Review round and Reports - 26 Oct 2026 (`ei_ui_theme`, `ei_reports`)
**Home, after reviewing it against a checklist:** the pipeline is eight step cards (no line joining unlike counts; each says what it counts); one place per figure; a negative cash balance is an exception; bank balances are labelled BOOK and a stale confirmation is an alert with a "Confirm the balance" button; who owes most is ranked with overdue against outstanding; every exception names its next step; lifted material is shown as three parts that add up; My Work says who owns what; recent activity is a digest; a "New" menu replaces the launcher at the foot of the page; the activity panel on a record can be hidden. **Reports (`ei_reports`):** see `AUDIT_AND_GAP_REPORT.md`, S18. **Not done:** profit and loss, balance sheet, trial balance, cash flow, PDF export and scheduled delivery of reports, document split-screen viewer, the other routes of the brief's audit (they follow the shared design but have not each been redesigned), a supervised five-second test with real staff.

## Client screenshot review, first checkpoint - 26 Oct 2026 (branch `exi-two`)
**What changed (and was checked in a real browser):**
* **EXI-01, a button that fails:** the eight card screens carried `create="1"`, which stops Odoo hiding "New" from people who may not create. Removed. A unit test reads the real view of every role and a browser spec (13) opens every menu entry as nine roles and presses every "New" that is offered: none ends in an Access Error. The access rules were not touched.
* **Home first screen is work.** For the executive, finance manager and accountant the page opens with five summary figures (each says what it is made of and opens its records) and, beside them, **what needs attention** and **your decisions** (or the team queue). The pipeline, flows, banks and charts follow. On a phone the first alert with its next-step button is inside the first 844 px (it was 2400 px down), money figures never wrap, and the secondary sections start folded. Spec 14 measures all of this at 1366x768, 1280x720, 683 px wide (200 % zoom) and 390x844.
* **Screens:** density toggle on lists, sticky form status bar, phone record layout (empty fields hidden, x2many rows as cards), the activity panel starts hidden, a STAGING badge on the top bar and the sign-in page.
* **Sign-in with a PIN** (`ei_pin_login`, `docs/pin_login.md`): a second way in beside user name + password. Everything about it is tested (27 unit tests, spec 15), including that a refusal always reads the same, that it never opens the programming interfaces, and that the system administrator signs in with the password only.

**Verified:** 320 unit tests, 0 failed, on a fresh database (`docs/test_results.md`); the real-browser suite, 15 specs (`docs/e2e_results.md`).

**Not done yet (the rest of the client order):** Party 360 re-organised into tabs, a sticky summary on the bank-matching screen, the approval-evidence dialog, the document split-screen viewer, the report workspace and Preview / Verified / Pending labels, trial balance / profit and loss / balance sheet / cash flow as labelled previews, PDF export and scheduled delivery, Firefox runs, the asset-bundle root-cause write-up, and the five-second test with real staff (a protocol and kit can be supplied; the test itself needs people).
**Decisions needed:** `docs/open_decisions.md` 26 (which roles may use a PIN) and 27 (the PIN rules).

