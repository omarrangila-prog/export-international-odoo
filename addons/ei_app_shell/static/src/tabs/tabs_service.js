import { proxy } from "@odoo/owl";
import { router } from "@web/core/browser/router";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";

// Workspace tabs, like a browser's. Every PLACE you work in (a menu screen, a record's own action) is a tab; moving around inside a place
// (list -> record -> next record) stays in its tab. The pages you leave stay open as tabs, come back exactly where you left them (that
// screen or record; not the filters you typed), and are remembered in this browser for next time. A tab is a plain link, so the router
// navigates without reloading the application and Odoo's own unsaved-changes prompt still guards a dirty form.
const MAX_TABS = 8;
const HOME_XMLID = "ei_ui_theme.menu_ei_home";
const storeKey = () => `ei.tabs.v1:${session.db || ""}:${user.userId}`;

const readStore = () => {
    try {
        const v = JSON.parse(window.localStorage.getItem(storeKey()) || "null");
        return v && Array.isArray(v.tabs) ? v : null;
    } catch {
        return null;
    }
};
const writeStore = (tabs, activeId) => {
    try { window.localStorage.setItem(storeKey(), JSON.stringify({ tabs, activeId })); } catch { /* private window: tabs are simply not remembered */ }
};

// the place a screen belongs to: the first action of the stack (a record opened from a list is the same place as the list)
export const placeKey = (state) => {
    const first = (state.actionStack || [])[0];
    return String((first && (first.action || first.model)) || state.action || state.model || "");
};
const currentTitle = (state) => {
    // "Contracts · CT/2026/0003": the place, then the record or view inside it
    const stack = state.actionStack || [];
    const first = stack[0] && stack[0].displayName, last = stack.at(-1) && stack.at(-1).displayName;
    if (first && last && stack.length > 1 && first !== last) { return `${first} · ${last}`; }
    return first || last || document.title || "";
};
const currentUrl = () => window.location.pathname + window.location.search;
let counter = 0;
const newId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

// Navigate like a click on a link inside the application: the router handles it without a reload
export function followLink(url) {
    const a = document.createElement("a");
    a.href = url;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
}

export const tabsService = {
    dependencies: ["menu"],
    start(env, { menu }) {
        const stored = readStore();
        const state = proxy({ tabs: stored ? stored.tabs.slice(0, MAX_TABS) : [], activeId: stored ? stored.activeId : null });
        let pendingNew = null;          // a tab made with "+": it takes the place of the next screen instead of merging with an existing tab of the same place
        let pendingFrom = null;         // the address "+" was pressed on (unless that already was Home)
        let timer = null;

        const persist = () => writeStore(JSON.parse(JSON.stringify(state.tabs)), state.activeId);
        const homeUrl = () => {
            const home = menu.getAll().find((m) => m.xmlid === HOME_XMLID);
            return home && home.actionID ? `/odoo/action-${home.actionID}` : "/odoo";
        };

        function sync() {
            const key = placeKey(router.current);
            if (!key) { return; }
            const cur = { key, title: currentTitle(router.current), url: currentUrl() };
            let tab = null;
            if (pendingNew && cur.url === pendingFrom) { return; }    // "+" was pressed but Home is still loading: this is the page we left
            if (pendingNew) {
                tab = state.tabs.find((t) => t.id === pendingNew);
                pendingNew = null;
            }
            tab = tab || state.tabs.find((t) => t.id === state.activeId && t.key === key) || state.tabs.find((t) => t.key === key);
            if (!tab) {
                tab = { id: newId() };
                const at = state.tabs.findIndex((t) => t.id === state.activeId);
                state.tabs.splice(at < 0 ? state.tabs.length : at + 1, 0, tab);
                while (state.tabs.length > MAX_TABS) {                      // the oldest page that is not this one goes
                    const drop = state.tabs.find((t) => t.id !== tab.id);
                    state.tabs.splice(state.tabs.indexOf(drop), 1);
                }
            }
            Object.assign(tab, cur);
            state.activeId = tab.id;
            persist();
        }
        const soon = () => { clearTimeout(timer); timer = setTimeout(sync, 80); };     // the router writes the new address a moment after the screen changes

        env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", (ev) => { if (ev.detail !== "new") { soon(); } });
        window.addEventListener("popstate", soon);
        document.addEventListener("DOMContentLoaded", soon);
        const titleEl = document.querySelector("title");
        if (titleEl) { new MutationObserver(soon).observe(titleEl, { childList: true, characterData: true, subtree: true }); }
        env.bus.addEventListener("WEB_CLIENT_READY", soon);

        return {
            state,
            get tabs() { return state.tabs; },
            get activeId() { return state.activeId; },
            activate(id) {
                const tab = state.tabs.find((t) => t.id === id);
                if (tab && tab.id !== state.activeId) { followLink(tab.url); }
            },
            add() {
                if (state.tabs.length >= MAX_TABS) { return; }
                const url = homeUrl();
                const tab = { id: newId(), key: "", title: "Home", url };
                const at = state.tabs.findIndex((t) => t.id === state.activeId);
                state.tabs.splice(at < 0 ? state.tabs.length : at + 1, 0, tab);
                pendingNew = tab.id;
                pendingFrom = currentUrl() === url ? null : currentUrl();
                state.activeId = tab.id;
                persist();
                followLink(url);
                soon();                          // the page may already be Home: nothing navigates, so say what this tab shows
            },
            close(id) {
                const i = state.tabs.findIndex((t) => t.id === id);
                if (i < 0) { return; }
                const wasActive = id === state.activeId;
                state.tabs.splice(i, 1);
                if (!state.tabs.length) {
                    state.activeId = null;
                    persist();
                    followLink(homeUrl());
                    return;
                }
                if (wasActive) {
                    const next = state.tabs[Math.min(i, state.tabs.length - 1)];
                    state.activeId = next.id;
                    persist();
                    followLink(next.url);
                } else {
                    persist();
                }
            },
            closeOthers(id) {
                const keep = state.tabs.find((t) => t.id === id);
                if (keep) { state.tabs.splice(0, state.tabs.length, keep); persist(); this.activate(id); }
            },
            maxTabs: MAX_TABS,
        };
    },
};

registry.category("services").add("ei_tabs", tabsService);
