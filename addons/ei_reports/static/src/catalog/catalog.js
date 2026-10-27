import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

// The report catalog: every report the business asked for, with what it answers, how it is worked out, where the numbers come from and
// whether it is delivered, partial, blocked or not built. A report that is not built is listed with the reason, never hidden.
const STATUS = {
    delivered: { label: "Built, tested on sample data", tone: "ok" },
    preview: { label: "Preview", tone: "preview" },
    partial: { label: "Partly there", tone: "info" },
    pending_source: { label: "Blocked: needs an approval or data", tone: "warn" },
    not_built: { label: "Not built yet", tone: "muted" },
};
// The readiness ladder: nothing is past "Tested on sample data" until real books are loaded and finance signs.
const LADDER = [
    ["ui_available", "Screen available"], ["demo_tested", "Tested on sample data"], ["data_validated", "Checked against real books"],
    ["finance_approved", "Approved by finance"], ["production_verified", "Verified in daily use"],
];
const AREAS = ["Money", "Trade and invoicing", "Management and controls"];

export class EiReportCatalog extends Component {
    static template = "ei_reports.Catalog";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ loading: true, error: false, items: [], q: "", area: "all", only: "open", note: "" });
        this.areas = AREAS;
        onWillStart(() => this.load());
    }
    async load() {
        this.state.loading = true;
        try { this.state.items = await this.orm.call("ei.report.catalog", "get_catalog", []); this.state.error = false; } catch { this.state.error = true; }
        this.state.loading = false;
    }
    statusOf(i) { return STATUS[i.status] || STATUS.not_built; }
    ladder(i) {
        const at = LADDER.findIndex(([k]) => k === i.readiness);
        return LADDER.map(([key, label], n) => ({ key, label, done: at >= 0 && n <= at }));
    }
    get counts() {
        const c = { delivered: 0, preview: 0, partial: 0, pending_source: 0, not_built: 0 };
        for (const i of this.state.items) { c[i.status] = (c[i.status] || 0) + 1; }
        return c;
    }
    get shown() {
        const q = this.state.q.trim().toLowerCase();
        return this.state.items.filter((i) => {
            if (this.state.area === "fav" && !i.favourite) { return false; }
            if (!["all", "fav"].includes(this.state.area) && i.area !== this.state.area) { return false; }
            if (this.state.only === "open" && !i.can_open) { return false; }
            return !q || `${i.title} ${i.question} ${i.definition} ${i.source}`.toLowerCase().includes(q);
        });
    }
    group(area) { return this.shown.filter((i) => i.area === area); }
    setArea(a) { this.state.area = a; }
    onSearch(ev) { this.state.q = ev.target.value; }
    onOnly(ev) { this.state.only = ev.target.checked ? "all" : "open"; }
    open(i) { return this.action.doAction(i.action); }
    async toggle(i) {
        try { i.favourite = await this.orm.call("ei.report.catalog", "toggle_favourite", [i.key]); this.state.note = i.favourite ? `${i.title} is now a favourite.` : `${i.title} is no longer a favourite.`; }
        catch { this.state.note = "Could not change the favourite. Nothing was changed."; }
    }
}

registry.category("actions").add("ei_reports_catalog", EiReportCatalog);
