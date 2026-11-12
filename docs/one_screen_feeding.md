# One-screen feeding, three parties, PKR only (11 November 2026)

The client's correction: feeding must be one fast screen like the old FoxPro entry, not Contract → DA → another form. All amounts are in PKR.

## What the operator sees
*Orders & Trucks › DA feeding desk › Real entry › New DA*:

1. **Entry date** and **DO / DA No**.
2. **SUPPLIER (Purchase From) → Purchase (IN) → Sold (OUT).** The first two are chosen from short lists; Sold (OUT) is searched by name or code and may stay empty ("Not sold yet").
3. **Coils:** Add Coil, then item (searched by name), coil number, grade, thickness, width, weight in kg (MTL is worked out), Sold (OUT) and the Sales / Purchase / P&L codes, the feeding method and its rates. The answer shows purchase, sale and spread per MTL, and the purchase amount, sale amount and gross spread of the coil.
4. **Save & Add Coil** keeps the item, the parties, the codes and the method for the next coil. **Submit for Approval** sends the DA to a checker (maker-checker).

"More details" holds the name printed on the DA, the printed order and ship dates, and "Against a signed contract" for the cases where one really exists.

## What happens behind the screen
- **No contract by hand.** The system keeps one *feeding account* per supplier and buying entity: an `ei.contract` of type `feeding`, opened by the system and labelled "Not a signed contract". It has no agreed quantity and no agreed rate, so the DA is not checked against either; after approval its lines show what was fed. It exists so that daily orders, truck loadings, invoices and reports keep working unchanged.
- **Formula.** A coil's mill-rate methods use the approved formula chosen on the mill (*Rate formula for feeding*, set by the accountant), with the parameters of that formula's first signed test case. A mill without one can only be fed with the direct method (typed rates).
- **Who the parties are.** An administrator ticks *Supplier (Purchase From)* and *Purchase (IN) entity* on the companies concerned. The client's own names are loaded by a script kept outside this repository.
- **Printed name.** With a Purchase (IN) entity on the DA, the name printed on the paper is compared with that entity. The sales code is checked against the Sold (OUT) customer only: it must be verified and belong to that customer.
- **Not sold yet.** A coil without Sold (OUT) can be saved as a draft; the DA cannot be submitted until every coil has one. Nothing is invented.
- **Feeding posts nothing to the books.** Accounting entries come later, from supplier and customer invoices.

## PKR only
- New contracts, DAs, supplier invoices, parent statements and LCs are refused in any currency but PKR, on the server.
- The currency selector and the exchange-rate line are gone from the entry screens.
- Older records in another currency are left as they are, still open, and a revision of one keeps its currency. Odoo's own currency setup is untouched.

## Ledgers (*Orders & Trucks › Ledgers*)
One row per fed coil, the same rows grouped five ways: **From → To trace**, **Supplier ledger**, **Purchase (IN) ledger**, **Customer ledger**, **P&L by code**. Columns: date, DA, supplier, Purchase (IN), Sold (OUT), coil, quantity, remaining to lift, purchase and sale rate, P&L per MTL, amounts, gross spread, the three codes and the status. These are quantities, rates and **gross** spread from the feeding entries. Money owed and paid is in the accounting ledgers (Customers & Suppliers).

## Tests
`ei_da_feeding/tests/test_feeding.py` tests 12 and 20–23; browser spec `26_one_screen_feeding.js`.

## Not done yet
- The new top menu (Home | New Feeding Entry | Daily Entries | Ledgers | Bank & Cash | Reports | Approvals | More).
- Invoice number, HS code and lifting status as columns of the trace.
- The one-page quick entry for bank and cash.
- The training film of this screen.
