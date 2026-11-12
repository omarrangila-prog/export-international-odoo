# Online Feeding and the Cash Book (`ei_daybook`, 12 Nov 2026)

The client's second old-system recording shows three things besides DA feeding: **online feeding** (money that reached a bank),
**browsing and printing** the entries, and the **cash book** (including a balance brought forward). This addon gives each its
own simple screen, fed the way the old system fed them: an amount, a CREDIT code and a DEBIT code from the client's own code list,
the two narrations, CHQ # and SLIP #.

## What an entry is

| Kind | Sides | Rule |
|---|---|---|
| Online feeding (bank) | credit = who paid, debit = the bank | the debit code must be on the BANK list |
| Cash book | credit and debit | one side must be on the BANK list (banks, the safe) |
| Balance brought forward | ONE code | a BANK-list code; printed apart; never counted as the day's receipts or payments; one per code per date |

* PKR only. The currency is fixed on create and refused on change.
* Codes keep their text form (a trailing zero stays: `x.20`, never `x.2`) and their list; a code from one list is never moved to another.
* A code written on the paper that is not in the code list (the recording shows one) goes in **Code not in the code list**:
  the entry is kept as a draft, shown with a warning, printed as "not in the code list", and **cannot be submitted**. Nothing is
  guessed: neither a nearby code nor an account.
* The same bank SMS / reference cannot be fed twice; the same date, amount and codes twice needs a written reason.
* A screenshot or SMS is proof that someone says it was paid. An online entry is **bank-confirmed** only when the bank desk links
  the line of an imported bank statement.

## Maker-checker and corrections

* **Save & Submit** sends the entry to a different person (flow `daybook` of the approvals engine; online entries are checked by a
  bank approver, cash entries by a cash approver). Nobody approves their own entry, whatever roles they hold.
* Return for correction puts it back to draft with the checker's note; Reject closes it (it reaches no ledger).
* **Delete draft** works only on a draft not waiting for a checker; every deletion is recorded (Setup > Deleted draft entries).
* An approved entry is never edited or deleted: a checker presses **Reverse**, which makes an equal entry with the sides swapped.
  Both stay; the code ledgers net to zero.

## What it is NOT

These entries are **not Odoo journal entries**. The client's old codes are not yet mapped to Odoo accounts by the accountant, so
posting them would mean guessing accounts. The ledgers here are ledgers **by old code** (Ledgers > Bank & cash ledger, Party
ledger), read straight from the entries (`ei.daybook.leg` is an SQL view, so a ledger can never disagree with its entries).
The opening balance needs the accountant's approved opening trial balance before anything is posted to the books.

## Screens

* Top bar: **Online Feeding**, **Cash Book** (Cash book entries, Cash vouchers, Count the cash, Print the day book),
  **Daily Entries** (Online and cash entries, and every older entry list), **Ledgers** (two new ledgers by code).
* Print the day book: a date range and a book; balances brought forward first and apart, then the entries, then Cr and Dr totals.

Tests: `addons/ei_daybook/tests/test_daybook.py` (synthetic codes) and `tests/e2e/specs/27_online_and_cash_book.js` (DEMO codes).
