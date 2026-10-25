# Release status - 19 Oct 2026

**State: functional first build for UAT preparation. Not production-ready. No client data beyond the code list has been loaded.**

## Verified (reproducible)
* 158 automated tests green on a fresh Odoo 20 database across 11 modules (incl. 14 UI tests) (`docs/test_results.md`).
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

## Interface (ei_ui_theme)
Built: Home page per role, plain-language labels/menus, card views, guidance banners, mobile layout.
Not done: Urdu translation, keyboard/accessibility audit, measured usability testing with staff, dark mode, global command palette.
