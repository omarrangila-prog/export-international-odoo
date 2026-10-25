# AUDIT AND GAP REPORT - Export International "EXI ONE" upgrade

Date: 25 Oct 2026. Branch: `exi-one-upgrade` (baseline commit `b7ef73e`, taken before any change in this upgrade; file backup `~/backups/export-international-odoo-before-exi-one-20261025.tgz`).
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
| D1 | **P0** | **12 actions returned from Python had `view_mode` but no `views`; Odoo 20's web client crashes on them.** Affected: every Home / dashboard money drill-down, "Amend" on contracts, DAs and formulas, the three import wizards' result screens, the invoice wizard result, "Send daily order by email". The server work succeeded and the user saw "Oops! Something went wrong". Found by clicking "Customers owe us" as the CEO: `TypeError: Cannot read properties of undefined (reading 'map')`. The earlier 158 tests and the 25-screen smoke test never clicked these. | Browser + console log; test `ei_ui_theme.test_15` (AST scan of all addons) failed on 12 dicts | All 12 now return `views`; the scan test keeps it fixed |
| D2 | P1 | The CEO (management) role could see AR/AP on Home but had no read access to journal items, so the drill-down failed with an access error | `has_access` check; test `ei_management_dashboard.test_15` failed first | Management now implies Odoo's read-only accounting group (`account.group_account_readonly`). Read only: the test asserts no write. **Needs finance sign-off (decision #9).** |
| D3 | P2 | Search by text: Odoo's `ilike` treats `%` as a wildcard, so typing `%%` listed all 639 codes | Shell check: 639 matches | User text is escaped in every search in the new addon |
| D4 | P2 | Bank-lines list opened grouped and showed a meaningless sum of "how sure" scores | Screenshot | Default grouping removed, aggregate switched off |
| D5 | P2 | Parent-statement card dates wrapped over four lines | Screenshot | Single-line date range |
| D6 | P2 | Staging database held 10 asset bundles whose files were missing, so the web client rendered a blank page | Blank screenshot, `FileNotFoundError` in the log | Stale generated rows deleted. Cause unknown (see risks) |

**Open:**
| # | Sev | Finding |
|---|---|---|
| O1 | P1 | No automated browser tests in the standard run: `tests/ui_smoke.js`, `tests/ui_party360.js` are manual scripts. A JS/browser tour suite would have caught D1. |
| O2 | P1 | No FoxPro data, so migration (workflow E) is unproven; opening balances are not loaded. |
| O3 | P1 | Status pills in the bank-lines list are cut off in narrow columns ("Suggest..."). |
| O4 | P2 | "1 loadings ready to invoice" on Home (plural wording; the Party 360 page was fixed). |
| O5 | P2 | The Party 360 phone page is about 4,900 px tall because every figure is a full-width card; zero-value cards should collapse. |
| O6 | P2 | Home "steps" for the CEO include operator steps ("Prepare today's Daily Order Request"). |
| O7 | P2 | No dark theme, no density setting, no command palette entry for parties (Odoo's own Ctrl+K exists but does not search legacy codes). |

## 5. Security review (what was checked)
* Group model is least-privilege: `group_ei_user` is implied by every role; auditor is read-all and is not implied by operational roles. Maker-checker enforced in the ORM and covered by tests in every module.
* **Risk:** demo users and `admin/admin` exist in `ei20b`. Staging only; never promote this database. Server now loopback-only.
* **Risk:** the CEO role now reads all journal items (D2). Read-only, company-scoped by Odoo's own rules.
* **NOT CHECKED:** SQL/ORM penetration test, session hardening, dependency audit, rate limits, a restore of the filestore with the database.

## 6. Gap against the 20 screens (S01-S20)
| Screen | State |
|---|---|
| S01 My Work Today | PARTIAL: Home with real counts per role; no owner/due/age, assign, delegate, snooze or comment |
| S02 CEO/CFO Command Center | PARTIAL: dashboard + Home money tiles with drill-down (now working for the CEO); no "Explain this number" on the dashboard, no period comparison |
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
| S17 Approvals Control Room | PARTIAL: approvals queues; approval is not bound to a snapshot hash |
| S18 Reports Builder | PARTIAL: one PDF summary; no saved report templates |
| S19 AI Assistant | NOT BUILT |
| S20 Integration/System Health | PARTIAL: static "connections" list; no job/queue health |

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
