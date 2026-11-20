# Company currency: PKR. Investigation and safe change plan

## Why it matters
Export International works in PKR only. Every DA, contract, voucher and day-book entry is in PKR. When the **company's
accounting currency** is not PKR (a fresh Odoo database starts in USD), every PKR document needs a PKR exchange rate to be
booked. The feeding screen then said "No PKR rate on or before <date>". Since 20 Nov 2026 it says plainly that the company
currency is the cause.

**What the update does by itself (20.0.1.0.13):** a company that is not PKR **and has no journal items at all** is switched
to PKR (Odoo allows it; nothing is booked yet, so nothing can be miscounted). A company that **has** journal items is left
exactly as it is, and the update log says: `... keeps its books in USD: N journal items exist; see docs/deploy_currency_plan.md`.
Such a company follows steps 1-3 below with the accountant.

## Step 1: look (read-only, changes nothing)
Run `migration/currency_check.py` in the Odoo shell of the database. It prints, per company:
- the accounting currency;
- the journal items and entries (posted, draft or cancelled; by currency; first and last date);
- the Export International documents by currency;
- whether Odoo would accept a currency change now.

## Step 2: decide with the accountant
| What step 1 shows | What to do |
|---|---|
| Company already PKR | Nothing. The message cannot appear. |
| Not PKR, **no journal items** | The update switches it to PKR by itself (backup first, as for every deployment). By hand: Settings > Companies > currency = PKR. |
| Not PKR, **only test/demo entries** (no real business) | Back up, then cancel and delete those draft/test entries with the accountant's written OK, then change the currency. Never delete posted real entries. |
| Not PKR, **real posted entries** | Do not change in place. Options for the accountant: (a) a new PKR company and opening balances migrated with the opening trial balance; or (b) keep the company and enter a PKR rate each day (not recommended for a PKR-only business). |

## Step 3: change (only after step 2's decision)
1. Odoo.sh: make a manual backup (Backups > Backup now). Note its time.
2. Change the currency as decided in step 2.
3. Run `migration/currency_check.py` again: the currency is PKR; the counts match the backup apart from what step 2 removed.
4. Open a DA in the feeding screen: no currency message.

## Rollback
Restore the step-3.1 backup (Odoo.sh: Backups > Restore). Nothing else depends on the currency change.
