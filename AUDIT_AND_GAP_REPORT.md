# AUDIT AND GAP REPORT - Export International "EXI ONE" upgrade

Date: 25-26 Oct 2026. Branch: `exi-one-upgrade` (baseline commit `b7ef73e`, taken before any change in this upgrade; file backup `~/backups/export-international-odoo-before-exi-one-20261025.tgz`).
Method: code read, tests run, and the running staging site driven in headless Chromium. Anything not checked is marked **NOT CHECKED**.
Status words: **BUILT** = code + test exists and was run. **PARTIAL** = some of it exists. **NOT BUILT** = not found in the code. **N/A** = depends on something we do not have.

## 1. Environment (verified)
| Item | Finding |
|---|---|
| Odoo | 20.0 Community nightly 20261018, unpacked in `~/odoo20`, started by `~/odoo20/odoo20` (isolated from the Odoo 19 Enterprise that other projects use). A nightly is not a stable release (decision #8). |
| Stack | PostgreSQL 16, Python 3.12. Local machine only: no staging server, no Odoo.sh, no CI, no monitoring, no off-site backup. |
| Git | There was none. Initialised on 25 Oct with a baseline commit and the development branch. |
| Addons | 12 (`ei_legacy_master`, `ei_bank_operations`, `ei_cashbook`, `ei_contract_da`, `ei_daily_orders`, `ei_material_lifting`, `ei_invoice_extensions`, `ei_parent_reconciliation`, `ei_trade_lc`, `ei_management_dashboard`, `ei_ui_theme`, **`ei_party360` (new)**). 35 models (two are page-data helpers with no table), 11 wizards, 44 window actions, 66 views, 44 active menus, 22 groups, 128 access rows, 5 reports, 1 scheduled job (inactive). |
| Databases | `ei20b` staging (PKR company, 639 real codes, **synthetic DEMO data**, demo.* users with password `demo`); throw-away test databases. |
| Server exposure | Staging server now binds to `127.0.0.1` only (`migration/serve.sh`). The earlier launch script was not checked for this; `admin/admin` and `demo/demo` must never be reachable from a network. |

## 2. Source evidence
| Source | What it gives | Status |
|---|---|---|
| CODE LIST.xlsx / EXI_legacy_codes.csv | 639 codes (452/79/58/24/18/8), 0 Excel formulas, codes kept as text (4.20, 5.10, 16.10) | VERIFIED; xlsx and csv give identical content; re-import creates nothing new |
| Daily Working Tasks PDF | Only the pasted text of sections 1-7 was ever seen. W8-W10 come from the brief | PARTIAL |
| DOS FoxPro files (DBF/IDX/FPT/PRG) | **Not supplied.** No FoxPro history has been migrated or compared | MISSING (decision #4) |
| Signed historical outputs, bank/FBR access, tax bases, stock ownership, legal entities | **Not supplied** | MISSING (see `docs/open_decisions.md`) |
| `EXI_ONE_ULTIMATE_UPGRADE_CLAUDE_PROMPT.md` | Not on disk; the pasted brief was cut off after section 6 of the second message | NOT SEEN IN FULL |

## 3. What exists (workflow inventory)
| Legacy step (PDF) | Where it lives | State |
|---|---|---|
| 1 Online banking + posting | `ei_bank_operations`: morning balance check, statement file import (idempotent fingerprints), suggestions, party confirmation, allocation to invoices, approve, post, end-of-day review | BUILT (file import only; no bank API) |
| 2 DA / contract feeding | `ei_contract_da`: contract -> review -> approve -> activate, DA with quantity control, amendments as revisions, formula register needing accountant approval | BUILT (no document extraction) |
| 3 Cash book | `ei_cashbook`: vouchers with maker-checker, transfers, daily count | BUILT (no amount-threshold policy: every voucher needs approval) |
| 4 Daily order request | `ei_daily_orders`: made from approved DAs, PDF/email | BUILT |
| 5 Invoice number / lifting trace | `ei_material_lifting` (gate pass, weighbridge, verified MTL, ownership model), `ei_invoice_extensions` (supplier intake with mismatch blocking) | BUILT |
| 6 Parent ledger matching | `ei_parent_reconciliation`: import, match, classify, resolve, sign off | BUILT |
| 7 Invoice cutting | `ei_invoice_extensions` wizard: customer invoices from verified liftings | PARTIAL (one wording flag per customer, no template library) |
| 8-10 Daily review, merge/ledgerize, previous-day | `ei_management_dashboard` + Odoo accounting | PARTIAL (brief only) |
| LC register | `ei_trade_lc` | PARTIAL (settlement gated) |
| Interface | `ei_ui_theme`: Home page, plain labels, menus, cards, banners | BUILT |
| **Party 360** | `ei_party360` (new this session) | BUILT, see section 6 |

## 4. Defects found and ranked
**Fixed in this upgrade (each has a test that failed first or a browser check):**
| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| D1 | P1 | **12 window actions returned from Python lacked `views`** (`view_mode` only). Odoo's own button controller (`/web/dataset/call_button`) normalises them, so revise, amend, new version, email, the import-wizard result screens and the dashboard magnifiers worked (re-checked in a browser against the untouched baseline: they pass). The crash happens only when a custom screen asks for the action through JavaScript (`orm.call`): the **Home money tiles** ("Customers owe us", "We owe suppliers", "Profit") threw `Cannot read properties of undefined (reading 'map')` and showed "Oops!" to every role. My first write-up of this overstated the reach; this is the corrected, verified scope. | Baseline browser run: Home tile crashes (console `TypeError` in `_preprocessAction`); flows 1-4, 10, 11 pass on baseline | All 12 now return `views`; test `ei_ui_theme.test_15` scans all addons so a JavaScript caller can never receive one without |
| D2 | P1 | The CEO (management) role could see AR/AP on Home but had no read access to journal items, so the drill-down failed with an access error | `has_access` check; test `ei_management_dashboard.test_15` failed first | Management now implies Odoo's read-only accounting group (`account.group_account_readonly`). Read only: the test asserts no write. **Needs finance sign-off (decision #9).** |
| D3 | P2 | Search by text: Odoo's `ilike` treats `%` as a wildcard, so typing `%%` listed all 639 codes | Shell check: 639 matches | User text is escaped in every search in the new addon |
| D4 | P2 | Bank-lines list opened grouped and showed a meaningless sum of "how sure" scores | Screenshot | Default grouping removed, aggregate switched off |
| D5 | P2 | Parent-statement card dates wrapped over four lines | Screenshot | Single-line date range |
| D6 | P2 | Staging database held 10 asset bundles whose files were missing, so the web client rendered a blank page | Blank screenshot, `FileNotFoundError` in the log | Stale generated rows deleted. Cause unknown (see risks) |

**Fixed in the second pass (found by the new real-browser suite, the unit tests and the translation export; each has a test that failed first):**
| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| D7 | **P1** | **"Cancel order request" and "Reverse lifting" could never succeed from the screen.** The reason wizard's allow-list only knew contracts and DAs, so Confirm always answered "Action not allowed". Unit tests called the model methods directly and never went through the wizard. | Browser: Confirm on the wizard; unit test `test_16` (every reason button vs the allow-list) failed first | Each module registers its own entry; `ei_daily_orders` and `ei_material_lifting` added theirs; wizard tests for both |
| D8 | P1 | The first administrator to press Print on a fresh company was interrupted by Odoo's "Configure your document layout" wizard, and everything after it was blocked | Browser: Print on the Daily Order | `migration/setup_company.py` sets the standard layout; runbook says to upload the logo |
| D9 | P1 | An accountant saw the "Bank balances" figure, but clicking it opened a screen their role cannot read (access error) | Browser: role matrix opens every figure for every role | The figure opens the posted items on the bank accounts for roles without bank access |
| D10 | P1 | **Root cause of the blank-page / missing-asset-bundle failure (the earlier fix was only clearing rows).** The staging server had been started with its data directory inside a scratch folder that was wiped between sessions, while the build scripts used Odoo's default directory. The web bundles generated while serving lived in the scratch filestore; the database rows survived, the files did not. | Transcript of the old launch script (`--data-dir=$S/odoo20-data`); 10 bundle rows, 0 business attachments missing | One data directory for every script (`migration/env.sh`); `check_filestore.py` fails loudly and `serve.sh` refuses to start on missing business files; `ei_drop_db` removes the filestore too |
| D11 | P1 | No PDF engine on this machine: Daily Order print and email, invoice PDFs and the dashboard PDF could not work, and no test had ever produced a real PDF | Browser: "Unable to find the pdf engine" | `wkhtmltopdf` unpacked in user space from the official package; the browser suite now downloads a real PDF; Home shows a red System check to administrators when it is missing |
| D12 | P2 | My own mistake: extending seven models with the activity mixin using `_inherit` without `_name` silently created seven new, empty models (`ei.daily.order.activity` and so on) and left the real models without activity support | Seen in the translation export; unit test `test_21` | `_name` set on each; test that no `ei.*.activity` model exists and that every task model supports assignment |
| D13 | P2 | My own mistake: OWL 3 rejects `t-model` on plain state fields, so the Assign and Escalate dialogs failed to render | Browser console `Invalid t-model expression` | Explicit value and input handlers |
| D14 | P2 | My own mistake: `min(480px, 70vh)` in SCSS (Sass cannot mix units) made the whole bundle fail to compile and the whole app render unstyled | "A css error occurred" banner | Plain CSS `min()`; the browser suite now reads every stylesheet bundle and fails on a compile error |
| D15 | P2 | A role with no Export International role crashed the new My Work list (no access to the snooze table) | Unit test `test_03` | Empty, polite result |
| D16 | P2 | Dark mode: navigation bar went light, white chatter and breadcrumb, purple links, white text on a light-blue primary button | Screenshots; scan for light surfaces | Tokens for every surface Odoo draws; contrast measured |
| D17 | **P0** | **All three import wizards (bank statement, parent statement, old codes) failed on screen in Odoo 20 with "Oops! Something went wrong".** Odoo 20 hands an uploaded file back as a lazy `BinaryValue`, not base64 text; the wizards base64-decoded it. Every earlier test called `import_file()` directly with bytes, so a person uploading a bank statement was the first to hit it. | Browser flows 7-9; server log `binascii.Error: Invalid base64-encoded string`; unit test `test_17` drives each wizard the way the form does | One shared reader `upload_bytes()` (accepts the Odoo 20 value and legacy base64); used by all three wizards |
| D18 | P1 | The "Invoice delivered material" wizard failed on Create ("Missing required field Lifting"): the screen marks the lifting read-only, so the browser never sent it | Browser flow 6; server log shows the INSERT with a NULL lifting | `force_save` on that field |

**Open:**
| # | Sev | Finding |
|---|---|---|
| O1 | ~~P1~~ | ~~No automated browser tests in the standard run.~~ **Done:** `tests/run_e2e.sh` (6 specs) is part of `tests/run_all.sh`. |
| O2 | P1 | No FoxPro data, so migration (workflow E) is unproven; opening balances are not loaded. |
| O3 | ~~P1~~ | ~~Status pills in the bank-lines list are cut off.~~ **Done:** pills wrap; the browser suite checks every list at six widths. |
| O4 | ~~P2~~ | ~~"1 loadings" plural wording.~~ **Done** on Home, pipeline and Party 360. |
| O5 | ~~P2~~ | ~~Party 360 phone page about 4,900 px tall.~~ **Done:** zero figures collapse into one list, two columns on a phone (measured in spec 04). |
| O6 | ~~P2~~ | ~~Operator steps shown to the CEO.~~ **Done:** the executive layout has no routine list; My Work shows only what is stuck. |
| O7 | P2 | Dark theme is done for Home, Party 360 and the main Odoo screens (lists, forms, kanban, dialogs, chatter); rarely used Odoo screens keep Odoo's default and are not checked. No density setting. Ctrl+K now searches records and old codes. |
| O8 | P2 | `action_open_queue` has no button (dead code) and the old Detailed report shows approval counts as plain text; the new Home makes every queue openable. Remove the dead method when the old report is retired. |
| O9 | P1 | **Urdu text is not translated** (Odoo ships none). Right-to-left layout is built and tested (Arabic stands in). Plan, glossary draft and string export: `docs/urdu_plan.md`, `docs/i18n/ei_ui.pot`. |
| O10 | P1 | **AI copilot, automation recipes A01-A24 beyond the ones already built, and the page-by-page redesign of every other screen are not started.** This increment is the Home, My Work, search, Party 360 and the platform fixes. |

## 5. Security review (what was checked)
* Group model is least-privilege: `group_ei_user` is implied by every role; auditor is read-all and is not implied by operational roles. Maker-checker enforced in the ORM and covered by tests in every module.
* **Risk:** demo users and `admin/admin` exist in `ei20b`. Staging only; never promote this database. Server now loopback-only.
* **Risk:** the CEO role now reads all journal items (D2). Read-only, company-scoped by Odoo's own rules.
* **NOT CHECKED:** SQL/ORM penetration test, session hardening, dependency audit, rate limits, a restore of the filestore with the database.

## 6. Gap against the 20 screens (S01-S20)
| Screen | State |
|---|---|
| S01 My Work Today | **BUILT (core)**: real tasks from records waiting for a person, priority and waiting time by stated rules, maker-checker (you are not asked to approve what you prepared), assign (native Odoo reminder, only to people who can do the step), snooze, escalate to managers with a reason, close my reminder, filters, role-aware. Not built: free-text comments on a task, due dates unless assigned, delegation chains |
| S02 CEO/CFO Command Center | **PARTIAL+**: executive Home leads with eight figures that each show their basis (posted, bank-confirmed, waiting, provisional) and open the records behind them (verified for the CEO), alerts, 14-day invoiced-vs-received chart, receivables ageing, contract-to-payment pipeline. "Explain this number" exists on Party 360 only; no period comparison |
| **S03 Party 360** | **BUILT (new).** Search by name, nickname, exact old code text or approved alias; 15 figures each with "How is this worked out?" and "Show the records"; contract -> DA -> order -> lifting -> invoice -> payment strip per DA; timeline; unlinked old codes offered as codes, never turned into parties; ledger figures limited to finance roles; hidden sections named, never shown as zero. 15 tests + a browser script |
| S04 Legacy Code Explorer | PARTIAL: list, approval queue, immutable raw fields, import history; no collision analysis screen |
| S05 Contract Intelligence | PARTIAL: contract form, versions, attachments; no split-screen document viewer or extraction |
| S06 DA Desk | BUILT (quantity control, amendments) |
| S07 Daily Order Generator | BUILT |
| S08 Lifting Control Tower | PARTIAL: records, verify, remaining MTL; no tower board, mobile photo capture is attachment-only |
| S09 Supplier Invoice Intake | PARTIAL: manual entry, duplicate/mismatch blocking, bill creation; **no OCR/extraction, no side-by-side viewer** |
| S10 Invoice Studio | PARTIAL: wizard from verified liftings; no template library or preview |
| S11 Banking Command Center | PARTIAL: list-based; no API |
| S12 Payment Matching Workbench | PARTIAL: line list + confirm + allocate; not the three-column layout |
| S13 Cash Book | BUILT (basic) |
| S14 Accounting workspace | Odoo native; CEO now has read-only access |
| S15 Parent Reconciliation Hub | BUILT |
| S16 Document Intelligence | NOT BUILT (attachments only) |
| S17 Approvals Control Room | PARTIAL: Home alerts include approvals waiting too long (days are a setting); approvals queues; approval is still not bound to a snapshot hash |
| S18 Reports Builder | PARTIAL: one PDF summary; no saved report templates |
| S19 AI Assistant | NOT BUILT |
| S20 Integration/System Health | PARTIAL: administrators get real system checks on Home (PDF engine, outgoing mail, summary job, staff accounts, connections); no job/queue health or retry console |

## 7. Gap against the 24 automations (A01-A24)
BUILT: A05 (manual intake, duplicate and mismatch), A06, A07, A08, A09, A10, A12, A14, A16 (exact duplicates: bank fingerprint, supplier invoice number, gate pass, contract reference).
PARTIAL: A02, A03 (order is a button, not automatic), A04 (no arrival tracking), A11 (suggestion vs verified states, no proof intake), A13 (approval yes, amount thresholds no), A20 (bank day only), A22 (formulas have effective dates; not tested against history), A24 (daily summary e-mail exists but its schedule is inactive).
NOT BUILT: A01, A15, A17, A18, A19, A23.
N/A (no external connector exists): A21.

## 8. Baselines measured (25 Oct 2026, headless Chromium, local machine, warm assets, 5 runs, median)
**Demo-sized data (a few dozen rows). This is NOT a scale test and says nothing about 50k-250k lines.** Script: `tests/ui_timing.js`.
| Page | Median to usable |
|---|---|
| Home | 407 ms |
| Bank payments to check (list) | 423 ms |
| Contracts (list) | 448 ms |
| Daily orders (list) | 412 ms |
| Truck loadings (list) | 380 ms |
| Parent statements (kanban) | 358 ms |
| Party 360, server call for one party | 48 queries, 38 ms; party search 4 queries, 4 ms |

Cold-start load time after a server restart was not measured. Not measured, and not claimed: time to enter a DA, clicks per invoice, daily reconciliation time, duplicate entries prevented, staff satisfaction, 50k-250k-line performance, slow-network behaviour.

## 9. Prioritised backlog (next slices)
1. **P0 hygiene:** browser tour tests in the standard run (O1); click every Home tile and every wizard result in CI.
2. **Transaction timeline / "open entire transaction"** from a DA or contract (reuses the Party 360 chain code).
3. **My Work Today v2:** owner, age, due, assign/delegate/comment on top of the real counts; A17/A18 reminders as the first automations.
4. **Explain-this-number** on the management dashboard (same pattern as Party 360).
5. Supplier invoice side-by-side viewer + extraction behind an AI/OCR provider flag (needs a data-protection decision).
6. Three-column payment matching workbench.
7. Approval snapshots (hash of the approved values; any change forces re-approval).
8. Density/dark theme and user landing preferences.
9. FoxPro extraction pipeline once files are supplied.
