# Functional requirements and workflow matrix

Sources: `CODE LIST.xlsx` (read in full; 639 rows, 0 formulas), `EXI_legacy_codes.csv` (identical content, verified row by row),
and the text of "Daily Working Tasks at Export International" **as pasted by the client** (OCR text, ends at section 7 "Invoice cutting").
The master brief describes ten workflows; the pasted text covers seven numbered sections. W8-W10 below come from the brief only and
must be confirmed against the full PDF.

## Legacy workflow -> ERP flow -> owner -> evidence

| # | Legacy (source) | ERP flow | Module | Control owner | Tests |
|---|---|---|---|---|---|
| W1 | Morning bank call, balance vs register; SMS and payment images noted by hand; 4-5 p.m. posting review (PDF s.1) | Morning balance check vs ledger; statement CSV import with immutable batch, duplicate guards, party verification, allocation, daily posting review | ei_bank_operations | Bank officer (import) / Bank approver / Bank poster | test_banking 01-19 |
| W2 | DA and contract feeding into FoxPro (PDF s.2) | Contract + DA with approvals, quantity control, frozen calculation snapshot | ei_contract_da | Contract staff / Contract approver / Formula approver (accountant) | test_contracts 01-15, test_engine |
| W3 | Cash book on paper, re-entered (PDF s.3) | Cash vouchers (maker-checker), receipts, transfers, daily cash count | ei_cashbook | Cash clerk / Cash approver | test_cashbook 01-11 |
| W4 | Daily Order Request Excel sheet (PDF s.4) | Order request generated idempotently from approved DA; PDF + email | ei_daily_orders | Contract staff / Order approver | test_orders 01-08 |
| W5 | Invoice number written on the order sheet to see what is lifted (PDF s.5) | Supplier invoice number recorded on the order line; **lifting recorded and verified separately** (gate pass, weighbridge) | ei_daily_orders + ei_material_lifting | Dispatch officer / Lifting reviewer | test_orders 05, test_lifting 01-12 |
| W6 | Invoice number fed for month-end parent ledger matching (PDF s.6) | Supplier invoice intake; parent statement import and matching | ei_invoice_extensions, ei_parent_reconciliation | Invoicing staff / Recon user / Recon approver | test_invoicing 01-08, test_reconciliation 01-08 |
| W7 | Access -> Excel -> separate system to cut customer invoices (PDF s.7) | Wizard creates customer invoices from verified liftings | ei_invoice_extensions | Invoicing staff / Invoice approver | test_invoicing 09-13 |
| W8 | Separate reps review feeding then email files (brief only) | Shared central records; approvals queue; maker-checker | ei_management_dashboard | Management | dashboard test_09 |
| W9 | Merge and ledgerize emailed data by code (brief only) | Mapped partners/journals; native Odoo accounting updated on posting | ei_legacy_master + all | Mapping approver | journey (T14) |
| W10 | Previous-day figures received next afternoon (brief only) | Dashboard on posted records with explicit bank freshness labels | ei_management_dashboard | Management | dashboard test_03-05 |

## Module status (honest)

| Module (brief id) | Status | Notes |
|---|---|---|
| ei_legacy_master (M1) | Built, tested | 639 codes loaded from the real workbook and CSV; mapping queue and approvals; no auto-creation of records |
| ei_bank_operations (M2) | Built, tested with CSV statements | Generic CSV only. No bank API/feed. Same-currency allocation only |
| ei_cashbook (M3) | Built, tested | Cash-to-bank transfers need the company's internal transfer account set |
| ei_contract_da (M4, M5) | Built, tested | Engine and register complete. **No tax or commission formula is approved** (bases unconfirmed) |
| ei_daily_orders (M6) | Built, tested | PDF renders; email composer wired, not sent from this machine |
| ei_material_lifting (M7) | Built, tested | Ownership must be classified per contract line. **No stock moves or valuation** are created until the accountant decides owned-stock treatment |
| ei_invoice_extensions (M8, M9) | Built, tested | OCR not configured (manual entry). FBR/PRAL connector **not implemented**; submission log, idempotency and retry are tested with a simulated gateway only |
| ei_parent_reconciliation (M10) | Built, tested | CSV/XLSX statements; PDF statements need OCR (not configured) |
| ei_trade_lc (M11) | Register only | All 58 references preserved; settlement postings deliberately gated |
| ei_management_dashboard (M12, M13) | Built, tested, screens smoke-tested in headless Chromium | Excel export is Odoo's native list export on the drill-down; daily summary cron exists but is **inactive** |
| ei_ai_assistants (M14) | **Not built** | Brief says only after core controls work; no AI feature exists |

## Not provided / not built
Opening balances, FoxPro/Access extracts, bank statements, tax mappings, product catalogue and contact details were not supplied;
nothing was invented. Urdu labels, a Docker Compose file, performance/load tests, an external security review and UAT sign-off are not done.
