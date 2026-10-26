import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

const RECENT_KEY = "ei_party360_recent";
const TAB_KEY = "ei_party360_tab";
// One page, seven views of the same party. A tab exists only when the person's role can see something in it.
const TAB_DEFS = [
    { key: "overview", label: "Overview" },
    { key: "money", label: "Money", group: "money" },
    { key: "material", label: "Material", group: "material" },
    { key: "documents", label: "Documents", group: "documents", waiting: true },
    { key: "bank", label: "Bank", group: "bank", waiting: true },
    { key: "chains", label: "Contract to payment" },
    { key: "timeline", label: "History" },
];
// the four figures the overview leads with: the first four of these that have something in them (all real figures, none invented)
// the figures that mean "a person has something to do" (money received and confirmed is not one of them)
const WAITING = new Set(["d_das", "d_orders", "d_intake", "b_suggested", "p_diff", "l_to_invoice"]);
const SUMMARY_ORDER = ["f_ar", "f_ap", "m_remaining", "m_lifted", "l_to_invoice", "d_contracts", "d_das", "d_orders", "d_intake", "b_suggested", "p_diff"];
const SEARCH_DELAY = 220;
const CHAINS_SHOWN = 5;
const EVENTS_SHOWN = 8;

// Stroke icons (24x24); Odoo 20 does not style Font Awesome.
const ICONS = {
    search: "M11 4a7 7 0 100 14 7 7 0 000-14M21 21l-4.5-4.5",
    check: "M5 12.5l4.5 4.5L19 7",
    dots: "M5 12h.01M12 12h.01M19 12h.01",
    info: "M12 3a9 9 0 100 18 9 9 0 000-18M12 11v5M12 8v.01",
    chevron: "M9 6l6 6-6 6",
    refresh: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
    circle: "M12 3a9 9 0 100 18 9 9 0 000-18",
    minus: "M6 12h12",
};
const STAGE_ICON = { done: "check", active: "dots", todo: "circle", hidden: "minus" };
const STAGE_WORD = { done: "Done", active: "In progress", todo: "Not started", hidden: "Hidden" };
const KIND_LABEL = {
    contract: "Contract", da: "Delivery advice", order: "Daily order", lifting: "Truck loading",
    intake: "Supplier invoice", invoice: "Customer invoice", bank: "Bank line", statement: "Parent statement",
};

