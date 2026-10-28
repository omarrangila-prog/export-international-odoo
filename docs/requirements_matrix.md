# Requirements traceability matrix

Written 27 October 2026 from the code in this repository, against the client's 11-page *Daily Working Tasks at Export International*
(PDF) and *CODE LIST.xlsx*. One row per requirement: where it lives in Odoo, what proves it, and what is still open.

Evidence tags:
* **[SOURCE]**: described in the client's PDF or code list. It has not been checked for tax or legal applicability.
* **[CODE]**: present in models, views and permissions.
* **[TEST]**: covered by an automated test that passes; the test is named.
* **[BLOCKED]**: needs something outside the build, such as real FoxPro files, a bank, FBR or a signature.
* **[OPEN]**: a client decision. The number is the row in `open_decisions.md`.

Nothing here is **[CLIENT-APPROVED]**. No accountant or operations owner has signed any requirement, formula or report. "Demo" approvals on the
staging copy were made by synthetic users and are not sign-offs.

## 1. The ten daily processes (PDF pp.1-11)

| # | Requirement [SOURCE] | Where in Odoo [CODE] | Proof [TEST] | Open / next |
|---|---|---|---|---|
| 1 | Morning bank balance vs register; SMS entries; running balance (pp.1-2) | `ei.bank.balance.check`: the bank's balance vs the posted ledger, timing items, proof status, sign-off by a second person. `ei.bank.import`: statement files, checks of opening, closing and running balances | `test_banking` 04-06, **24** (500,000 + 100,000 - 20,000 = 580,000 against a bank balance of 575,000 shows -5,000 until timing items explain it; cannot be signed off without proof or by the person who entered it) | Bank feeds [BLOCKED] (5). What counts as proof [OPEN] (33) |
| 2 | Payment proofs from party groups; afternoon check against bank; no wrong-party, duplicate or missing receipt (pp.1-2) | `ei.bank.import.line` (verify party, unidentified, reject), `ei.bank.allocation`, `ei.partner.alias`, matching screen (`ei_matching`) | `test_banking` 01-03 (same file or line imported twice is not posted twice), 07-11, 15, 20-23; `test_matching` 05 (a suggestion is labelled and never allocates), 11, 17-19 | A screenshot is never treated as cleared money: only a bank statement line can be allocated |
| 3 | Contracts and DAs in MTL; commission, End Coils and direct-purchase methods (pp.2-6) | `ei.contract` (versioned revisions, maker-checker), `ei.da` (capped by contract quantity), formula register `ei.formula.definition` | `test_contracts` 01-17; `test_engine` (both PDF golden examples and CN per coil, both rounding modes) | Which rule applies to which contracts [OPEN] (31); End Coils [OPEN] (32) |
| 4 | Cash book written on paper, then fed in (p.6) | `ei.cash.voucher` (maker-checker, attachment, posting, old party code kept exactly, cheque/slip number), `ei.cash.count` (count vs expected, discrepancy) | `test_cashbook` 01-11 | Expense categories need approved GL accounts (3) |
| 5 | Daily Order Request printed before the supplier invoice (p.7) | `ei.daily.order` generated from approved DAs; PDF report | `test_orders` 01-08 | The client's exact print layout has not been seen; the current layout is a proposal |
| 6 | Supplier invoice number written onto the order; lifted vs not lifted (pp.7-8) | `invoice_ref` on order lines (filled from the supplier intake); `ei.lifting` with gate pass, weighbridge and maker-checker | `test_lifting` 01 (an invoice is not a lifting), 02-12; `test_invoicing` 01 | Which evidence proves a lift [OPEN] (2, and decision 10 in the audit) |
| 7 | Invoice number **and HS code** entered; month-end comparison with the parent statement (p.8) | `hs_code` on supplier intake lines and order lines (added 27 Oct); statement column "HS Code"; matching flags `hs_difference` | `test_journey`: the HS code reaches the order; the same code written without a dot matches; a different code is flagged although the amounts agree | Whether HS is compulsory at intake [OPEN] (34) |
| 8 | Customer-specific invoices cut in another system (p.9) | Customer invoicing from verified liftings; per-customer layout (one line per truck or per DA, truck details, HS code, contract reference, a note on every invoice); draft preview and edit before posting; PDF, email and spreadsheet output, each logged with a revision number | `test_invoicing` 09-13, 11b | The customers' own layouts have not been received; the options cover what the PDF describes |
| 9 | Several people's daily files merged and ledgerized by party code (pp.9-10) | One database; legacy codes (`ei.legacy.code`, 639 rows, codes kept as text such as `4.20`); repeat-safe imports | `test_legacy_master`, `test_parsing` (codes, counts, repeat import) | FoxPro history [BLOCKED] (4) |
| 10 | Next-day final figures after merging (pp.10-11) | Role-based Home, report centre, bank freshness, daily posting review | `test_home_v2`, `test_reports`, `test_banking` 17 | Performance with a year of real entries not measured (`asset_loss_writeup.md` section 7) |

