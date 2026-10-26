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
| 9 | CEO/management role now holds Odoo's read-only accounting group so KPI drill-downs open the journal items (it could not before). Finance to confirm the CEO may read all posted journal items; the role still cannot write | Permissions | read-only (applied 25 Oct 2026) |
| 10 | Party 360 shows ledger balances to finance roles, management and the auditor only (same rule as the dashboard). Confirm who else may see a party's balance | Permissions | finance + management + auditor |
| 16 | Days and owners for the four reminder rules (A17 supplier invoice missing, A18 approved material not lifted, A19 overdue customer, A24 anomalies). Defaults 3 / 5 / 7 / 1 days are PROPOSED by us, not agreed | Which rules the business switches on | All four rules OFF |
| 17 | Wording and channel for chasing overdue customers. The overdue rule only drafts wording inside an internal reminder; nothing is sent to a customer | Any automatic customer message | None sent |
| 18 | A bank line flagged as a duplicate that is really a second genuine payment: who may release it, and how? Also whether customer money that matches no invoice needs an "advance / on account" status. The bank module has neither control today | Matching screen | Duplicate lines can only be rejected; unallocated money stays on the bank suspense account, labelled as such |
| 19 | Two staged bank lines competing for one invoice: first allocation wins (D19). Confirm that is the policy | Matching screen | First staged claim keeps the money; the second is told how much is left |
| 20 | May any question text or record ever be sent to an external language model? Today NOTHING leaves the server: the assistant is rule-based. A model behind a provider flag needs a data-protection decision, a provider and a budget | Ask | No external model |
| 21 | Urdu and Roman-Urdu questions for Ask need a native reviewer for the question list and the wording of answers | Ask | English only; Urdu text is declined politely |
| 22 | How long the log of questions asked of the assistant is kept, and who besides management and the auditor may read it | Ask | Kept without limit; management and auditor read |
| 23 | Who may EXPORT data (the Export action on lists, a spreadsheet of what is on screen)? Today: management, the auditor, and the bank and cash approvers; operators and data entry cannot. An export only contains rows the person may read, with the filters on screen | Reports, every list | Export is available to those four roles only |
| 24 | Time zone for "today" in reports and the dashboard: they use the signed-in person's time zone (Asia/Karachi for the demo users). If a user has none set, the server's zone applies | Reports, Home | Same rule as the dashboard, so the two always agree |
| 25 | Staleness of a bank confirmation: amber when it is not from today, red from 3 days (constant `BANK_STALE_RED_DAYS`). Confirm the thresholds, and whether weekends and bank holidays should be excluded | Home, bank report | 3 days |
