# Signing in with a PIN (`ei_pin_login`)

Two ways to sign in, on the same page (tabs **Password** | **PIN**):

| Way | You type | Good for |
|---|---|---|
| Password | user name + password | everybody, always works |
| PIN | **four digits, nothing else** (a number pad on a phone) | a quick sign-in at a shared desk or on a phone |

The password way is Odoo's own and is untouched. A PIN does **not** replace it and is never required. (If an administrator sets `ei.pin.only_enabled` to False the PIN tab asks for the user name as well.)

## Setting your own PIN
Sign in with your password. Open your name menu (top right) → **Sign-in PIN**. Type your password (every time), then the four digits twice. Because the PIN alone says who you are, **two people cannot have the same PIN**: if yours is taken you are told "That PIN cannot be used" (without saying by whom) and after 5 such refusals in an hour you must wait, so nobody can find out whose PIN is which by trying them all.
Easy PINs are refused in plain words: 1234, 0000, any repeated digit, digits in a row (3456, 5432), a year (1900-2035), a repeated pair (4747). You can remove it the same way ("Remove my PIN").

## What an administrator can and cannot do
* Cannot read or choose anyone's PIN from the screens (only a keyed hash is stored; no screen or call returns it).
* Can **remove** a person's PIN, or **lift a lock**: Settings > Users > the person > tab *Sign-in PIN*.
* The operator who deploys the system can give a **first PIN** from the server console (`migration/provision_pins.py`, below). Nothing else can choose a PIN for someone.
* The system administrator account itself signs in with the password only (a PIN is refused even if one was planted).

## What a PIN alone can and cannot protect (read this)
A four-digit PIN has 10 000 possibilities, and with the PIN alone as the way in nobody has to guess *whose* PIN it is: any valid PIN works. So:
| Question | Answer |
|---|---|
| Can someone guess it? | Every refused PIN-alone sign-in, from any address, counts for the whole system. At 20 in an hour or 60 in a day **PIN sign-in rests for everybody** until the window has passed ("PIN sign-in is resting for a while. Use your password."); the password keeps working. One address may also fail only 20 times in 15 minutes. That holds a patient guesser to 60 tries a day: about 1.8 % a day to hit one of three random PINs. Home shows the administrator a red line while it is happening. |
| Easy PINs (repeated digits, 1234...) | **These are the first nine or ten things anybody tries. Whoever types 1111, 2222 ... 9999 reaches such an account in under a minute, before any limit helps.** The system lets an operator provision them (the owner decided so) but `provision_pins.py` refuses unless `EI_PIN_ACCEPT_WEAK=1`, and the remedy is below: restrict PIN sign-in to the office network, or choose PINs that are not easy. |
| Restrict where a PIN works | System Parameter `ei.pin.allowed_networks`, e.g. `203.0.113.0/24, 10.0.0.0/8` (addresses or ranges, comma-separated). From anywhere else the page says "PIN sign-in is only available from the office network. Use your password." Empty means anywhere. A value with no valid network closes PIN sign-in. Behind a proxy the server must run with `proxy_mode` so it sees the real address. |
| How is it stored? | HMAC-SHA256 of the PIN with a key kept **outside the database** (`EI_PIN_PEPPER` in the server's environment). Someone who copies only the database cannot recover PINs. Without the variable the database's own secret is used: it works and protects nothing if the database is copied (Home says so to the administrator). Changing the key invalidates every PIN. No PIN is ever written to a log. |
| Does a PIN open the programming interfaces (RPC, API)? | No: the web page only. Typing a PIN where a password is expected does nothing. |
| What does a refusal say? | One sentence (or one of two that say nothing about PINs: "resting", "office network only"), so the page cannot be used to learn who has a PIN. |
| Password reset by someone else? | A password set by someone other than the person (an administrator after a doubt, a reset link) also removes the PIN. A person changing their own password keeps it. |
| With a user name too (`ei.pin.only_enabled` = False) | The PIN is checked against that one person: 5 wrong tries pause it 15 minutes, 10 an hour, 15 lock it until an administrator lifts it. Much safer; recommended for any account that approves or posts. |
| Honest limit | A four-digit PIN is guessable by someone who watches it typed, and is only as strong as the limits and the network rule around it. It is a convenience beside the password, never a replacement for it on an account that can move money. |

## Settings (System Parameters)
| Key | Meaning | Default |
|---|---|---|
| `ei.pin.enabled` | switch the whole feature off | True |
| `ei.pin.only_enabled` | allow the PIN alone (False: the PIN tab also asks for the user name) | True |
| `ei.pin.blocked_groups` | comma-separated group ids that must use the password; write `none` to reserve nobody | `base.group_system` |
| `ei.pin.allowed_networks` | where a PIN may be used (above) | empty = anywhere |
| `EI_PIN_PEPPER` (server environment, not a parameter) | the key that protects PINs | must be set on a live server |

The numbers (5 / 10 / 15 tries, 20 and 60 refusals, 20 per address) are constants in `addons/ei_pin_login/models/pin_policy.py`.

## Giving first PINs (the operator)
```
EI_PROVISION_FILE=/somewhere/outside/the/repo/people.json  [EI_PIN_ACCEPT_WEAK=1]  ei_shell -d DB < migration/provision_pins.py
```
`people.json` (never in git) lists `login`, `name`, `role` (`executive` = the CEO's view; `all_operations` = every Export International role plus accountant, **not** the system administrator) and `pin`. A new person gets a random first password, shown once. Roles can be set with `groups` instead. See the header of the script.

On the staging copy three senior people were provisioned this way at the owner's request (the CEO and a second director with the executive view, the IT team lead with every operational role but not the system administrator account). The second director's role was assumed and is to be confirmed. Their PINs are in the owner's hands and in a private file on the machine that built this, never in git.

## Demo PINs (STAGING only, synthetic)
`migration/seed_demo_pins.py` gives every demo login a PIN so the feature can be tried; they exist only on the staging copy.

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

## Record
Setup > *Sign-in PIN activity* (system administrator, management, auditor; read-only, 180 days): every PIN sign-in, good or refused (address, reason; nobody is blamed for a refused PIN alone), and every set / remove / reset / unlock. A PIN is never recorded.

## Tests
* `addons/ei_pin_login/tests/test_pin_login.py` - 34 tests: PIN rules; keyed hash; password needed to set; no two people share a PIN and probing for taken ones is stopped; the PIN alone signs in and is logged without blaming anyone; the system-wide pause (hourly and daily); the switch; the network rule; provisioned PINs; every refusal reads the same; a PIN is not a password and the reverse; pause / hour / hard lock / unlock for the named variant; address throttle; the system administrator excluded; nobody can read the hashes; the log never holds a PIN; the real `/web/login` page, `/xmlrpc`, and the network message. Mutation-checked: removing the pause, the lock or the network rule makes tests fail.
* `tests/e2e/specs/15_pin_login.js` - the real page in a browser: both tabs, only the chosen field sent, no name asked, set from the name menu (wrong password, weak PIN, mismatch, success), sign in with the four digits alone, wrong PIN, the number pad on a phone (digits, delete, clear, sends at the fourth digit), password still works, the administrator has no menu entry, removal closes it, the log, phone layout.