## 2. Formulas (PDF pp.3-5): see `calculation_register.md`

| Requirement [SOURCE] | Built | Proof [TEST] | Open |
|---|---|---|---|
| ISL 239,950: 43,191.00 / 283,141.00 / 283.14 / 283,424.14 / 3,167.34 / 280,256.80 | Draft formula `ISL_ASML_DEALER_NET` (seeded), engine steps `add_ref`, `subtract_ref`, `input_amount` | `test_engine.test_isl_and_asml_golden_examples` (both rounding modes); the formula's 7 signed tests | Sign-off (31) |
| ASML 244,450: 44,001.00 / 288.45 / 288,739.45 / 3,226.74 / 285,512.71 | Same | Same | Same |
| 0.1% is taken on the 18%-inclusive rate; commission on the **basic** rate | Step bases fixed in the formula | `test_0_1_percent_is_on_the_18_percent_inclusive_rate_and_commission_on_the_basic_rate` | |
| CN per coil: CN 1,000 gives 13.20, then 986.80, then a final rate of 284,525.91; a coil without CN keeps Dealer Net | `cn_amount` is set per contract line; `cn_text` is required when an amount is given | `test_cn_per_coil`; `test_contracts.test_17` (two coils, only one with CN) | Is CN per MTL or a coil total? (31) |
| The earlier "210,000 less 1.32%" rule | Kept unchanged as `MILL_RATE_DEDUCTION` (draft) | `test_contracts` 01-04 | Which contracts it covers (31) |
| Direct local purchase 201,000 - 200,000 = 1,000 per MTL, which is not profit | `spread_per_mtl`, `expected_gross_spread` | `test_engine.test_spread_*`, `test_contracts.test_05` | |
| End Coils "210,000 @ 18%" | Not built on purpose | | (32) |
| Approved formulas immutable; contracts frozen at approval | Snapshot on each contract line | `test_contracts` 03-04 | |

## 3. Reconciliations

