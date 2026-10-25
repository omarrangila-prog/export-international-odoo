# Open decisions (owner: Export International finance unless stated)

| # | Decision | Blocks | Safe default in the build |
|---|---|---|---|
| 1 | Legal entities; one Odoo company per entity? | Company mapping, numbering | Single company, company-scoped rules ready |
| 2 | Stock ownership per flow (owned / consignment / direct dispatch) | Inventory valuation (M7) | Must be classified per contract line before lifting is verified; no stock moves created |
| 3 | Tax base, inclusive/exclusive, tax-on-tax, commission base, withholding, rounding, profit equation | Approving any real formula (M5) | Engine ready; only a draft deduction example exists |
| 4 | Opening balances, FoxPro/Access extracts, bank statements, signed statements | Any migration of positions; test T11 opening balances | Nothing migrated or invented |
| 5 | Bank feeds / statement formats per bank | Bank-specific parsers | Generic CSV (date, description, reference, debit/credit or amount, balance) |
| 6 | FBR/PRAL applicability, onboarding, sandbox credentials, integrator | E-invoicing | Connector not implemented; submissions stay "Pending configuration" |
| 7 | Accountant classification of the 22 `needs_review` legacy codes (5.01 SAFE, 5.83, 4.19, 4.20, expense-like customer rows) | Journal/account creation for them | They cannot be approved as bank/contact |
| 8 | Odoo 20 is a nightly build (20261018), not a stable release: confirm the client accepts it or wait for a stable tag | Version | 20.0 (nightly) |
| 9 | MTL = metric ton? | Quantity units | Contract unit defaults to Odoo "Ton"; kg conversion uses the unit setup |
| 10 | The remaining pages/sections of the PDF (W8-W10) | Confirming W8-W10 design | Designed from the brief |
| 11 | LC accounting treatment and workflow | LC settlement | Register only; settlement action refuses |
| 12 | Self-approval limits and receipt thresholds for cash | Cash policy | 0 = second person always approves; receipt always required |
| 13 | Weighbridge tolerance | Lifting verification | 0 (any difference needs an approved note) |
| 14 | Whether customer invoice wording may vary per customer | Invoice layouts | One optional switch (show gate pass/truck) |
| 15 | Which users hold which role | Production role assignment | None assigned |
