# Five-second test - kit and protocol

**Status: NOT RUN.** Nobody has been tested yet. This file is the kit for running it with real staff of Export International; no result is claimed anywhere. Do not report the test as done until the results sheet at the end holds real answers from real people.

## What it answers
Can a person understand, in five seconds, what their Home page is for and what to do first? Home is the first thing every person sees, so if it fails here the rest of the screens do not matter.

## Who and how many
* 5 people per role that really uses the page: executive, finance manager or accountant, contract desk, bank or cash data entry, logistics. That is 25 sessions of about 6 minutes each.
* At least 3 of the 5 per role must never have seen the new screens. People who worked on the project do not count.
* Voluntary, anonymous (a number, not a name), no recording unless the person agrees. Say it plainly before starting: "This tests the screen, not you. You can stop at any time."

## What to show
Use only the staging copy (synthetic DEMO data; the "STAGING" label is on screen). Never show live figures.
1. Open the staging site as the role's demo login (see `docs/deployment_runbook.md`; PINs are in `docs/pin_login.md`) on the device the person really uses: a laptop at 1366x768 or a phone.
2. Or show the prepared pictures in `docs/ui/gallery/`: `home-executive.png`, `home-finance-manager.png`, `home-accountant.png`, `home-contract-desk.png`, `home-data-entry-bank.png`, `home-data-entry-cash.png`, `home-logistics.png` (laptop; crop to the first 768 px) and `phone-home.png` (phone; crop to the first 844 px). Show the first screen only, without scrolling.
3. Cover the screen. Show it for exactly **5 seconds** (a phone timer), then cover it again.

## Script (read aloud, in the person's language; the screen text is English, the questions can be asked in Urdu)
> "I am going to show you a page for five seconds. Please look at it as you normally would. Then I will hide it and ask four short questions. There are no wrong answers."

Questions, in this order, notes taken word for word:
| # | Ask | What a good answer sounds like |
|---|---|---|
| Q1 | "What is this page for?" | "My overview / what needs my attention / my work for today" |
| Q2 | "What is the first thing you would do?" | Names the first alert, decision or task, or a "New" action for data-entry roles |
| Q3 | "Tell me one thing you remember seeing." | Any real element: a figure, an alert, a button |
| Q4 | "Was anything confusing or missing?" | Free answer; write it down, do not defend the screen |

Then show the screen again, **without time limit**, and ask: "Where would you click to ... ?" (one task per role from the table below). Time how long the person takes and whether the first click is right.

## Tasks after the five seconds (one per role)
| Role | Task |
|---|---|
| Executive | "Find out which approvals are waiting for you." |
| Finance / accountant | "Find the bank money that still has to be matched to a customer." |
| Contract desk | "Start a new delivery advice." |
| Bank / cash data entry | "Start entering a bank statement" / "a cash voucher". |
| Logistics | "Find the trucks that still have to be loaded." |

## Scoring
Per person: Q1 right (names the purpose), Q2 right (a sensible, correct first step), first click right, time to click.
**Pass for a role:** at least 4 of 5 people get Q1 and Q2 right and the first click right within 10 seconds. Anything less is a finding. Write down every confusing word; those words are the first thing to change.
Record what changed after a failed round, and run 3 new people on the fixed screen. Do not re-test the same people.

## What this test cannot tell you
It tests understanding at first sight, not whether the figures are right (that is the job of the automated checks that compare every figure with the books) and not whether the approval flow suits the business. It also cannot be answered by the people who built the screens.

## Results sheet (copy this table; fill in one row per person)
| Person no. | Role | Device | Q1 right? | Q2 right? | First click right? | Seconds to click | Confusing words / notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## Before you start
* Run the staging site, sign in once as each role and check the first screen opens without errors (`tests/e2e/specs/14_home_first_screen.js` measures that the first alert is on the first screen).
* Prepare fresh pictures with `NODE_PATH=$HOME/tfmsg-website/node_modules node tests/ui_gallery.js docs/ui/gallery http://127.0.0.1:8369 homes,phone && python3 tests/ui_gallery_index.py` (staging on port 8369).
* Decide who may see the results: this file recommends the owner of Export International and Odoovations only.
