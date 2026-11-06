# Test report: Odoo.sh failures, November 2026

Written 6 November 2026. It covers the Odoo.sh build logs of 3, 5 and 6 November and the work done on them. Log details such as session values, tokens and database identifiers are left out on purpose.

## Where the code was tested
| Environment | What it is | Used for |
|---|---|---|
| Community, build machine | Odoo 20 nightly of 18 Oct, Python 3.12, with the client code list | 392 code tests; Playwright browser suite |
| Latest Community | Odoo 20 nightly of 4 Nov, Python 3.14, demo data, no code list | 250 code tests, 14 of them in a real browser |
| The same, with a stand-in | A small test addon, not in the repository, that holds Enterprise's own colour-scheme code (service, cookie, setting) taken from the Enterprise 19 copy on the build machine, and a web client subclass written to match the 6 November error | Reproducing the failures below. It may differ from Enterprise 20 |
| Odoo.sh | Enterprise 20.0 on Python 3.14, as the log reports | The 6 November 18:21 build ran 250 tests with 2 failures, both listed below; every other browser test passed on real Enterprise. The result of the latest commit has not been seen yet |

Enterprise 20's source is not available on the build machine, so only an Odoo.sh build can prove behaviour on real Enterprise.

## Failures and root causes
| Log | Failure | Root cause | Fix | Reproduced before the fix |
|---|---|---|---|---|
| 5 Nov | `test_p02`: the wrong theme colour on the app head | Real bug. Enterprise's view set its own colour after ours | Our view now applies last and replaces the tag | Yes, with the stand-in |
| 5 Nov | `test_43`: `RuntimeError: request not bound` | Test bug. With no cookie the code correctly falls through to Enterprise, which reads the live request, and the test had none | The test now checks that the decision is passed down, without depending on the edition. Enterprise's behaviour is untouched | Yes, with the stand-in |
| 6 Nov | Whole web client: `Cannot find the definition of component "EiTabStrip"` | Real, serious bug. Components were added to the base class's list, and Enterprise's subclass had already copied that list. The app could not open | The tab strip, undo/redo and Documents button are reached through the prototype, which subclasses inherit | Yes, with the stand-in |
| 6 Nov (18:21) | `test_p02`: the browser bar stays light in dark theme | Test bug. Enterprise answers every page with its own `color_scheme` cookie, so the test's cookie arrived beside a `light` one | The test now uses Enterprise's own setting for a person | Yes, against the real Enterprise Python code |
| 6 Nov (18:21) | `test_b03`: `Inspected target navigated or closed` | Real bug, found while diagnosing this. Enterprise's web client resets the cookie to the person's setting and reloads, so **the Home dark/light button could never change anything on Enterprise** | On Enterprise the button now changes that setting, and the server leaves the decision to Enterprise | Yes, with Enterprise's own colour-scheme code |

The 14 new browser tests found the 6 November crash. The 236 tests that existed before could not have found it.

## The four database uniqueness errors
All four are deliberate. Each comes from a test that creates a duplicate on purpose inside a savepoint, and the application is not at fault.

| Constraint | Test | What the test now proves |
|---|---|---|
| `ei_close_uniq` | `test_close.test_05` | Refused by this exact constraint; one row remains |
| `ei_contract_uniq_ref` | `test_contracts.test_08` | The same |
| `ei_supplier_intake_dup` | `test_invoicing.test_05` | The same |
| `ei_lifting_gate` | `test_lifting.test_09` | The same |

These tests used to accept any exception. They now accept only `UniqueViolation` from the named constraint. No constraint was removed. The expected log line is muted, so an `ERROR` in the log now means something unexpected.

## Dark theme
| Case | Result on Community | How it was checked |
|---|---|---|
| Dark cookie | Dark colours and a dark browser bar | Native browser test, Playwright spec 19 |
| Light cookie | Light colours | The same |
| No cookie or an unknown value | Left to the layer below: light on Community, the user's setting on Enterprise | `test_43` |
| Moving to another screen | Stays dark | The same browser tests |
| Refresh | Stays dark; choosing light comes back after a refresh | Playwright spec 19 |
| Another person in another browser | Not affected | Playwright spec 19 |

On Community the choice is a browser cookie, so two people sharing one browser share it. On Enterprise it is a setting per person, which follows them to any browser and also appears in their Preferences.

## PIN key
* **Now:** the key comes from `EI_PIN_PEPPER` in the environment or `ei_pin_pepper` in the Odoo configuration file, and is never logged.
* **Changing the key:** each PIN records a one-way fingerprint of its key. After a change, an old PIN used with a user name asks the person to set it again. It does not count as a wrong try, and locks nobody. Tested with 20 tries (`test_s01c`). An old PIN used alone is simply not recognised.
* **The owner's decision, 6 Nov:** no warning appears in the log or on Home when the key is missing. PINs then rest on the database's own secret, so anyone with a copy of the database could work them out. The risk remains, and nothing shows it any more.
* **Odoo.sh:** no key is set there, and how a host secret survives rebuilds is unconfirmed.
* Lockouts and rate limits were not changed; their tests pass.

## Secondary warnings
* **Translations:** about 1,100 warnings came from text translated with no language known. These are fixed. A plain call with no environment now returns the English sentence.
* **Deprecated `/xmlrpc`:** the only caller in this repository is one test, `test_w06`, which proves that a PIN cannot open the programming interfaces. Its warning is muted. The other `jsonrpc` matches are the browser's normal internal calls.
* **Migration plan:** Odoo schedules these endpoints for removal in Odoo 22. Before that upgrade, point `test_w06` at the replacement API and ask the client whether any outside system calls `/xmlrpc` or `/jsonrpc`. None is known; that has not been checked with the client.

## Assets
See `asset_loss_writeup.md`, including section 8. The causes on the build machine are documented and fixed. No missing-bundle error appears in the Odoo.sh logs seen, but those logs were filtered or cut off, and restores and upgrades there have not been observed. The browser tests now fail if a bundle does not load or a stylesheet does not compile.

## What the native browser tests cover
`ei_close/tests/test_browser.py`, 14 tests: the sign-in page; Home for 11 roles with any console error failing the test; light and dark themes; navigation; New hidden from a reader and working for a maker; contract approval showing its evidence, with Cancel changing nothing; the bank matching screen; supplier invoices; financial reports; and the phone layout. Breaking the code on purpose in three places made them fail each time.

## Environment
The Odoo.sh logs report `20.0+e`, so the target is Enterprise. Enterprise-specific behaviour was reached through `WebClientEnterprise` and `web_enterprise`. The `My Company` and `USD` in those logs are test data. They say nothing about real settings, and no financial configuration was changed.

## Production readiness
**Not ready.** The latest commit has not been seen green on Odoo.sh, the screens have not been looked at on Enterprise, and the open rows in `release_gate.md` remain: opening balances, real parent statements, the FoxPro copy, staff acceptance, and bank and FBR access.