| Workbench | Built [CODE] | Proof [TEST] | Not yet |
|---|---|---|---|
| R1 Bank book vs bank | Balance check with timing items, "still unexplained", proof status, second-person sign-off and lock; statement opening/closing/running checks | `test_banking` 04-06, 24 | Bank feeds (5) |
| R2 Bank line -> party -> invoice | Verified party, allocations (one receipt to many invoices, many receipts to one invoice, partial), posting through Odoo reconciliation, duplicate protection | `test_banking` 01-03, 07-23; `test_matching` 01-20 | |
| R3 Party subledger vs GL control account | `ei.subledger.check`: control total, sum of party balances, items with no party, hand entries on control accounts, parties the wrong way round; second-person sign-off; never posts | `test_close` 01-02 | Real chart of accounts (3) |
| R4 Contract -> DA -> customer allocation | Remaining = ordered - allocated; DA capped; override needs a group and a reason; amendments free the old quantity | `test_contracts` 09-15 | |
| R5 Daily order -> invoice -> physical lifting | Order lines show requested, verified lifted and remaining; **quantity trail** per DA line: promised, requested, supplier-invoiced, lifted, customer-invoiced, and the four mismatches | `test_orders` 03, 07; `test_lifting` 01-12; `test_journey` (trail) | |
| R6 Supplier invoice vs contract/DA | **Reading the attached invoice** with the approved language model: a proposal shown beside the record, applied by a person to empty fields only (`test_assistant` a28). Intake blocks rate, quantity and duplicate mismatches; an override needs an approver and a note; the bill is created only after the check; **side by side** per line: supplier says / contract says / DA says / still to invoice / actually lifted / difference / who reviews | `test_invoicing` 01-07, 02b | Side-by-side document viewer exists (documents beside the record); OCR not configured [BLOCKED] |
| R7 Parent month-end statement | Import (CSV/XLSX, checksum, duplicate-file refusal), classification (matched, amount, tax, **HS**, missing either side, duplicate, possible match), owners, resolutions, sign-off by a second person. **Printed total**: sign-off is refused until the total typed from the paper equals the imported rows. Every rupee of the parent total falls into exactly one class | `test_reconciliation` 01-09; `test_journey` (HS); `test_assistant` a29 (PDF read into rows by the language model) | Real statements needed |
| R8 Cash count | Count vs expected, discrepancy, custodian cannot close their own count | `test_cashbook` 09-10 | |
| R9 FoxPro -> Odoo | Code list (639 rows, exact codes). **Read-only FoxPro extract** (`migration/foxpro_extract.py`): every file hashed, code page, deleted records kept and marked, numbers as exact text, memo files; refuses to write beside the source and checks nothing changed. Extracts recorded in Odoo (changed tables shown); **control totals** from the old reports compared with the books and signed | `test_migration` 01-04 (synthetic tables) | FoxPro copy and opening balances [BLOCKED] (4) |
| Ask with a language model (decision 35) | Read-only Claude behind Ask for questions the rules do not understand, and for Urdu. Its only tools are the existing answers and the record search, run with the asker's rights. The answer is shown with the records it used, labelled, and logged with its engine | `test_assistant` a22, a24-a27 | Off until the key is set |
| R10 FBR | Adapter that never claims success while unconfigured; retry is idempotent | `test_invoicing` 14-16 | Registration, integrator and credentials [BLOCKED] (6) |

## 3b. Close, centre and reporting controls

| Requirement | Built [CODE] | Proof [TEST] |
|---|---|---|
| Daily and month-end close with blockers and explanations | `ei.close`: checklist worked out from the records; blockers cleared or waived with a reason by an accounting manager; second-person sign-off with a frozen snapshot; a signed month can set Odoo's lock date | `test_close` 03-05 |
| All reconciliations in one place, permission-aware | Reconciliation centre (R1-R10 and the close), each with open items, oldest age, last sign-off; the bank card has a row per account (book, today in/out, lines waiting, bank, proof) | `test_close` 06; browser spec 18 |
| Report readiness, not "delivered" for a screen | Catalog shows a ladder: screen available, tested on sample data, checked against real books, approved by finance, verified in daily use. Nothing is past "tested on sample data" | `test_reports` r08 |
| Report data contract | Company, currency, as-of, what is left out and owner on every report | `test_reports` r08 |
| Honest import and integration health | Imports and integrations log: bank and parent statements, code list, old-system extracts, FBR submissions, with fingerprints and problems | browser spec 18 |
| Screen-by-screen, role-by-role inventory | `docs/screen_inventory.md`, generated from the installed menus and access rules | generated |

## 4. Controls that apply everywhere

| Control | Proof [TEST] |
|---|---|
| Maker-checker on contracts, DAs, orders, liftings, cash, bank, statements and formulas | Named tests in each module (for example `test_contracts` 13, `test_banking` 13, `test_reconciliation` 04, `test_banking` 24) |
| A button a role may not use is hidden, and the server refuses it anyway | `test_visible_actions`, `test_review.e03` |
| An approver sees what, who, what changed, the documents and the effect before approving | `test_review` e01-e06 |
| Company boundaries | Record rules in every `ir.access.csv`; `test_ui` |

## 5. What this matrix does not claim
* That any figure is correct for real money: no real contract, statement or ledger has been run through it.
* That the reports are finance-approved: the financial previews are labelled PREVIEW.
* That bank, FBR or OCR integrations are live: they are not.
* That the browser suite proves what it checks for the real data: it ran on synthetic data on the build machine.
