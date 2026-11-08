# DA feeding desk

Orders & Trucks › **DA feeding desk** (module `ei_da_feeding`). One screen for feeding a parent company's delivery advice (DA) coil by coil, as staff did in FoxPro, with every calculation shown step by step.

## Two tabs
- **Practice** shows all the feeding methods side by side, using the sample numbers from the client's handwritten DA (basic rate 229,500; 4,574 kg). The inputs can be edited. **Nothing is written to the database**: no DA, invoice, stock or journal entry. A test counts the records before and after to prove it.
- **Real entry** is for a real DA. The steps are:
  1. Type what the paper says: the DA number, the printed customer, the order time and the ship date.
  2. Attach the paper, which is shown beside the entry.
  3. Add each coil: coil number, grade and weight in kg (MTL = kg / 1,000).
  4. Choose the customer and the three old-system codes (customer, purchase/sale, P&L). You can search by code, name or nickname.
  5. Choose the method; only that method's fields appear.
  6. Save the coil as a draft, then send the DA for review.

  Approval stays on the DA, with maker-checker.

## Methods
| Method | Purchase rate | Sale rate |
|---|---|---|
| Normal sale | Dealer net (from the contract's formula) | Mill rate ± an amount (the example uses −1,000) |
| High-profit sale | Dealer net | Mill rate + an amount (the example uses +10,000) |
| Loss sale | Dealer net | Mill rate − an amount (the example uses −10,000); needs a reason and an approver |
| Sale at mill rate | Dealer net | Mill rate |
| Purchase with CN | Dealer net less the net CN (CN less 1.32%), for **this coil only** | Mill rate ± an amount |
| Direct purchase and sale, no commission | Typed | Typed |
| Purchase without commission | **Waiting for the client's example and the accountant's rule.** It cannot be calculated or saved. | |

- The amounts are examples. The operator types the amount actually agreed, or the sale rate itself.
- "Sale at mill rate" is **not** "Purchase without commission": its purchase rate still has the 1.32% commission taken off.
- The mill rate and dealer net come from the contract line's **approved** formula (`ISL_ASML_DEALER_NET`: 18% of the basic rate is added; 0.1% of that rate is added; 1.32% of the basic rate is the commission). Practice may use the formula while it is still a draft and labels it as such. Real entry refuses a formula that has not been approved.
- The results are gross spreads per MTL and for the coil's tons. They are not tax results, invoice totals or booked profit.

## Checks before a DA can be approved
- The coil's rates must equal a fresh recalculation, so a rate edited by hand is refused.
- A sale below cost needs a written reason. The person who entered the DA cannot approve it.
- A credit note needs its text. A basic rate different from the contract needs a rate note.
- **Customer code:**
  - The code must come from the customer list.
  - It must be verified by the accountant and linked to a customer.
  - That customer must be the coil's customer.
  - If the printed customer name shares no word with the code, an authorised person must record why the code is right. This last case is the only one that can be accepted; an unverified code or another customer's code can never be waved through.
- A DA in a foreign currency (USD) needs an Odoo exchange rate on or before the DA date. The screen shows the company-currency equivalent.
- A contract line whose formula gives a purchase rate cannot be sent for review with a different hand-typed rate.

## After approval
The approved DA line carries its purchase and sale rate into the existing chain:
- the daily order request;
- the supplier invoice check, which compares against the DA line's purchase rate;
- material lifting;
- the customer invoice wizard, which starts from the DA line's sale rate.

## Tests
- `ei_da_feeding/tests/test_feeding.py`: the six worked examples to the cent, and every check above.
- Browser spec `tests/e2e/specs/20_da_feeding_desk.js`: practice on screen; a real DA with its paper attached and a coil with a CN, sent for review; approval refused while the customer code is unverified; phone layout.

## Open, needs the client
- "Purchase without commission": a real example and the rule.
- What "VA" means.
- What the "seventh entry" is.
- Whether a CN is per MTL or a coil total, and its credit-note accounting.
- The rounding policy.
- Approval of the formula by the client's accountant.
