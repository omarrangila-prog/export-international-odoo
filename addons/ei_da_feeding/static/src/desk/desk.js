import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

// The DA feeding desk. Every number shown is worked out on the server (ei.feeding.desk); this file only collects what
// the person types and lays the answer out. Practice never writes anything; real entry writes draft DA lines only.
const MODEL = "ei.feeding.desk";
const OFFSET_METHODS = ["normal_sale", "high_profit_sale", "loss_sale", "sale_at_mill_rate", "purchase_with_cn"];
const LOOKUPS = { customer: "Customer", customer_code: "Customer code", trade_code: "Purchase / sale code", pl_code: "P&L code" };

// today in the person's own time zone (Karachi), not UTC: between midnight and 5 am they differ by a day
const localDay = () => { const n = new Date(), z = (x) => String(x).padStart(2, "0"); return `${n.getFullYear()}-${z(n.getMonth() + 1)}-${z(n.getDate())}`; };
const toNum = (v) => parseFloat(String(v === undefined || v === null ? "" : v).replace(/,/g, ""));
export function fmt(v, digits = 2) {
    const n = toNum(v);
    if (Number.isNaN(n)) { return ""; }
    return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
const blankLine = () => ({
    id: false, contract_line_id: "", coil_no: "", grade: "", weight_kg: "", method: "", basic_rate: "", sale_offset: "",
    sale_typed: false, sale_rate: "", purchase_rate: "", cn_amount: "", cn_text: "", loss_reason: "", rate_note: "",
    customer: null, customer_code: null, trade_code: null, pl_code: null,
});

export class EiDaFeeding extends Component {
    static template = "ei_da_feeding.Desk";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = proxy({
            tab: "practice", lab: null, labInputs: null, open: {}, labBusy: false,
            methods: [], list: null, da: null, line: null, preview: null, previewBusy: false, newDa: null,
            look: { field: null, term: "", rows: [], busy: false }, busy: false, error: "", header: null, docIndex: 0,
            review: false, next: null, newCur: "PKR",
        });
        this.timers = { lab: null, prev: null, look: null };
        this.onKey = (ev) => {
            if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s" && this.state.tab === "real" && this.state.line) {
                ev.preventDefault();
                this.saveLine();
            }
        };
        onWillStart(async () => {
            const ctx = (this.props.action && this.props.action.context) || {};
            const [methods, lab] = await Promise.all([this.orm.call(MODEL, "methods", []), this.orm.call(MODEL, "lab", [{}])]);
            this.state.methods = methods;
            this.setLab(lab);
            if (ctx.da_id) { this.state.tab = "real"; await this.loadList(); await this.openDa(ctx.da_id); }
        });
        onMounted(() => document.addEventListener("keydown", this.onKey));
        onWillUnmount(() => { document.removeEventListener("keydown", this.onKey); Object.values(this.timers).forEach(clearTimeout); });
    }

    // ------------------------------------------------------------------ helpers for the template
    fmt(v, d) { return fmt(v, d); }
    str(v) { return v === undefined || v === null ? "" : String(v); }       // templates have no String()/Number()
    toInt(v) { return parseInt(v, 10) || 0; }
    signed(v) { const n = toNum(v); return Number.isNaN(n) ? "" : (n > 0 ? "+" : n < 0 ? "−" : "") + fmt(Math.abs(n)); }
    isOffset(key) { return OFFSET_METHODS.includes(key); }
    methodOf(key) { return this.state.methods.find((m) => m.key === key) || {}; }
    lookLabel(f) { return LOOKUPS[f]; }
    get mtl() { const kg = toNum(this.state.line && this.state.line.weight_kg); return Number.isNaN(kg) ? "" : (kg / 1000).toFixed(3); }
    get cl() { const l = this.state.line, d = this.state.da; return l && d ? d.contract_lines.find((c) => c.id === Number(l.contract_line_id)) : null; }
    get lineBasis() { const m = this.methodOf(this.state.line && this.state.line.method); return m.basis || ""; }
    get doc() { const a = this.state.da && this.state.da.attachments; return a && a.length ? a[Math.min(this.state.docIndex, a.length - 1)] : null; }
    docUrl(a) { return `/web/content/${a.id}?download=false`; }
    isImage(a) { return /^image\//.test(a.mimetype || ""); }

    async call(method, args) {
        this.state.error = "";
        try { return await this.orm.call(MODEL, method, args); }
        catch (e) {
            this.state.error = (e && e.data && e.data.message) || (e && e.message) || "Something went wrong.";
            throw e;
        }
    }

    // ------------------------------------------------------------------ practice
    setLab(lab) {
        this.state.lab = lab;
        if (!this.state.labInputs) {
            const i = lab.inputs;
            this.state.labInputs = { basic_rate: i.basic_rate, weight_kg: i.weight_kg, cn_amount: i.cn_amount, direct_purchase: i.direct_purchase,
                direct_sale: i.direct_sale, params: { ...i.params }, offsets: { ...i.offsets } };
        }
    }
    labInput(key, ev, group) {
        if (group) { this.state.labInputs[group][key] = ev.target.value; } else { this.state.labInputs[key] = ev.target.value; }
        clearTimeout(this.timers.lab);
        this.timers.lab = setTimeout(() => this.runLab(), 300);
    }
    async runLab() {
        this.state.labBusy = true;
        try { this.state.lab = await this.call("lab", [this.state.labInputs]); } catch { /* shown */ } finally { this.state.labBusy = false; }
    }
    async resetLab() {
        const lab = await this.call("lab", [{}]);
        this.state.labInputs = null;           // set again from the fresh answer in the same tick: the screen never sees it empty
        this.setLab(lab);
    }
    toggle(key) { this.state.open[key] = !this.state.open[key]; }

    // ------------------------------------------------------------------ real entry: the DA
    async setTab(tab) {
        this.state.tab = tab;
        if (tab === "real" && !this.state.list) { await this.loadList(); }
    }
    async loadList() { try { this.state.list = await this.call("da_list", []); } catch { this.state.list = { rows: [], contracts: [] }; } }
    async openDa(id) {
        this.state.line = null; this.state.preview = null; this.state.docIndex = 0; this.state.next = null; this.state.review = false;
        try { this.setDa(await this.call("da_load", [id])); } catch { /* shown */ }
    }
    setDa(da) {
        this.state.da = da;
        this.state.header = { printed_customer: da.printed_customer, order_datetime: da.order_datetime, ship_date: da.ship_date, date: da.date };
        // keep the DA list on the left in step with the DA open on the right (coil count and tons change with every saved coil)
        const row = this.state.list && this.state.list.rows.find((x) => x.id === da.id);
        if (row) { row.coils = da.lines.length; row.mtl = da.total_mtl; }
    }
    startNewDa() {
        this.state.next = null;
        const c = this.contractsForCurrency;
        this.state.newDa = { contract_id: c.length === 1 ? String(c[0].id) : "", name: "", date: localDay(),
            order_datetime: "", ship_date: "", printed_customer: "" };
    }
    async createDa() {
        this.state.busy = true;
        try {
            const id = await this.call("da_create", [this.state.newDa]);
            this.state.newDa = null;
            await this.loadList();
            await this.openDa(id);
        } catch { /* shown */ } finally { this.state.busy = false; }
    }
    async saveHeader() {
        try { this.setDa(await this.call("da_save_header", [this.state.da.id, this.state.header])); this.toast("DA details saved."); } catch { /* shown */ }
    }
    async attach(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) { return; }
        const data = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(file); });
        try { this.setDa(await this.call("attach", [this.state.da.id, file.name, data, file.type])); this.toast("Paper attached."); } catch { /* shown */ }
        ev.target.value = "";
    }
    // Save & Continue: confirmed now when approval is off (the default), or sent to the approver when ticked / switched on
    async submit() {
        if (this.state.line) { this.toast("Save or close the coil you are editing first.", "warning"); return; }
        this.state.busy = true;
        try {
            const r = await this.call("submit", [this.state.da.id, this.state.review]);
            this.setDa(r); this.state.next = r.next; await this.loadList();
            const who = r.approval && r.approval.approver ? ` to ${r.approval.approver}` : "";
            this.toast(r.state === "approved" ? "DA confirmed." + (r.next && !r.next.error ? " Next: the daily order request is ready." : "")
                : (r.approval && r.approval.needs_assignment ? "Submitted. Assignment required: an administrator has been told." : `Submitted for approval${who}.`));
        } catch { /* shown */ } finally { this.state.busy = false; }
    }
    openApproval() {
        const a = this.state.da.approval;
        this.action.doAction({ type: "ir.actions.client", tag: "ei_approvals.center", name: "Approvals", params: { tab: "mine", request_id: a.request_id } });
    }
    openNext() {
        const n = this.state.next;
        if (n && !n.error) { this.action.doAction({ type: "ir.actions.act_window", res_model: n.model, res_id: n.id, views: [[false, "form"]], target: "current" }); }
    }
    get step() {
        const d = this.state.da;
        if (!d) { return 1; }
        if (this.state.line) { return this.state.line.method ? 3 : 2; }
        return d.lines.length ? 4 : 2;
    }
    get contractsForCurrency() {
        return (this.state.list ? this.state.list.contracts : []).filter((c) => c.currency === this.state.newCur);
    }
    setNewCur(cur) { this.state.newCur = cur; if (this.state.newDa) { this.state.newDa.contract_id = ""; } }

    // ------------------------------------------------------------------ real entry: one coil
    newLine() {
        const l = blankLine(), d = this.state.da;
        if (d.contract_lines.length === 1) {
            const cl = d.contract_lines[0];
            l.contract_line_id = String(cl.id); l.basic_rate = cl.basic_rate ? String(cl.basic_rate) : "";
            if (cl.target_customer) { l.customer = cl.target_customer; }
        }
        const last = d.lines[d.lines.length - 1];
        if (last) {            // the next coil of the same DA usually goes to the same customer with the same codes
            l.customer = last.customer; l.customer_code = last.customer_code; l.trade_code = last.trade_code; l.pl_code = last.pl_code;
            l.method = last.method; l.basic_rate = last.basic_rate ? String(last.basic_rate) : l.basic_rate;
        }
        this.state.line = l; this.state.preview = null;
        this.focusSoon("#ei-fd-coil");
    }
    // a new coil with the repeatable details of an existing one; the coil number, weight and credit note are left empty
    duplicateLine(row) {
        const l = blankLine();
        Object.assign(l, { contract_line_id: String(row.contract_line_id), grade: row.grade, method: row.method,
            basic_rate: row.basic_rate ? String(row.basic_rate) : "", sale_offset: String(row.sale_offset || 0), sale_typed: row.sale_typed,
            sale_rate: row.sale_typed ? String(row.sale_rate || "") : "", purchase_rate: row.method === "direct_no_commission" ? String(row.purchase_rate || "") : "",
            customer: row.customer, customer_code: row.customer_code, trade_code: row.trade_code, pl_code: row.pl_code, rate_note: row.rate_note });
        this.state.line = l; this.state.preview = null;
        this.focusSoon("#ei-fd-coil");
        this.refresh();
    }
    editLine(row) {
        this.state.line = { ...blankLine(), ...row, contract_line_id: String(row.contract_line_id), weight_kg: String(row.weight_kg || ""),
            basic_rate: row.basic_rate ? String(row.basic_rate) : "", sale_offset: String(row.sale_offset || 0),
            cn_amount: row.cn_amount ? String(row.cn_amount) : "", sale_rate: String(row.sale_rate || ""), purchase_rate: String(row.purchase_rate || "") };
        this.refresh();
    }
    closeLine() { this.state.line = null; this.state.preview = null; }
    setLine(key, ev) {
        const v = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        this.state.line[key] = v;
        if (key === "contract_line_id" && this.cl && !this.state.line.basic_rate) { this.state.line.basic_rate = String(this.cl.basic_rate || ""); }
        this.refresh();
    }
    pickMethod(key) {
        const l = this.state.line;
        l.method = key;
        if (key === "purchase_with_cn" || key === "sale_at_mill_rate") { l.sale_offset = "0"; }
        this.refresh();
    }
    payload() {
        const l = this.state.line;
        return { contract_line_id: l.contract_line_id, coil_no: l.coil_no, grade: l.grade, weight_kg: l.weight_kg, method: l.method,
            basic_rate: l.basic_rate, sale_offset: l.sale_offset, sale_typed: l.sale_typed, sale_rate: l.sale_rate, purchase_rate: l.purchase_rate,
            cn_amount: l.cn_amount, cn_text: l.cn_text, loss_reason: l.loss_reason, rate_note: l.rate_note,
            customer_id: l.customer && l.customer.id, customer_code_id: l.customer_code && l.customer_code.id,
            trade_code_id: l.trade_code && l.trade_code.id, pl_code_id: l.pl_code && l.pl_code.id };
    }
    refresh() {
        clearTimeout(this.timers.prev);
        this.timers.prev = setTimeout(async () => {
            const l = this.state.line;
            if (!l || !l.method || !l.contract_line_id || !l.weight_kg) { this.state.preview = null; return; }
            this.state.previewBusy = true;
            try { this.state.preview = await this.orm.call(MODEL, "preview", [this.state.da.id, this.payload()]); }
            catch (e) { this.state.preview = { ok: false, error: (e.data && e.data.message) || "Could not work it out." }; }
            finally { this.state.previewBusy = false; }
        }, 250);
    }
    async saveLine(addNext = false) {
        if (!this.state.line || this.state.busy) { return; }
        this.state.busy = true;
        try {
            const r = await this.call("save_line", [this.state.da.id, this.state.line.id || false, this.payload()]);
            this.setDa(r.da);
            const saved = r.da.lines.find((x) => x.id === r.line_id);
            this.toast(saved && saved.code_issue ? "Coil saved as a draft. Check the code warning before sending it." : "Coil saved as a draft.",
                saved && saved.code_issue ? "warning" : "success");
            if (addNext) { this.newLine(); } else { this.closeLine(); }
        } catch { /* shown */ } finally { this.state.busy = false; }
    }
    async deleteLine(row) {
        if (!window.confirm(`Remove coil ${row.coil_no || ""} from this draft?`)) { return; }
        try { this.setDa(await this.call("delete_line", [this.state.da.id, row.id])); this.closeLine(); } catch { /* shown */ }
    }

    // ------------------------------------------------------------------ look-ups (customer and the three code lists)
    openLook(field) {
        this.state.look = { field, term: "", rows: [], busy: false };
        this.runLook();
        this.focusSoon("#ei-fd-look");
    }
    lookInput(ev) {
        this.state.look.term = ev.target.value;
        clearTimeout(this.timers.look);
        this.timers.look = setTimeout(() => this.runLook(), 200);
    }
    async runLook() {
        const s = this.state.look, kind = { customer_code: "customer", trade_code: "trade", pl_code: "pl" }[s.field];
        s.busy = true;
        try {
            s.rows = s.field === "customer" ? await this.orm.call(MODEL, "partner_search", [s.term])
                : await this.orm.call(MODEL, "code_search", [kind, s.term, this.state.da.printed_customer || ""]);
        } finally { s.busy = false; }
    }
    choose(row) {
        const f = this.state.look.field;
        this.state.line[f] = f === "customer" ? { id: row.id, name: row.name } : row;
        this.state.look = { field: null, term: "", rows: [], busy: false };
        this.refresh();
    }
    clearPick(f) { this.state.line[f] = null; this.refresh(); }
    lookKey(ev) {
        if (ev.key === "Escape") { this.state.look.field = null; }
        if (ev.key === "Enter" && this.state.look.rows.length) { ev.preventDefault(); this.choose(this.state.look.rows[0]); }
    }

    focusSoon(sel) { setTimeout(() => { const el = document.querySelector(sel); if (el) { el.focus(); } }, 60); }
    toast(message, type = "success") { this.notification.add(message, { type }); }
}

registry.category("actions").add("ei_da_feeding", EiDaFeeding);
