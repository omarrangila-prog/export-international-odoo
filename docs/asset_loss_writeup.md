# Staging "blank page" incidents: root cause, fixes, and what protects the live server

Written 27 October 2026. Scope: the staging copy on the build machine. The live server has not been affected; section 5 says why the
same causes cannot occur there if the installer and the update steps are followed.

## 1. What people saw
| When | Symptom | Who was affected |
|---|---|---|
| 25 Oct 2026 | Staging opened as a **blank white page** (no menu, no Home). The server log showed `FileNotFoundError` for files under `filestore/<db>/..`. | Staging only. No business data lost. |
| 27 Oct 2026 (a) | New screens appeared **completely unstyled** (plain browser buttons, huge icons), with a red line "A css error occurred, using an old style". | Staging only, a few minutes, during development. |
| 27 Oct 2026 (b) | A code change did not appear at all after "restarting" staging: the old screen kept showing, and the new screen was reported missing ("Cannot find key ... in the actions registry"). | Staging only, during development. |
| 27 Oct 2026 (c) | A style change did not appear after a restart; the browser kept receiving the previous stylesheet. | Staging only, during development. |

## 2. How Odoo serves its screens (why these can happen at all)
Odoo compiles all JavaScript, templates and styles into a few large **bundles** and stores each compiled bundle as an attachment: a row in
the database (`ir_attachment`, `url like '/web/assets/%'`) that points to a file in the **filestore** folder (`data_dir/filestore/<db>/`).
Every page asks for the bundle by that row. So the row and the file must exist together, and the row must be dropped when the sources change.

## 3. Root causes
**(1) Blank page, 25 Oct: the database and the filestore came from two different folders.**
One staging start used `--data-dir` pointing at a temporary scratch folder. Odoo compiled the bundles into that folder and wrote the rows into
the database. The scratch folder was later wiped; the database kept the rows. From then on every page asked for bundle files that no longer
existed, so the browser received nothing and showed a blank page. Business attachments were not affected (they had been written while the
normal data folder was in use), which is why no data was lost.

**(2) Unstyled screens, 27 Oct (a): a style the compiler cannot read.**
Odoo 20 compiles styles with libsass. A modern CSS expression, `min(100%, 250px)`, is a Sass function to libsass with incompatible units, so
the whole stylesheet failed to compile. Odoo does not stop: it serves the last good stylesheet or none, and the app looks broken everywhere,
not only on the new screen.

**(3) New code not loading, 27 Oct (b): an old server still held the port.**
Staging was restarted while the previous server process was still running on port 8369. The new process could not bind the port and stopped,
but the start script only checked "does something answer on 8369?", the old server answered, and the script reported success.

**(4) Old stylesheet after a restart, 27 Oct (c): compiled bundles are reused until the module is updated.**
Editing a style file on a running staging database does not, by itself, retire the compiled bundle rows. Without `-u <module>` (which drops
them) or deleting the bundle rows, Odoo keeps serving the previous compilation.

## 4. Fixes made (in the code, with checks that would have caught each one)
| Cause | Fix | Check |
|---|---|---|
| (1) | `migration/env.sh`: every script uses ONE persistent data folder (`~/.local/share/Odoo`); never a scratch folder. Dropping a database with `ei_drop_db` also removes its filestore. | `migration/check_filestore.py` compares every row with the disk. `serve.sh` runs it before starting and refuses to start on missing business files; missing bundles (derived data) are repaired only on request (`EI_REPAIR_ASSETS=1`). |
| (2) | The expressions are written so libsass passes them through (`#{"min(...)"}`). | The browser suite reads every served stylesheet and fails if it contains Odoo's `css_error_message` (`Session.cssErrors()` in `tests/e2e/lib.js`); every new screen is screenshot and looked at. |
| (3) | `migration/serve.sh` now refuses to start when the port is already in use, names the process holding it, and fails if the new server stops while starting. | Running it twice in a row now prints "port 8369 is already in use". |
| (4) | After changing styles or templates on staging: update the module (`-u`) or delete the bundle rows, then restart (`delete from ir_attachment where url like '/web/assets/%'`). | The browser suite always starts from a fresh copy updated with `-u` for every module (`tests/run_e2e.sh`). |

## 5. Why the live server is protected
* The data folder is fixed in `/etc/odoo/odoo.conf` (`data_dir = /var/lib/odoo`) by the installer, and the service always starts with that file. Nothing on the server uses a temporary folder.
* The nightly backup takes the database AND the filestore together (`deploy/backup.sh`), and the restore steps in `HANDOVER.md` put both back together. Restoring only one of the two recreates cause (1).
* Every update runs `odoo -u all` before the restart (`HANDOVER.md`, section 8), which drops stale bundles: cause (4) cannot occur.
* The service is managed by systemd (`systemctl restart odoo`), which stops the old process before starting the new one: cause (3) cannot occur.
* Code reaches the live server only after the tests pass on a copy; a stylesheet that does not compile fails the browser suite: cause (2).

## 6. If it ever happens anyway (a blank or unstyled page)
1. Look at the log: `sudo tail -100 /var/log/odoo/odoo-server.log`. A `FileNotFoundError` under `filestore` = cause (1); a Sass or "css" error = cause (2).
2. For missing bundles only (the rows point at `/web/assets/...`): `sudo -u odoo psql ei -c "delete from ir_attachment where url like '/web/assets/%'"` then `sudo systemctl restart odoo`. Odoo rebuilds them on the next page load. This is safe: bundles are derived from the code.
3. If business attachments (scans, PDFs) are missing, do NOT delete anything: restore the filestore from the backup taken with the same database.

## 7. Performance profile (staging, 27 Oct 2026)
Measured in a real browser at 1366x768 on the build laptop (4 cores, 8 GB, Odoo with one process, staging data: a few hundred records).
Times are from navigation until the page's main content is on screen, second visit; the slowest server call is shown beside it.

| Role | Page | Time | Slowest server call |
|---|---|---|---|
| Executive | first screen after sign-in (cold) | 2.2 s | |
| Executive | Home | 1.3 s | `ei.home/get_data` 0.37 s |
| Executive | Financial reports | 0.85 s | `get_statements` 0.25 s |
| Executive | Contracts list | 0.64 s | `get_views` 0.10 s |
| Finance | Home | 1.5 s | `ei.home/get_data` 0.35 s |
| Finance | Financial reports | 0.68 s | `get_statements` 0.16 s |
| Bank data entry | Home | 0.60 s | `ei.home/get_data` 0.11 s |
| Contract desk | Home | 0.51 s | `ei.home/get_data` 0.08 s |
| Contract desk | Contracts list | 0.41 s | `web_search_read` 0.05 s |

Reading: the roles that see money (executive, finance) have the heaviest Home, because it works out every figure from posted entries on each
visit; it is still well under 2 seconds. Nothing here says how it behaves with 50,000 journal lines or more: that has **not** been measured,
because the client's historical data is not loaded. Before go-live, load a year of real entries on a copy and repeat these measurements; the
first places to look are `ei.home.get_data` and `ei.report.financials.get_statements` (both read aggregated sums, which PostgreSQL indexes well).
