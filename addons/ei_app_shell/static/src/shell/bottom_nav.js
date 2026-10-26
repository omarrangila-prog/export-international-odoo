import { Component, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Phone: the main sections as a bar at the bottom (thumb reach), the rest under "More" in a sheet. Built from the person's own menus, so a
// role without a section simply does not get its button. Desktop and tablet keep the top bar.
const PHONE = "(max-width: 767.98px)";
const HOME = "ei_ui_theme.menu_ei_home";
const ROOT = "ei_legacy_master.menu_ei_root";
const PRIORITY = ["Money", "Orders & Trucks", "Approvals", "Customers & Suppliers", "Bills & Invoices", "Month-end", "Reports", "Setup"];
const MAX_BUTTONS = 4;           // Home + three; the fifth place is "More"
const ICONS = {
    Home: "M3 11.5L12 4l9 7.5M5.5 10v10h13V10",
    Money: "M12 3a9 9 0 100 18 9 9 0 000-18M14.5 9.2c-.6-.8-1.5-1.2-2.5-1.2-1.4 0-2.5.8-2.5 1.9 0 2.6 5 1.4 5 4 0 1.1-1.1 2-2.6 2-1.1 0-2-.5-2.6-1.3M12 6.5V8M12 16v1.5",
    "Orders & Trucks": "M2.5 7h11v9h-11zM13.5 10h4l3 3v3h-7M7 19a1.7 1.7 0 100-3.4A1.7 1.7 0 007 19M17 19a1.7 1.7 0 100-3.4 1.7 1.7 0 000 3.4",
    Approvals: "M12 3a9 9 0 100 18 9 9 0 000-18M8 12.5l2.8 2.8L16 9.8",
    "Customers & Suppliers": "M9 11a3.2 3.2 0 100-6.4A3.2 3.2 0 009 11M3.5 19c.4-3 2.5-4.7 5.5-4.7s5.1 1.7 5.5 4.7M16.5 10.2a2.6 2.6 0 100-5.2M17 14.3c2 .3 3.3 1.7 3.6 4.2",
    "Bills & Invoices": "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6",
    "Month-end": "M4 6.5h16V20H4zM4 10.5h16M8 3.5v5M16 3.5v5",
    Reports: "M5 20V10M12 20V4M19 20v-7",
    Setup: "M12 15.2a3.2 3.2 0 100-6.4 3.2 3.2 0 000 6.4M19 12l1.7-1-1.5-2.7-1.9.5a6.7 6.7 0 00-1.6-.9L15.3 5h-3l-.4 2.1a6.7 6.7 0 00-1.6.9l-1.9-.5L6.9 10l1.7 1a6.8 6.8 0 000 1.9L6.9 14l1.5 2.7 1.9-.5c.5.4 1 .7 1.6.9l.4 2.1h3l.4-2.1c.6-.2 1.1-.5 1.6-.9l1.9.5 1.5-2.7-1.7-1c.1-.6.1-1.3 0-1.9",
    More: "M5 12h.01M12 12h.01M19 12h.01",
    chevron: "M9 6l6 6-6 6",
    close: "M6 6l12 12M18 6L6 18",
};

const leaves = (node) => (node.actionID ? [node] : []).concat(...(node.childrenTree || []).map(leaves));

export class EiBottomNav extends Component {
    static template = "ei_app_shell.BottomNav";

    setup() {
        this.menu = useService("menu");
        this.action = useService("action");
        this.tabs = useService("ei_tabs");
        this.mq = window.matchMedia(PHONE);
        this.state = proxy({ phone: this.mq.matches, sheet: null, keyboard: false, tick: 0 });
        this.onMq = () => { this.state.phone = this.mq.matches; this.sync(); };
        this.onUi = () => { this.state.tick++; };
        this.onViewport = () => {
            const vv = window.visualViewport;
            this.state.keyboard = !!vv && this.state.phone && vv.height < window.innerHeight * 0.75;      // a phone keyboard is open: the bar would sit on top of it
        };
        this.onKey = (ev) => { if (ev.key === "Escape" && this.state.sheet) { this.close(); } };
        onMounted(() => {
            this.mq.addEventListener("change", this.onMq);
            this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", this.onUi);
            window.visualViewport?.addEventListener("resize", this.onViewport);
            document.addEventListener("keydown", this.onKey);
            this.sync();
        });
        onWillUnmount(() => {
            this.mq.removeEventListener("change", this.onMq);
            this.env.bus.removeEventListener("ACTION_MANAGER:UI-UPDATED", this.onUi);
            window.visualViewport?.removeEventListener("resize", this.onViewport);
            document.removeEventListener("keydown", this.onKey);
            document.body.classList.remove("ei-has-bn");
        });
    }

    sync() { document.body.classList.toggle("ei-has-bn", this.state.phone && this.sections.length > 0); }

    get app() {
        const apps = this.menu.getApps();
        return apps.find((a) => a.xmlid === ROOT) || apps[0];
    }
    get sections() {
        const app = this.app;
        if (!app) { return []; }
        return this.menu.getMenuAsTree(app.id).childrenTree
            .map((s) => ({ key: s.id, name: s.name, home: s.xmlid === HOME, entries: leaves(s) }))
            .filter((s) => s.entries.length);
    }
    isCurrent(section) {
        this.state.tick;                                                 // read so that a new screen re-evaluates this
        const cur = this.action.currentController && this.action.currentController.action;
        return !!cur && section.entries.some((e) => e.actionID === cur.id || e.actionID === cur.xml_id || e.actionID === cur.path);
    }
    get buttons() {
        const all = this.sections;
        const home = all.find((s) => s.home);
        const rest = all.filter((s) => !s.home).sort((a, b) => this.rank(a) - this.rank(b));
        const shown = (home ? [home] : []).concat(rest.slice(0, MAX_BUTTONS - (home ? 1 : 0)));
        const more = rest.filter((s) => !shown.includes(s));
        const out = shown.map((s) => ({ key: "s" + s.key, label: s.home ? _t("Home") : s.name, icon: ICONS[s.name] || ICONS.More, section: s, on: this.isCurrent(s) }));
        if (more.length || this.tabs.tabs.length > 1) {
            out.push({ key: "more", label: _t("More"), icon: ICONS.More, more, on: more.some((s) => this.isCurrent(s)) });
        }
        return out;
    }
    rank(section) { const i = PRIORITY.indexOf(section.name); return i < 0 ? PRIORITY.length : i; }
    icon(name) { return ICONS[name] || ICONS.More; }

    async press(btn) {
        if (btn.section && btn.section.home) {
            this.state.sheet = null;
            return this.menu.selectMenu(btn.section.entries[0]);
        }
        const pages = this.tabs.tabs.length > 1
            ? [{ name: _t("Open pages"), pages: true, entries: this.tabs.tabs.map((t) => ({ id: t.id, name: t.title || _t("Page"), on: t.id === this.tabs.activeId })) }]
            : [];
        this.state.sheet = btn.more
            ? { title: _t("More"), groups: pages.concat(btn.more.map((s) => ({ name: s.name, entries: s.entries }))) }
            : { title: btn.section.name, groups: [{ name: "", entries: btn.section.entries }] };
    }
    async open(entry) {
        this.state.sheet = null;
        await this.menu.selectMenu(entry);
    }
    openPage(entry) { this.state.sheet = null; this.tabs.activate(entry.id); }
    closePage(entry) {
        this.tabs.close(entry.id);
        if (this.tabs.tabs.length < 2) { this.state.sheet = null; } else { this.state.sheet = Object.assign({}, this.state.sheet, { groups: this.state.sheet.groups.map((g) => (g.pages ? { ...g, entries: this.tabs.tabs.map((t) => ({ id: t.id, name: t.title || _t("Page"), on: t.id === this.tabs.activeId })) } : g)) }); }
    }
    close() { this.state.sheet = null; }
}

registry.category("main_components").add("ei_app_shell.BottomNav", { Component: EiBottomNav });
