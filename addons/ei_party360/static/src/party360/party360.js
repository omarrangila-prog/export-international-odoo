import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

const RECENT_KEY = "ei_party360_recent";
const SEARCH_DELAY = 220;

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
            loading: false, error: false, data: null, explain: {}, recent: this.readRecent(),
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

    icon(name) { return ICONS[name] || ICONS.circle; }
    stageIcon(tone) { return ICONS[STAGE_ICON[tone] || "circle"]; }
    stageWord(tone) { return STAGE_WORD[tone] || ""; }
    kindLabel(kind) { return KIND_LABEL[kind] || kind; }
    metricsOf(group) { return this.state.data.metrics.filter((m) => m.group === group.key); }
    hasMetrics(group) { return this.metricsOf(group).length > 0; }

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
