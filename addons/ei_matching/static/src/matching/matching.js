import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { iconPath } from "@ei_ui_theme/common/icons";

const MODEL = "ei.matching";
const SEARCH_DELAY = 250;
const DEFER = [[1, "Until tomorrow"], [3, "For 3 days"], [7, "For a week"]];
const EMPTY_TEXT = {
    check: "Every bank line has been looked at. New lines appear here when a statement is imported.",
    allocate: "No confirmed payment is waiting for invoices.",
    unidentified: "No payment is waiting for its payer to be found.",
    duplicates: "No line looks like a repeat.",
};
const TOLERANCE = 0.004;

const num = (v) => parseFloat(String(v === undefined || v === null ? "" : v).replace(/,/g, "")) || 0;
const round2 = (v) => Math.round(v * 100) / 100;
const money = (v) => round2(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

export class EiMatching extends Component {
    static template = "ei_matching.Matching";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            loading: true, error: false, queue: null, tab: "check", q: "", journal: "", deferred: false,
            selected: null, pinned: null, saved: false, detail: null, detailLoading: false, detailError: false, step: "queue",
            draft: {}, proposal: null, pick: null, note: "", partyTerm: "", partyResults: [], partyOpen: false, searchedParty: false,
            changeParty: false, dialog: null, deferMenu: false, busy: false, toast: null,
        });
        this.deferChoices = DEFER;
        this.timers = { search: null, party: null, toast: null };
        this.seq = { queue: 0, detail: 0 };
        this.onKey = (ev) => this.handleKey(ev);
        onWillStart(() => this.start());
        onMounted(() => document.addEventListener("keydown", this.onKey));
        onWillUnmount(() => {
            document.removeEventListener("keydown", this.onKey);
            Object.values(this.timers).forEach(clearTimeout);
        });
    }

    // Home opens this screen on one line ("Match bank payment" task): show that line, in the list it belongs to
    async start() {
        const target = this.props.action.params && this.props.action.params.line_id;
        if (!target) { return this.loadQueue(); }
        const s = this.state;
        try {
            const d = await this.orm.call(MODEL, "detail", [target]);
            s.tab = { new: "check", proposed: "check", verified: "allocate", unidentified: "unidentified", duplicate: "duplicates" }[d.line.state] || "check";
            await this.loadQueue();
            this.setDetail(d);
            s.selected = target;
            s.pinned = this.items.some((i) => i.id === target) ? null : target;
            s.step = "decide";
        } catch {
            await this.loadQueue();
        }
    }

    // ------------------------------------------------------------------ helpers for the template
    icon(name) { return iconPath(name); }
    money(v) { return money(v); }
    get items() { return this.state.queue ? this.state.queue.items : []; }
    get emptyText() { return this.state.deferred ? "Nothing is put aside." : EMPTY_TEXT[this.state.tab]; }
    get d() { return this.state.detail; }
    journalOn(j) { return String(j.id) === String(this.state.journal); }
    get canReview() { return !!(this.state.queue && this.state.queue.can_review); }
    // a line the officer has just finished stays on screen (with its effect) even though it has left the list
    get leftTheList() { return !!(this.state.selected && this.state.pinned === this.state.selected && !this.items.some((i) => i.id === this.state.selected)); }
    get verified() { return !!(this.d && this.d.line.state === "verified"); }
    get isDuplicate() { return !!(this.d && this.d.line.state === "duplicate"); }
    get showItems() { return !!(this.d && (this.verified || this.d.preview_party) && this.d.open_items.length + this.d.foreign_items > 0); }
    get needsNote() {
        const p = this.state.pick, s = this.d && this.d.suggestion;
        return !!p && !(s && s.partner_id === p.partner_id && s.kind === "approved_alias");
    }
    get confirmLabel() {
        const p = this.state.pick;
        if (!p) { return ""; }
        return this.d.line.inbound ? `Confirm that ${p.name} paid` : `Confirm that ${p.name} was paid`;
    }
    get showPartyPicker() { return !!this.d && (!this.d.party || this.state.changeParty) && !this.isDuplicate; }
    get typed() { return round2(Object.values(this.state.draft).reduce((t, v) => t + num(v), 0)); }
    get left() { return round2(this.d.total - this.typed); }
    get savedMap() { return Object.fromEntries(this.d.allocations.map((a) => [a.invoice_id, round2(a.amount)])); }
    get draftChanged() {
        const saved = this.savedMap, cur = {};
        for (const [id, v] of Object.entries(this.state.draft)) { if (num(v) > 0) { cur[id] = round2(num(v)); } }
        const ids = new Set([...Object.keys(saved), ...Object.keys(cur)]);
        return [...ids].some((id) => Math.abs((saved[id] || 0) - (cur[id] || 0)) > TOLERANCE);
    }
    rowProblem(it) {
        const v = num(this.state.draft[it.invoice_id]);
        if (v < 0) { return "An amount cannot be negative."; }
        if (v > it.available + TOLERANCE) {
            return it.claimed > 0 ? `Only ${it.available_text} is left: another bank line already claims ${it.claimed_text}.` : `Only ${it.available_text} is open on this invoice.`;
        }
        return "";
    }
    get draftProblem() {
        if (this.typed > this.d.total + TOLERANCE) { return `That is more than the payment (${this.d.line.amount_text}).`; }
        const bad = this.d.open_items.find((it) => this.rowProblem(it));
        return bad ? `${bad.name}: ${this.rowProblem(bad)}` : "";
    }
    get canSave() { return !!this.d.can.allocate && this.draftChanged && !this.draftProblem && !this.state.busy; }
    get dialogTitle() {
        return { unidentified: "Mark as unidentified", reject: "Reject this bank line", ask: "Ask for evidence", changeParty: "Change the party?" }[this.state.dialog.kind];
    }
    get dialogHelp() {
        return {
            unidentified: "Use this when nobody can say yet who paid. The line stays in the statement. If the statement is posted like this, the money waits on the bank suspense account until someone finds the payer.",
            reject: "A rejected line is left out of the books. Use it for a line that should not be in the statement, such as a repeat of a payment already counted.",
            ask: "This is written on the bank line, and the person you choose gets a reminder. It does not change anything else.",
            changeParty: `The invoices already allocated to ${this.d && this.d.party ? this.d.party.name : "the current party"} will be removed, because they belong to someone else. Nothing is posted by this.`,
        }[this.state.dialog.kind];
    }
    get dialogLabel() {
        return { unidentified: "What did you try? (optional)", reject: "Why is it rejected? (required)", ask: "What do you need? (required)", changeParty: "" }[this.state.dialog.kind];
    }
    get dialogCta() {
        return { unidentified: "Mark unidentified", reject: "Reject line", ask: "Write it on the line", changeParty: "Remove allocations and change party" }[this.state.dialog.kind];
    }

    // ------------------------------------------------------------------ feedback
    say(text, kind = "ok") {
        clearTimeout(this.timers.toast);
        this.state.toast = { text, kind };
        this.timers.toast = setTimeout(() => { this.state.toast = null; }, 6000);
    }
    errorText(e) { return (e && e.data && e.data.message) || "Something went wrong. Nothing was changed."; }

    // ------------------------------------------------------------------ the queue
    async loadQueue() {
        const s = this.state, mine = ++this.seq.queue;
        try {
            const res = await this.orm.call(MODEL, "queue", [s.tab, s.q, s.journal ? Number(s.journal) : false, s.deferred]);
            if (mine !== this.seq.queue) { return null; }
            s.queue = res;
            s.error = false;
        } catch {
            if (mine === this.seq.queue) { s.error = true; }
        }
        s.loading = false;
        return s.queue;
    }
    // after the list changed, keep the same line if it is still there; otherwise move to the one that took its place
    async refreshQueue(previousIndex = -1) {
        const s = this.state;
        await this.loadQueue();
        if (!s.queue) { return; }
        const items = s.queue.items;
        if (items.some((i) => i.id === s.selected) || (s.pinned && s.pinned === s.selected)) { return; }
        const next = items.length ? items[Math.min(Math.max(previousIndex, 0), items.length - 1)] : null;
        await this.select(next ? next.id : null);
    }
    async setTab(key) {
        const s = this.state;
        s.tab = key;
        s.deferred = false;
        s.selected = null;
        await this.loadQueue();
        await this.select(this.items.length ? this.items[0].id : null);
    }
    async toggleDeferred() {
        this.state.deferred = !this.state.deferred;
        this.state.selected = null;
        await this.loadQueue();
        await this.select(this.items.length ? this.items[0].id : null);
    }
    onSearch(ev) {
        this.state.q = ev.target.value;
        clearTimeout(this.timers.search);
        this.timers.search = setTimeout(async () => {
            await this.loadQueue();
            if (!this.items.some((i) => i.id === this.state.selected)) { await this.select(this.items.length ? this.items[0].id : null); }
        }, SEARCH_DELAY);
    }
    async onJournal(ev) {
        this.state.journal = ev.target.value;
        await this.loadQueue();
        if (!this.items.some((i) => i.id === this.state.selected)) { await this.select(this.items.length ? this.items[0].id : null); }
    }
    async onRefresh() {
        const idx = this.items.findIndex((i) => i.id === this.state.selected);
        await this.refreshQueue(idx);
        if (this.state.selected) { await this.select(this.state.selected, { keepStep: true }); }
        this.say("List refreshed.");
    }

    // ------------------------------------------------------------------ one line
    resetDecision() {
        Object.assign(this.state, { pick: null, note: "", partyTerm: "", partyResults: [], partyOpen: false, searchedParty: false, changeParty: false, deferMenu: false, proposal: null });
    }
    setDetail(d) {
        const s = this.state;
        s.detail = d;
        s.draft = Object.fromEntries(d.allocations.map((a) => [a.invoice_id, String(a.amount)]));
        s.detailError = false;
    }
    async select(id, { step, keepStep } = {}) {
        const s = this.state, mine = ++this.seq.detail;
        if (s.pinned !== id) { s.pinned = null; s.saved = false; }
        s.selected = id;
        this.resetDecision();
        if (step) { s.step = step; } else if (!keepStep && !id) { s.step = "queue"; }
        if (!id) { s.detail = null; return; }
        s.detailLoading = true;
        try {
            const d = await this.orm.call(MODEL, "detail", [id]);
            if (mine === this.seq.detail) { this.setDetail(d); }
        } catch {
            if (mine === this.seq.detail) { s.detail = null; s.detailError = true; }
        }
        if (mine === this.seq.detail) { s.detailLoading = false; }
    }
    back() { this.state.step = "queue"; }
    async nextPayment() {
        const next = this.items[0];
        this.state.pinned = null;
        this.state.saved = false;
        await this.select(next ? next.id : null, { step: next ? "decide" : "queue" });
    }
    showStep(step) { this.state.step = step; }

    // ------------------------------------------------------------------ who paid
    onPartyInput(ev) {
        const s = this.state;
        s.partyTerm = ev.target.value;
        clearTimeout(this.timers.party);
        if (s.partyTerm.trim().length < 2) { s.partyResults = []; s.partyOpen = false; s.searchedParty = false; return; }
        this.timers.party = setTimeout(async () => {
            const term = s.partyTerm;
            try {
                const res = await this.orm.call(MODEL, "search_party", [term]);
                if (term === s.partyTerm) { s.partyResults = res; s.partyOpen = true; s.searchedParty = true; }
            } catch { s.partyResults = []; }
        }, SEARCH_DELAY);
    }
    pick(partnerId, name) {
        Object.assign(this.state, { pick: { partner_id: partnerId, name }, partyOpen: false, partyTerm: "", partyResults: [], note: "" });
    }
    cancelPick() { Object.assign(this.state, { pick: null, note: "", changeParty: false }); }
    startChange() { this.state.changeParty = true; }
    onNote(ev) { this.state.note = ev.target.value; }
    async confirmParty(clear = false) {
        const s = this.state, p = s.pick;
        if (!p) { return; }
        if (this.needsNote && !s.note.trim()) {
            this.say("Write how you know it was them (for example: payment slip checked, or the bank confirmed by phone).", "bad");
            return;
        }
        if (!clear && this.d.allocations.length && this.d.party && this.d.party.partner_id !== p.partner_id) {
            s.dialog = { kind: "changeParty", text: "" };
            return;
        }
        await this.run(() => this.orm.call(MODEL, "confirm_party", [this.d.line.id, p.partner_id, s.note.trim() || false, clear]), "allocate");
    }

    // ------------------------------------------------------------------ which invoices
    setAmount(id, ev) { this.state.draft[id] = ev.target.value; }
    fill(it) {
        const current = num(this.state.draft[it.invoice_id]);
        this.state.draft[it.invoice_id] = String(round2(Math.max(0, Math.min(it.available, this.left + current))));
    }
    clearDraft() { this.state.draft = {}; this.state.proposal = null; }
    async askProposal() {
        this.state.busy = true;
        try {
            const res = await this.orm.call(MODEL, "suggest_allocation", [this.d.line.id]);
            this.state.draft = Object.fromEntries(res.items.map((i) => [i.invoice_id, String(i.amount)]));
            this.state.proposal = res;
        } catch (e) {
            this.say(this.errorText(e), "bad");
        }
        this.state.busy = false;
    }
    async saveAllocations() {
        const items = Object.entries(this.state.draft).map(([id, v]) => ({ invoice_id: Number(id), amount: num(v) })).filter((i) => i.amount > 0);
        await this.run(() => this.orm.call(MODEL, "set_allocations", [this.d.line.id, items]), "", true);
    }

    // ------------------------------------------------------------------ the other decisions
    openDialog(kind) {
        const text = kind === "reject" && this.isDuplicate && this.d.duplicate_of
            ? `Duplicate of the line of ${this.d.duplicate_of.date_text} (${this.d.duplicate_of.amount_text}) in ${this.d.duplicate_of.statement}.` : "";
        this.state.dialog = { kind, text, user: "" };
        setTimeout(() => {
            const first = document.querySelector(".ei-mt-dialog select, .ei-mt-dialog textarea, .ei-mt-dialog button");
            if (first) { first.focus(); }
        }, 60);
    }
    toggleDeferMenu() { this.state.deferMenu = !this.state.deferMenu; }
    closeDialog() { this.state.dialog = null; }
    onDialogText(ev) { this.state.dialog.text = ev.target.value; }
    onDialogUser(ev) { this.state.dialog.user = ev.target.value; }
    async submitDialog() {
        const dlg = this.state.dialog, id = this.d.line.id;
        if ((dlg.kind === "reject" || dlg.kind === "ask") && !dlg.text.trim()) {
            this.say(dlg.kind === "reject" ? "A rejection needs a reason." : "Say what you need.", "bad");
            return;
        }
        if (dlg.kind === "changeParty") {
            this.state.dialog = null;
            await this.confirmParty(true);
            return;
        }
        const call = {
            unidentified: () => this.orm.call(MODEL, "mark_unidentified", [id, dlg.text.trim() || false, true]),
            reject: () => this.orm.call(MODEL, "reject", [id, dlg.text.trim()]),
            ask: () => this.orm.call(MODEL, "ask_evidence", [id, dlg.text.trim(), dlg.user ? Number(dlg.user) : false]),
        }[dlg.kind];
        this.state.dialog = null;
        await this.run(call);
    }
    async defer(days) {
        this.state.deferMenu = false;
        await this.run(() => this.orm.call(MODEL, "defer", [this.d.line.id, days]));
    }
    async undefer() { await this.run(() => this.orm.call(MODEL, "undefer", [this.d.line.id])); }

    // one place that runs a decision, shows the outcome and moves on to the next line. A confirmed party moves the line to
    // "Waiting for allocation": the screen follows it there, so step 2 (the invoices) is right in front of the officer.
    async run(call, followToTab = "", stay = false) {
        const s = this.state;
        if (s.busy) { return; }
        s.busy = true;
        const index = this.items.findIndex((i) => i.id === s.selected);
        try {
            const res = await call();
            this.resetDecision();
            this.setDetail(res.detail);
            this.say(res.message);
            if (followToTab && s.tab !== followToTab) { s.tab = followToTab; s.deferred = false; }
            s.pinned = stay ? s.selected : null;
            s.saved = stay;
            await this.refreshQueue(followToTab ? 0 : index);
        } catch (e) {
            this.say(this.errorText(e), "bad");
        }
        s.busy = false;
    }

    // ------------------------------------------------------------------ open real records
    openLine() { return this.openRecord("ei.bank.import.line", this.d.line.id); }
    openStatement() { return this.openRecord("ei.bank.import", this.d.batch.id); }
    openInvoice(id) { return this.openRecord("account.move", id); }
    openRecord(model, id) {
        return this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]], target: "current" });
    }
    openParty(partnerId) { return this.action.doAction({ type: "ir.actions.client", tag: "ei_party360", params: { partner_id: partnerId } }); }
    openTwin(id) { return this.select(id, { keepStep: true }); }

    // ------------------------------------------------------------------ keyboard
    handleKey(ev) {
        const s = this.state;
        if (ev.key === "Escape") {
            if (s.dialog) { this.closeDialog(); ev.stopPropagation(); } else if (s.partyOpen) { s.partyOpen = false; } else if (s.deferMenu) { s.deferMenu = false; }
            return;
        }
        const tag = (ev.target && ev.target.tagName) || "";
        if (/INPUT|TEXTAREA|SELECT/.test(tag) || s.dialog || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
        if (ev.key !== "/" && ev.target && ev.target.closest && ev.target.closest(".ei-mt-decide, .ei-mt-evidence")) { return; }   // there the arrows scroll
        if (ev.key === "/") {
            ev.preventDefault();
            const box = document.getElementById("ei-mt-q");
            if (box) { box.focus(); }
        } else if (ev.key === "ArrowDown" || ev.key === "j") {
            ev.preventDefault();
            this.move(1);
        } else if (ev.key === "ArrowUp" || ev.key === "k") {
            ev.preventDefault();
            this.move(-1);
        }
    }
    move(delta) {
        const items = this.items;
        if (!items.length) { return; }
        const at = items.findIndex((i) => i.id === this.state.selected);
        const next = items[Math.min(Math.max(at + delta, 0), items.length - 1)];
        if (next && next.id !== this.state.selected) {
            this.select(next.id, { keepStep: true });
            const el = document.getElementById("ei-mt-row-" + next.id);
            if (el) { el.focus(); el.scrollIntoView({ block: "nearest" }); }
        }
    }
    onDialogKey(ev) {                               // keep Tab inside the dialog
        if (ev.key !== "Tab") { return; }
        const nodes = [...ev.currentTarget.querySelectorAll("button, textarea, select, input")].filter((n) => !n.disabled);
        if (!nodes.length) { return; }
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); } else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
}

registry.category("actions").add("ei_matching", EiMatching);
