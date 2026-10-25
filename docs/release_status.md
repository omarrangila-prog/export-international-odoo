# Release status - 26 Oct 2026

**State: functional first build for UAT preparation. Not production-ready. No client data beyond the code list has been loaded.**

## Verified (reproducible)
* 202 automated unit tests green on a fresh Odoo 20 database across 12 modules (`docs/test_results.md`), plus a real-browser suite of 6 specs that is part of `tests/run_all.sh` (`docs/e2e_results.md`, `tests/e2e/README.md`).
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
**Not done:** Urdu text (Odoo ships none; plan and string export in `docs/urdu_plan.md`), the AI copilot, new automation recipes beyond those already built, the page-by-page redesign of the remaining screens (they carry the new tokens, dark theme and plain labels but not new layouts), supervised screen-reader pass, measured usability testing with staff, performance at 50k+ lines.

## Upgrade 25-26 Oct 2026 (branch `exi-one-upgrade`; every item is itemised in `AUDIT_AND_GAP_REPORT.md`, D1 to D18)
* New: Party 360, My Work engine, universal search, dark theme, role profiles (7 personas), design system document, real-browser suite.
* Fixed (each found by running the real screens, with a test that failed first): the Home money tiles crashing for every role; all three import wizards failing on screen in Odoo 20; the invoice wizard failing on save; Cancel order request and Reverse lifting always refused; first Print interrupted by a layout wizard; the CEO and accountant unable to open figures they could see; the missing-asset blank page (root cause, not a cache clear); no PDF engine on the machine.
* Honest limits unchanged: no FoxPro data, no bank/FBR/OCR connector, no supervised user test, 50k+ line performance unmeasured, demo data is synthetic.
