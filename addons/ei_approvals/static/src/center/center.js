// The approvals centre: tabs (pending for me, urgent, returned, approved, rejected, my submissions, all, history), a sortable and
// searchable table (cards on a phone), and a review panel with everything a checker needs and three clear actions:
// Approve, Return for correction, Reject. Every decision is made on the server, which checks it again (role, not the maker,
// still pending, unchanged since submission); this screen only asks.
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { EiApprovalsTray } from "@ei_approvals/systray/approvals_tray";

const MODEL = "ei.approval.request";
const TABS = [
    ["pending", "Pending for me"], ["urgent", "Urgent"], ["returned", "Returned"], ["approved", "Approved"], ["rejected", "Rejected"],
    ["mine", "My submissions"], ["all", "All I can see"], ["history", "History"],
];
const COLS = [
    ["name", "Document"], ["type", "Type"], ["party", "Customer / party"], ["maker", "Submitted by"], ["approver", "Checker"],
    ["submitted", "Submitted"], ["amount", "Amount"], ["state", "Status"],
];

export class EiApprovalsCenter extends Component {
    static template = "ei_approvals.Center";
    static components = { EiApprovalsTray };
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.bus = useService("bus_service");
        const params = (this.props.action && this.props.action.params) || {};
        this.tabs = TABS;
        this.cols = COLS;
        this.state = proxy({
            tab: params.tab || "pending", search: "", flow: params.flow || "", status: params.state || "", dateFrom: "", dateTo: "",
            sort: params.tab === "history" ? "decided" : "submitted", desc: true, page: 0, limit: 25,
            data: null, loading: false, review: null, reviewBusy: false, ask: null, comment: "", reassign: "",
        });
        this.timer = null;
        onWillStart(async () => {
            await this.load();
            if (params.request_id) { await this.openReview(params.request_id); }
        });
        onMounted(() => {
            this.unsub = this.bus.subscribe("ei_approvals/changed", () => this.reloadSoon());
            this.bus.start();
        });
        onWillUnmount(() => { if (this.unsub) { this.unsub(); } clearTimeout(this.timer); });
    }

    // ------------------------------------------------------------------ list
    async load() {
        const s = this.state;
        s.loading = true;
        try {
            s.data = await this.orm.call(MODEL, "center_data", [], {
                tab: s.tab, search: s.search, flow: s.flow, state: s.status, date_from: s.dateFrom, date_to: s.dateTo,
                sort: s.sort, desc: s.desc, offset: s.page * s.limit, limit: s.limit,
            });
        } finally { s.loading = false; }
    }
    reloadSoon() {
        clearTimeout(this.timer);
        this.timer = setTimeout(async () => {
            await this.load();
            if (this.state.review && !this.state.reviewBusy) { await this.openReview(this.state.review.row.id, true); }
        }, 400);
    }
    setTab(t) { this.state.tab = t; this.state.page = 0; if (t === "history") { this.state.sort = "decided"; } this.load(); }
    onSearch(ev) { this.state.search = ev.target.value; this.state.page = 0; clearTimeout(this.timer); this.timer = setTimeout(() => this.load(), 300); }
    setFilter(key, ev) { this.state[key] = ev.target.value; this.state.page = 0; this.load(); }
    clearFilters() { Object.assign(this.state, { search: "", flow: "", status: "", dateFrom: "", dateTo: "", page: 0 }); this.load(); }
    sortBy(key) {
        const s = this.state;
        if (s.sort === key) { s.desc = !s.desc; } else { s.sort = key; s.desc = key === "submitted" || key === "amount" || key === "decided"; }
        this.load();
    }
    sortMark(key) { return this.state.sort === key ? (this.state.desc ? " ↓" : " ↑") : ""; }
    ariaSort(key) { return this.state.sort === key ? (this.state.desc ? "descending" : "ascending") : "none"; }
    page(delta) { const s = this.state; const max = Math.max(0, Math.ceil((s.data.total || 0) / s.limit) - 1); s.page = Math.min(max, Math.max(0, s.page + delta)); this.load(); }
    get pageText() {
        const s = this.state, t = (s.data && s.data.total) || 0;
        if (!t) { return "0"; }
        return `${s.page * s.limit + 1}–${Math.min(t, (s.page + 1) * s.limit)} of ${t}`;
    }
    tabCount(key) { return this.state.data && this.state.data.tabs ? this.state.data.tabs[key] : 0; }
    hasFilters() { const s = this.state; return !!(s.search || s.flow || s.status || s.dateFrom || s.dateTo); }
    statusClass(row) {
        if (row.needs_assignment) { return "is-bad"; }
        return { pending: row.overdue ? "is-bad" : "is-info", approved: "is-ok", returned: "is-warn", superseded: "is-warn", rejected: "is-bad", withdrawn: "is-muted" }[row.state] || "is-muted";
    }
    statusText(row) { return row.needs_assignment ? "Assignment required" : (row.state === "pending" && row.overdue ? "Overdue" : row.state_label); }

    // ------------------------------------------------------------------ review
    async openReview(id, quiet = false) {
        this.state.reviewBusy = !quiet;
        try {
            this.state.review = await this.orm.call(MODEL, "review_data", [[id]]);
            this.state.comment = ""; this.state.reassign = "";
        } finally { this.state.reviewBusy = false; }
    }
    closeReview() { this.state.review = null; this.state.ask = null; }
    ask(kind) {
        const r = this.state.review.row;
        const texts = {
            approve: { title: `Approve ${r.name}?`, body: `${r.type}${r.amount_text ? " · " + r.amount_text : ""}. It moves to its next stage at once (${r.type === "Cash voucher" ? "posted to the cash book" : "the next step of the work"}).`, button: "Approve", need: false, tone: "is-ok" },
            return: { title: `Return ${r.name} for correction?`, body: `It goes back to ${r.maker} with your note. They correct it and submit it again.`, button: "Return for correction", need: true, tone: "is-warn" },
            reject: { title: `Reject ${r.name}?`, body: `It is cancelled with your reason and ${r.maker} is told. This cannot be undone; a new entry would be needed.`, button: "Reject", need: true, tone: "is-bad" },
            withdraw: { title: `Withdraw ${r.name}?`, body: "It comes back to you as a draft, so you can correct it before submitting again.", button: "Withdraw", need: false, tone: "is-warn" },
        };
        this.state.ask = Object.assign({ kind, note: "", error: "" }, texts[kind]);
        setTimeout(() => { const el = document.querySelector(".ei-ap-ask textarea, .ei-ap-ask .ei-ap-btn.is-primary"); if (el) { el.focus(); } }, 50);
    }
    async confirm() {
        const a = this.state.ask;
        if (a.need && !a.note.trim()) { a.error = "Write the reason; the maker sees it."; return; }
        const id = this.state.review.row.id;
        this.state.reviewBusy = true;
        try {
            this.state.review = await this.orm.call(MODEL, "decide", [id, a.kind, a.note]);
            const done = { approve: "Approved.", return: "Returned for correction.", reject: "Rejected.", withdraw: "Withdrawn." }[a.kind];
            this.notification.add(`${done} ${this.state.review.row.name}`, { type: a.kind === "approve" ? "success" : "info" });
            this.state.ask = null;
            await this.load();
        } catch (e) {
            a.error = (e && e.data && e.data.message) || (e && e.message) || "It could not be done.";
            await this.openReview(id, true);
            await this.load();
        } finally { this.state.reviewBusy = false; }
    }
    async addComment() {
        if (!this.state.comment.trim()) { return; }
        this.state.review = await this.orm.call(MODEL, "add_comment", [this.state.review.row.id, this.state.comment]);
    }
    async reassign() {
        if (!this.state.reassign) { return; }
        await this.orm.call(MODEL, "action_reassign", [[this.state.review.row.id], parseInt(this.state.reassign, 10)]);
        await this.openReview(this.state.review.row.id, true);
        await this.load();
    }
    async openDocument() {
        const act = await this.orm.call(MODEL, "open_record_action", [this.state.review.row.id]);
        this.action.doAction(act);
    }
    isImage(d) { return d.kind === "image"; }
    // numbers and money right-aligned; a negative amount (a loss) in red
    cellClass(cell) {
        const t = this.str(cell).trim();
        const num = /^[-−]?\s*(Rs\.?|\$|PKR|USD)?\s*[-−]?[\d,]+(\.\d+)?$/.test(t) || /^[\d,]+(\.\d+)?\s*(Rs\.?|\$)?$/.test(t);
        const neg = num && /[-−]/.test(t);
        return (num ? "ei-ap-num is-r" : "") + (neg ? " is-neg" : "");
    }
    str(v) { return v === undefined || v === null ? "" : String(v); }
}

registry.category("actions").add("ei_approvals.center", EiApprovalsCenter);