export class EiParty360 extends Component {
    static template = "ei_party360.Party360";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            query: "", results: [], active: -1, searching: false, open: false, searched: false,
            loading: false, error: false, data: null, explain: {}, recent: this.readRecent(), allChains: false, allEvents: false, tab: this.readTab(),
        });
        this.timer = null;
        onWillUnmount(() => clearTimeout(this.timer));
        onWillStart(async () => {
            const pid = this.props.action.params && this.props.action.params.partner_id;
            if (pid) {
                await this.load(pid);
            }
        });
    }

    // ---- per-viewer convenience only; the page works without it
    readRecent() {
        try {
            return JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]").slice(0, 5);
        } catch {
            return [];
        }
    }
    remember(partner) {
        try {
            const list = [{ id: partner.id, name: partner.name }].concat(this.state.recent.filter((r) => r.id !== partner.id)).slice(0, 5);
            window.localStorage.setItem(RECENT_KEY, JSON.stringify(list));
            this.state.recent = list;
        } catch {
            /* private window or blocked storage: ignore */
        }
    }

    readTab() { try { return window.sessionStorage.getItem(TAB_KEY) || "overview"; } catch { return "overview"; } }
    setTab(key, focus) {
        this.state.tab = key;
        try { window.sessionStorage.setItem(TAB_KEY, key); } catch { /* the tab just is not remembered */ }
        if (focus) { setTimeout(() => document.getElementById("ei-p360-tab-" + key)?.focus(), 0); }
    }
    onTabKey(ev, i) {
        const tabs = this.tabs;
        const go = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[ev.key];
        if (go === undefined) { return; }
        ev.preventDefault();
        this.setTab(tabs[(go + tabs.length) % tabs.length].key, true);
    }
    get tabs() {
        const d = this.state.data;
        if (!d) { return []; }
        return TAB_DEFS.filter((t) => {
            if (t.group) { return d.metrics.some((m) => m.group === t.group); }
            if (t.key === "chains") { return d.chains !== null; }
            if (t.key === "timeline") { return d.timeline.length > 0; }
            return true;
        }).map((t) => ({ ...t, badge: t.waiting ? d.metrics.filter((m) => m.group === t.group && WAITING.has(m.key)).reduce((n, m) => n + (m.count || 0), 0) : 0 }));
    }
    get tabKey() { return this.tabs.some((t) => t.key === this.state.tab) ? this.state.tab : "overview"; }
    // the figure cards of the open tab: the overview leads with four, a figure tab shows its own group
    get cards() {
        const d = this.state.data, key = this.tabKey;
        if (key === "overview") {
            const by = Object.fromEntries(d.metrics.map((m) => [m.key, m]));
            const present = SUMMARY_ORDER.map((k) => by[k]).filter(Boolean);
            return present.filter((m) => m.count > 0).concat(present.filter((m) => !m.count)).slice(0, 4);
        }
        return d.metrics.filter((m) => m.group === key && m.count > 0);
    }
    get panelQuiet() { const key = this.tabKey; return key === "overview" ? [] : this.state.data.metrics.filter((m) => m.group === key && !m.count); }
    // what needs a person: the document and bank figures with something in them
    get attention() { return this.state.data.metrics.filter((m) => WAITING.has(m.key) && m.count > 0); }
    get latest() { return this.state.data.timeline.slice(0, 4); }
    icon(name) { return ICONS[name] || ICONS.circle; }
    stageIcon(tone) { return ICONS[STAGE_ICON[tone] || "circle"]; }
    stageWord(tone) { return STAGE_WORD[tone] || ""; }
    kindLabel(kind) { return KIND_LABEL[kind] || kind; }
    // figures with something to show get a card; figures that are genuinely zero wait in one quiet list
    metricsOf(group) { return this.state.data.metrics.filter((m) => m.group === group.key && m.count > 0); }
    hasMetrics(group) { return this.metricsOf(group).length > 0; }
    get chains() { const c = this.state.data.chains; return this.state.allChains ? c : c.slice(0, CHAINS_SHOWN); }
    get events() { const e = this.state.data.timeline; return this.state.allEvents ? e : e.slice(0, EVENTS_SHOWN); }
    get moreChains() { return Math.max(0, this.state.data.chains.length - CHAINS_SHOWN); }
    get moreEvents() { return Math.max(0, this.state.data.timeline.length - EVENTS_SHOWN); }
    get quiet() { return this.state.data.metrics.filter((m) => m.count === 0); }

    // ---- search
    onInput(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this.timer);
        if (this.state.query.trim().length < 2) {
            this.state.results = [];
            this.state.open = false;
            this.state.searched = false;
            return;
        }
        this.timer = setTimeout(() => this.search(), SEARCH_DELAY);
    }
    async search() {
        const q = this.state.query.trim();
        this.state.searching = true;
        try {
            const res = await this.orm.call("ei.party360", "search_parties", [q]);
            if (q === this.state.query.trim()) {
                this.state.results = res;
                this.state.active = res.length ? 0 : -1;
                this.state.open = true;
                this.state.searched = true;
            }
        } catch {
            this.state.results = [];
            this.state.open = true;
            this.state.searched = true;
        }
        this.state.searching = false;
    }
    onKeydown(ev) {
        const n = this.state.results.length;
        if (ev.key === "ArrowDown" && n) {
            ev.preventDefault();
            this.state.open = true;
            this.state.active = (this.state.active + 1) % n;
        } else if (ev.key === "ArrowUp" && n) {
            ev.preventDefault();
            this.state.active = (this.state.active - 1 + n) % n;
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            const r = this.state.results[this.state.active];
            if (this.state.open && r) {
                this.pick(r);
            } else {
                clearTimeout(this.timer);
                this.search();
            }
        } else if (ev.key === "Escape") {
            this.state.open = false;
        }
    }
    async pick(r) {
        this.state.open = false;
        if (r.partner_id) {
            this.state.query = "";
            await this.load(r.partner_id);
        } else if (r.code_id) {
            await this.openRecord("ei.legacy.code", r.code_id);
        }
    }

    // ---- page
    async load(partnerId) {
        this.state.loading = true;
        this.state.error = false;
        this.state.explain = {};
        this.state.allChains = false;
        this.state.allEvents = false;
        try {
            this.state.data = await this.orm.call("ei.party360", "get_data", [partnerId]);
            this.remember(this.state.data.partner);
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || "We could not load this party.";
            this.state.data = null;
        }
        this.state.loading = false;
    }
    reload() { return this.load(this.state.data.partner.id); }

    toggleExplain(key) { this.state.explain[key] = !this.state.explain[key]; }

    async openFigure(m) {
        const act = await this.orm.call("ei.party360", "open_records", [this.state.data.partner.id, m.key]);
        if (act) {
            await this.action.doAction(act);
        }
    }
    async openRecord(model, resId) {
        if (!resId) {
            return;
        }
        const act = await this.orm.call("ei.party360", "open_record", [model, resId]);
        if (act) {
            await this.action.doAction(act);
        }
    }
    openContact() {
        return this.openRecord("res.partner", this.state.data.partner.id);
    }
}

registry.category("actions").add("ei_party360", EiParty360);
