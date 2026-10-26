# Signing in with a PIN (`ei_pin_login`)

Two ways to sign in, on the same page (tabs **Password** | **PIN**):

| Way | You type | Good for |
|---|---|---|
| Password | user name + password | everybody, always works |
| PIN | user name + four digits | a quick sign-in on a shared desk or a phone, for people who set one |

The password way is Odoo's own and is untouched. A PIN does **not** replace it and is never required.

## Setting your own PIN
Sign in with your password. Open your name menu (top right) → **Sign-in PIN**. Type your password (every time), then the four digits twice. The server refuses the obvious ones in plain words: 1234, 0000, any repeated digit, digits in a row (3456, 5432), a year (1900-2035), a repeated pair (4747).
You can remove it the same way ("Remove my PIN").

## What an administrator can and cannot do
* Cannot read or choose anyone's PIN (only a salted hash is stored; there is no screen or call that returns it).
* Can **remove** a person's PIN, or **lift a lock**: Settings > Users > the person > tab *Sign-in PIN*. The person then signs in with their password and can set a new PIN.
* The system administrator account itself signs in with the password only (a PIN is refused even if one was planted).

## Safety, in one place
| Question | Answer |
|---|---|
| How is it stored? | pbkdf2-sha512, random salt, bound to the account (a hash copied to another person does not work). No PIN is ever written to a log. |
| Can someone guess it? | 10 000 combinations, so the *person* is locked, not the address: 5 wrong tries pause the PIN for 15 minutes, 10 for an hour, 15 lock it until an administrator lifts it. 15 guesses is 0.15 % of the combinations. The password is never affected by any of this. |
| Many addresses at once? | The counter is per person. One address may also fail only 20 times in 15 minutes (all names together). Odoo's own per-address cooldown still applies. |
| What does the person see on a refusal? | Always the same sentence: wrong PIN, unknown name, no PIN set, paused, locked and switched-off all read alike, so the page cannot be used to find out who has an account or a PIN. |
| Does a PIN open the programming interfaces (RPC, API)? | No. It opens the web page only (`interactive` sign-in). Typing a PIN where a password is expected does nothing. |
| Password reset by someone else? | A password set by someone other than the person (an administrator after a doubt, a reset link) also removes the PIN, so whoever held the old secrets keeps no way in. A person changing their own password keeps their PIN. |
| Is there a record? | Yes: Setup > *Sign-in PIN activity* (system administrator, management, auditor; read-only, 180 days): every PIN sign-in good or refused (name, address, reason), and every set / remove / reset / unlock. An unknown name is stored as "(not a known name)" because people sometimes type their password into the name box. |
| Honest limits | A four-digit PIN is guessable by someone who watches it being typed, and could be brute-forced **offline** by whoever copies the database (10 000 candidates; the salt and 600 000 rounds only slow that down). That is why it is a convenience beside the password, not a replacement, and why decision 26 in `open_decisions.md` recommends keeping the approving roles on the password. |

## Settings (System Parameters)
| Key | Meaning | Default |
|---|---|---|
| `ei.pin.enabled` | switch the whole feature off (the tab disappears, PIN sign-in is refused) | True |
| `ei.pin.blocked_groups` | comma-separated group ids that must use the password, e.g. `base.group_system,ei_contract_da.group_ei_contract_approver`; write `none` to reserve nobody | `base.group_system` |

The numbers (5 / 10 / 15 tries, 15 min / 1 h, 20 per address) are constants in `addons/ei_pin_login/models/pin_policy.py`.

## Demo PINs (STAGING only, synthetic)
`migration/seed_demo_pins.py` gives every demo login a PIN so the feature can be tried; they exist only on the staging copy and are changed by each person from the name menu.

| Login | PIN |
|---|---|
| demo.ceo | 4826 |
| demo.finance | 5973 |
| demo.accountant | 6184 |
| demo.contractapprover | 7352 |
| demo.contracts | 8419 |
| demo.bank | 3647 |
| demo.cash | 2958 |
| demo.dispatch | 9261 |
| demo.sysadmin | none (administrator: password only) |

## Tests
* `addons/ei_pin_login/tests/test_pin_login.py` - 27 tests: PIN rules, hash only, password needed to set, every refusal reads the same, PIN is not a password and the reverse, copied hash fails, pause / hour / hard lock / unlock, lock belongs to the person, address throttle, system administrator excluded, switch off, admin remove and unlock only, nobody can read the hashes, log content (never a PIN), clean-up, and the real `/web/login` page and `/xmlrpc` (a PIN does not open it).
* `tests/e2e/specs/15_pin_login.js` - the real page in a browser: both tabs, only the chosen field sent, digits only, set from the name menu (wrong password, weak PIN, mismatch, success), sign in with it, wrong PIN and unknown name read the same and stay on the PIN tab, password still works, administrator has no menu entry, removal closes it, log, phone.
