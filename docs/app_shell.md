# App shell (`ei_app_shell`): install, phone, tabs, undo

What it is for the people who use it is in `docs/ui/UI_GUIDE.md`. This page is for whoever maintains it.

| Piece | Where | Notes |
|---|---|---|
| Installable app | `controllers/webmanifest.py`, `views/head_templates.xml`, `static/img/` | Replaces Odoo's manifest (name, scope `/`, our colours and icons, no share target). Icons are drawn by `migration/make_app_icons.py`. The head allows pinch zoom (Odoo's forbids it) and reaches under a phone's notch (`viewport-fit=cover`; the page pads itself with the safe-area insets). Odoo's own service worker is kept (offline page only). |
| Phone bottom bar | `static/src/shell/bottom_nav.*`, `shell.scss` | Built from the person's own menus (`menu` service), so a role without a section gets no button. Under 768 px only; `body.ei-has-bn` pads the content. |
| Workspace tabs | `static/src/tabs/tabs_service.js` (service `ei_tabs`), `tab_strip.*` | A tab is a place (first action of the router's stack). Tabs are plain links, so Odoo's router navigates without reload and its unsaved-changes guard still applies. Stored in `localStorage` per database and user. Inserted in `web.WebClient` by template inheritance + `patch(WebClient, {components})`. |
| Undo / redo | `static/src/undo/undo.*` | Patches `Record.update` to record `{before, after}` for simple fields of the form's root record; inserted in `web.FormView`. Lines (x2many) are deliberately not tracked. |

Traps found while building it:
* `min(70vw, 280px)` in SCSS breaks the whole stylesheet (libsass cannot mix units): use `width` + `max-width`.
* `role="tablist"` needs `role="tab"` children (axe: aria-required-children); tabs that are page links are a `nav` with `aria-current="page"`.
* Odoo's router intercepts a click on any same-site `<a href="/odoo/...">` and navigates without a reload; that is how a tab (or a programmatic "go to this URL") switches page.
* `ACTION_MANAGER:UI-UPDATED` fires before the router has written the new URL; wait a moment (80 ms) before reading it.

Tests: `addons/ei_app_shell/tests/test_pwa.py` (manifest, icons, head) and `tests/e2e/specs/16_app_shell.js` (installability as Chromium judges it, bottom bar and sheet for four roles, tabs, undo and redo with the keyboard).
