import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

// Financial reports (PREVIEW): profit and loss, balance sheet, trial balance and cash flow on one page with a shared period, a strip of
// headline figures, what the money is made of, who the biggest customers are, the checks that say whether the books agree, a row-by-row
// drill-down to the posted items, and a PDF. Every figure comes from `ei.report.financials`; this page only lays it out.
const TABS = [
    { key: "summary", label: "Summary" },
    { key: "pnl", label: "Profit and loss" },
    { key: "balance_sheet", label: "Balance sheet" },
    { key: "trial_balance", label: "Trial balance" },
    { key: "cash_flow", label: "Cash flow" },
];
const fmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export class EiReportWorkspace extends Component {
    static template = "ei_reports.Workspace";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const wanted = this.props.action.params && this.props.action.params.statement;
        this.tabs = TABS;
        this.state = proxy({ loading: true, error: "", data: null, tab: TABS.some((t) => t.key === wanted) ? wanted : "summary", period: "month", from: "", to: "", choices: [], note: "" });
        onWillStart(async () => {
            this.state.choices = await this.orm.call("ei.report.financials", "period_choices", []).catch(() => []);
            const first = this.state.choices.find((c) => c.key === this.state.period);
            if (first) { this.state.from = first.date_from; this.state.to = first.date_to; }
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call("ei.report.financials", "get_statements", [this.state.from, this.state.to]);
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || "The figures could not be loaded. Nothing was changed.";
            this.state.data = null;
        }
        this.state.loading = false;
    }

    money(v) { return (v < 0 ? "-" : "") + fmt.format(Math.abs(v || 0)); }
    pct(part, whole) { return whole ? Math.max(2, Math.round((Math.abs(part) / Math.abs(whole)) * 100)) : 0; }
    get d() { return this.state.data; }
    get label() { return TABS.find((t) => t.key === this.state.tab).label; }
    get pdfUrl() {
        const d = this.d;
        return d ? `/ei_reports/financial.pdf?statement=${this.state.tab}&date_from=${d.period.date_from}&date_to=${d.period.date_to}` : "#";
    }
    get periodText() {
        const p = this.d && this.d.period;
        return p ? (this.state.tab === "balance_sheet" ? `As at ${p.date_to}` : `${p.date_from} to ${p.date_to}`) : "";
    }
    get costTotal() { return this.d ? this.d.composition.reduce((t, r) => t + r.amount, 0) : 0; }
    get customerTotal() { return this.d ? this.d.ranking.reduce((t, r) => t + r.amount, 0) : 0; }
    get failedChecks() { return this.d ? this.d.checks.filter((c) => !c.ok).length : 0; }

    setTab(key, focus) {
        this.state.tab = key;
        if (focus) { setTimeout(() => document.getElementById("ei-ws-tab-" + key)?.focus(), 0); }
    }
    onTabKey(ev, i) {
        const go = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[ev.key];
        if (go === undefined) { return; }
        ev.preventDefault();
        this.setTab(TABS[(go + TABS.length) % TABS.length].key, true);
    }
    async choose(c) {
        this.state.period = c.key;
        this.state.from = c.date_from;
        this.state.to = c.date_to;
        await this.load();
    }
    async applyCustom() {
        this.state.period = "custom";
        await this.load();
    }
    onFrom(ev) { this.state.from = ev.target.value; }
    onTo(ev) { this.state.to = ev.target.value; }

    async openAccount(row, cumulative) {
        try {
            const act = await this.orm.call("ei.report.financials", "open_lines", [row.account_id, this.d.period.date_from, this.d.period.date_to, !!cumulative]);
            await this.action.doAction(act);
        } catch (e) {
            this.state.note = (e && e.data && e.data.message) || "Could not open those items.";
        }
    }
    openCustomer(r) { return this.action.doAction({ type: "ir.actions.client", tag: "ei_party360", params: { partner_id: r.partner_id } }); }
    openSchedule() { return this.action.doAction("ei_reports.action_report_schedule"); }
}

registry.category("actions").add("ei_reports_workspace", EiReportWorkspace);
