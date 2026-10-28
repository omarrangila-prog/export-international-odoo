# Release gate: what must be true before real money goes in

Written 27 October 2026. Each condition says what the system does to support it and what is still open. "Open" items need the client,
a bank, FBR or real data. They are not code that is missing.

| # | Condition | What the system provides | State |
|---|---|---|---|
| 1 | Rate formulas signed off with the books | Separate, versioned, draft formulas with signed tests from the PDF (`calculation_register.md`); contracts keep the version they were approved with | Approved by the owner 27 Oct 2026; the accountant presses Approve in the system before first use |
| 2 | Ledger balances signed off | Party balances vs control accounts (R3) with sign-off by a second person; month-end close; Odoo lock date | **Open**: opening balances (4) |
| 3 | End-to-end tests pass for every role | 372 code tests; real-browser suite (1,078 checks) for every role, phone to large screen, light and dark, Chrome and Firefox | Passes on synthetic data |
| 4 | Bank events counted once | File fingerprints, line fingerprints, one posting per line; imports log | Passes on synthetic data |
| 5 | Parent statements reconcile on approved examples | Matching by number, amount, tax and HS code; printed total must equal the rows imported; sign-off by a second person | **Open**: needs real parent statements |
| 6 | Physical MTL checks work | Verified loadings (gate pass, weighbridge, maker-checker); quantity trail per DA line | **Open**: which evidence proves a lift (2) |
| 7 | Migrated balances equal the FoxPro control reports | Read-only extract with hashes; control totals compared with the books and signed | **Open**: no FoxPro copy received |
| 8 | Report totals agree with the books for the same filters | Readiness ladder per report; previews say PREVIEW; built-in checks on the financial previews | **Open**: "checked against real books" is not reached by any report |
| 9 | Staff acceptance (UAT) signed | Role guide in `HANDOVER.md` | **Open** |
| 10 | Backup, restore and rollback rehearsed | `deploy/backup.sh`, restore steps in `HANDOVER.md` section 7 | Rehearsed on the build machine; repeat on the server |
| 11 | Bank, FBR and the language model shown honestly | The FBR adapter never reports success while unconfigured; no bank feed is claimed; answers and document reading by the language model are labelled as such and never change a record | Holds; bank and FBR not connected (5, 6); language model approved, off until a key is set |
| 12 | No critical permission or asset issue | Hidden buttons and server checks agree (tests); asset-loss causes fixed (`asset_loss_writeup.md`) | Holds on synthetic data |

Release is a business decision. When every "Open" row is closed, sign this page with names and dates and keep it with the go-live record.
