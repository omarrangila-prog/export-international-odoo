// Top bar: "Approvals (n)" for a checker (requests waiting for them) and a bell with unread notifications (new requests, entries
// approved / returned / rejected, overdue). Counts come from the server for the signed-in person; they update live through the bus
// when the server pushes a change, and are re-read every minute and when the window gets focus (in case live updates are blocked).
import { Component, onMounted, onWillStart, onWillUnmount, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REQ = "ei.approval.request";
const NOTICE = "ei.approval.notice";

export class EiApprovalsTray extends Component {
    static template = "ei_approvals.Tray";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.bus = useService("bus_service");
        this.state = proxy({ counts: null, open: false, items: [], busy: false });
        this.onDoc = (ev) => { if (this.state.open && !ev.target.closest(".ei-ap-tray")) { this.state.open = false; } };
        this.onKey = (ev) => { if (ev.key === "Escape" && this.state.open) { this.state.open = false; } };
        this.onFocus = () => this.refresh();
        onWillStart(() => this.refresh());
        onMounted(() => {
            this.unsub = this.bus.subscribe("ei_approvals/changed", (p) => this.onPush(p));
            this.bus.start();
            this.timer = setInterval(() => this.refresh(), 60000);
            this.late = setTimeout(() => this.env.bus.trigger("EI_BADGES", { Approvals: this.pending || 0 }), 1500);   // the phone bar may mount after us
            document.addEventListener("click", this.onDoc, true);
            document.addEventListener("keydown", this.onKey);
            window.addEventListener("focus", this.onFocus);
        });
        onWillUnmount(() => {
            if (this.unsub) { this.unsub(); }
            clearInterval(this.timer); clearTimeout(this.late);
            document.removeEventListener("click", this.onDoc, true);
            document.removeEventListener("keydown", this.onKey);
            window.removeEventListener("focus", this.onFocus);
        });
    }

    async refresh() {
        try { this.state.counts = await this.orm.call(REQ, "counts", []); } catch { /* signed out or offline */ }
        this.env.bus.trigger("EI_BADGES", { Approvals: this.pending || 0 });           // the phone bar shows the same count
        if (this.state.open) { await this.loadItems(); }
    }
    async loadItems() {
        const r = await this.orm.call(NOTICE, "inbox", [12]);
        this.state.items = r.items;
        this.state.counts = r.counts;
    }
    onPush(p) {
        // one toast per new event (the server sends it once); never repeated, never flashing
        if (p && p.toast) { this.notification.add(p.name ? `${p.toast}: ${p.name}` : p.toast, { type: "info" }); }
        this.refresh();
    }
    get showPill() { const c = this.state.counts; return !!c && (c.is_checker || c.pending_for_me > 0); }
    get pending() { return this.state.counts ? this.state.counts.pending_for_me : 0; }
    get overdue() { return this.state.counts ? this.state.counts.overdue_for_me : 0; }
    get unread() { return this.state.counts ? this.state.counts.unread : 0; }

    async toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) { await this.loadItems(); }
    }
    openCenter(tab = "pending", requestId = false) {
        this.state.open = false;
        this.action.doAction({ type: "ir.actions.client", tag: "ei_approvals.center", name: "Approvals", params: { tab, request_id: requestId } },
            { clearBreadcrumbs: false });
    }
    async openItem(item) {
        if (!item.read) { this.state.counts = await this.orm.call(NOTICE, "mark_read", [[item.id]]); }
        this.openCenter(item.kind === "request" || item.kind === "escalated" || item.kind === "assignment" ? "pending" : "mine", item.request_id);
    }
    async markAll() {
        this.state.counts = await this.orm.call(NOTICE, "mark_read", [false]);
        this.state.items = this.state.items.map((i) => Object.assign({}, i, { read: true }));
    }
    tone(item) {
        if (item.kind === "rejected") { return "is-bad"; }
        if (item.kind === "returned" || item.kind === "superseded" || item.kind === "assignment") { return "is-warn"; }
        if (item.kind === "approved") { return "is-ok"; }
        if (item.overdue || item.kind === "escalated") { return "is-bad"; }
        return "is-info";
    }
}

registry.category("systray").add("ei_approvals_tray", { Component: EiApprovalsTray }, { sequence: 2 });
