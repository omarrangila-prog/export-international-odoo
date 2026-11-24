import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

// The DA feeding desk. Every number shown is worked out on the server (ei.feeding.desk); this file only collects what
// the person types and lays the answer out. Practice never writes anything; real entry writes draft DA lines only.
const MODEL = "ei.feeding.desk";
const OFFSET_METHODS = ["normal_sale", "high_profit_sale", "loss_sale", "sale_at_mill_rate", "purchase_with_cn"];
const LOOKUPS = { customer: "Sold (OUT)", customer_code: "Sales code", trade_code: "Purchase code", pl_code: "P&L code" };
const LOOK_WORDS = { customer: "the customer", customer_code: "sales code", trade_code: "purchase code", pl_code: "P&L code" };

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
    customer: null, customer_code: null, trade_code: null, pl_code: null, thickness: "", width: "",
    qty: "", unit: "MTL", small_ok: false,
});
// the quantity as typed, in its unit, turned into kg without floating-point dust (4.574 MTL -> "4574")
const kgOf = (qty, unit) => {
    const n = toNum(qty);
    if (Number.isNaN(n)) { return ""; }
    const kg = unit === "MTL" ? n * 1000 : n;
    return String(parseFloat(kg.toFixed(3)));
};
const SMALL_KG = 100;
// the two choices on the screen (client, 23 Nov 2026); the server records what a commission coil works out to
const PICKS = [
    { key: "commission", label: "Commission based", basis: "commission", ready: true, why: "Basic rate and mill rate +/−. Credit note optional: leave it empty if there is none." },
    { key: "direct_no_commission", label: "Direct (no commission)", basis: "direct", ready: true, why: "Type the purchase rate and the sale rate." },
];
const pickOf = (method) => (!method ? "" : method === "direct_no_commission" ? "direct_no_commission" : "commission");
const blankRate = () => ({ method: "", basic_rate: "", sale_offset: "", purchase_rate: "", sale_rate: "" });
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// MTL to whole grams as an integer: totals of many coils without floating-point dust
const grams = (mtl) => { const n = toNum(mtl); return Number.isNaN(n) ? 0 : Math.round(n * 1000); };
let bulkKey = 0;
// fields that move on with Enter (FoxPro style); lookups, buttons and text areas keep their own Enter
const NEXT_SEL = ["input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([readonly]):not([disabled])", "select:not([disabled])",
    ".ei-fd-pick > button.ei-fd-btn", ".ei-fd-mpick:not([disabled])", ".ei-fd-savebtn"].join(", ");

export class EiDaFeeding extends Component {
    static template = "ei_da_feeding.Desk";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = proxy({
            tab: "real", lab: null, labInputs: null, open: {}, labBusy: false,
            methods: [], list: null, da: null, line: null, preview: null, previewBusy: false, newDa: null,
            look: { field: null, term: "", rows: [], busy: false }, busy: false, error: "", header: null, docIndex: 0,
            review: false, next: null, partyLook: { term: "", rows: [] }, itemLook: null, dupes: null,
            pl: { supplier: { term: "", rows: [] }, pin: { term: "", rows: [] } },
            docsOpen: false, quotaUi: null, quotaMore: false, sel: {}, rate: blankRate(), ratePlan: null, bulk: null,
            missing: [], itemMsg: "", codeCheck: null, soldChange: null,
        });
        this.lookSeq = 0;
        this.timers = { lab: null, prev: null, look: null, party: null, item: null };
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
            await this.loadList();
            if (ctx.da_id) { await this.openDa(ctx.da_id); }
            else if (ctx.ei_new && this.state.list && this.state.list.can_create) { this.startNewDa(); }
        });
        onMounted(() => document.addEventListener("keydown", this.onKey));
        onWillUnmount(() => { document.removeEventListener("keydown", this.onKey); Object.values(this.timers).forEach(clearTimeout); });
    }

    // ------------------------------------------------------------------ Enter moves to the next box (like FoxPro)
    onFieldKey(ev) {
        // arrow keys move through a list of matches; Enter on a row picks it (the button's own click)
        if ((ev.key === "ArrowDown" || ev.key === "ArrowUp") && ev.target && ev.target.closest && ev.target.closest(".ei-fd-lookrows")) {
            const li = ev.target.closest("li"), to = ev.key === "ArrowDown" ? li && li.nextElementSibling : li && li.previousElementSibling;
            const b = to && to.querySelector("button");
            if (b) { ev.preventDefault(); b.focus(); b.scrollIntoView({ block: "nearest" }); }
            return;
        }
        // a letter typed on a "Choose … code" button, or while its search box is still opening, goes into that search box
        const printable = ev.key && ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey;
        if (printable && !ev.defaultPrevented && ev.target && ev.target.id !== "ei-fd-look") {
            const pick = ev.target.closest && ev.target.closest(".ei-fd-pick");
            const f = this.state.look.field || (pick && ev.target.matches(".ei-fd-pick > button.ei-fd-btn") ? pick.dataset.f : null);
            if (f && (this.state.look.field === f || !this.state.look.field)) {
                ev.preventDefault();
                if (this.state.look.field !== f) { this.state.look = { field: f, term: "", rows: [], busy: false }; }
                this.state.look.term += ev.key;
                clearTimeout(this.timers.look);
                this.timers.look = setTimeout(() => { this.timers.look = null; this.runLook(); }, 200);
                this.focusSoon("#ei-fd-look");
                return;
            }
        }
        if (ev.key !== "Enter" || ev.defaultPrevented || ev.isComposing || ev.shiftKey || ev.ctrlKey || ev.altKey || ev.metaKey) { return; }
        const el = ev.target;
        if (!el || el.tagName === "TEXTAREA" || el.tagName === "BUTTON" || el.tagName === "A") { return; }   // their own Enter
        if (!el.matches("input, select") || el.type === "checkbox" || el.type === "file") { return; }
        ev.preventDefault();
        if (el.id === "ei-fd-daname" || el.closest(".ei-fd-newhead")) { this.focusNext(el); return; }
        if (el.classList.contains("ei-fd-bcount")) { this.addRows(); return; }                          // the number of rows: Enter adds them
        if (el.classList.contains("ei-fd-bqty") && el.closest("tr") && !el.closest("tr").nextElementSibling) {   // last weight: stop on Save all
            const b = document.querySelector(".ei-fd-bsave"); if (b) { b.focus(); b.scrollIntoView({ block: "center" }); } return;
        }
        if (el.classList.contains("ei-fd-lastrate")) { const b = document.querySelector(".ei-fd-savebtn"); if (b) { b.focus(); b.scrollIntoView({ block: "center" }); } return; }
        this.focusNext(el);
    }
    focusNext(from) {
        const root = document.querySelector(".ei-fd-real") || document;
        const all = [...root.querySelectorAll(NEXT_SEL)].filter((x) => x.offsetParent !== null);
        const i = all.indexOf(from.closest ? (from.closest(NEXT_SEL) || from) : from);
        // a box that is not itself in the list (a "Change" link, a picked name): the first box after it on the screen
        const next = i >= 0 ? all[i + 1] : all.find((x) => from.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (next) { next.focus(); next.scrollIntoView({ block: "center" }); }
    }
    advanceSoon(sel) { setTimeout(() => { const el = document.querySelector(sel); if (el) { this.focusNext(el); } }, 80); }
    noMatch(term) { this.state.error = `No match for “${term}”. Pick a name from the list; a new one is added only with its Add button.`; }

    // ------------------------------------------------------------------ helpers for the template
    fmt(v, d) { return fmt(v, d); }
    toNum(v) { return toNum(v); }
    dmy(day) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : ""; }
    str(v) { return v === undefined || v === null ? "" : String(v); }       // templates have no String()/Number()
    toInt(v) { return parseInt(v, 10) || 0; }
    signed(v) { const n = toNum(v); return Number.isNaN(n) ? "" : (n > 0 ? "+" : n < 0 ? "−" : "") + fmt(Math.abs(n)); }
    isOffset(key) { return OFFSET_METHODS.includes(key); }
    methodOf(key) { return PICKS.find((m) => m.key === key) || this.state.methods.find((m) => m.key === key) || {}; }
    get picks() { return PICKS; }
    noFormula(m) { return m.key === "commission" && !!this.cl && !this.cl.formula && !!(this.state.da && this.state.da.is_feeding); }
    lookLabel(f) { return LOOKUPS[f]; }
    lookWord(f) { return LOOK_WORDS[f]; }
    get mtl() { const kg = toNum(this.state.line && this.state.line.weight_kg); return Number.isNaN(kg) ? "" : String(parseFloat((kg / 1000).toFixed(6))); }
    get kgText() { const kg = toNum(this.state.line && this.state.line.weight_kg); return Number.isNaN(kg) ? "" : fmt(kg, kg % 1 ? 3 : 0); }
    // a coil lighter than 100 kg is nearly always tons typed as kg: say so, offer MTL, and ask for a tick before saving
    get smallWeight() { const l = this.state.line, kg = toNum(l && l.weight_kg); return !!l && !Number.isNaN(kg) && kg > 0 && kg < SMALL_KG; }
    get cl() { const l = this.state.line, d = this.state.da; return l && d ? d.contract_lines.find((c) => c.id === Number(l.contract_line_id)) : null; }
    get lineBasis() { const m = this.methodOf(this.state.line && this.state.line.method); return m.basis || ""; }
    // what is missing for this coil, by field (shown beside the box and listed above Save)
    get fieldErr() {
        const e = {};
        for (const m of this.state.missing) { e[m.key] = m.msg; }
        if (!e.item && this.state.itemMsg) { e.item = this.state.itemMsg; }
        return e;
    }
    lineProblems() {
        const l = this.state.line, out = [], basis = this.lineBasis, term = this.state.itemLook && this.state.itemLook.term.trim();
        if (!l.contract_line_id) {
            out.push({ key: "item", msg: term ? `Item: “${term}” is typed but not chosen. Pick it from the list under the box, or press “+ Add new item”.`
                : "Item: choose the item (material) of this coil." });
        }
        if (!(l.coil_no || "").trim()) { out.push({ key: "coil", msg: "Coil No: type the coil number as printed." }); }
        if (!l.weight_kg || toNum(l.weight_kg) <= 0) { out.push({ key: "weight", msg: "Weight: type the weight (MTL or kg)." }); }
        if (!l.method) { out.push({ key: "method", msg: "Method: choose Commission based or Direct." }); }
        else if (basis === "direct" && (!l.purchase_rate || !l.sale_rate)) { out.push({ key: "rate", msg: "Rates: type the purchase rate and the sale rate." }); }
        else if (basis !== "direct" && !l.basic_rate) { out.push({ key: "rate", msg: "Rates: type the basic rate." }); }
        const p = this.state.preview;
        if (p && p.ok && p.result === "loss" && !(l.loss_reason || "").trim()) {
            out.push({ key: "loss", msg: "Sold below cost: write why in the box under the calculation (an approver checks it)." });
        }
        return out;
    }
    fixField(m) {
        const sel = { item: "#ei-fd-item", coil: "#ei-fd-coil", weight: "#ei-fd-qty", method: ".ei-fd-mpick", rate: ".ei-fd-editor .ei-fd-rate input", loss: ".ei-fd-lossbox input" }[m.key];
        if (m.key === "item" && !document.querySelector("#ei-fd-item")) { this.openItems(); }
        setTimeout(() => { const el = document.querySelector(sel); if (el) { el.scrollIntoView({ block: "center" }); el.focus(); } }, 60);
    }
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
        this.state.newDa = null; this.state.dupes = null;         // a recent entry clicked while a new form is open: show that entry
        this.state.line = null; this.state.preview = null; this.state.docIndex = 0; this.state.next = null; this.state.review = false;
        this.state.docsOpen = false; this.state.quotaUi = null; this.state.sel = {}; this.state.ratePlan = null; this.state.bulk = null;
        try { this.setDa(await this.call("da_load", [id])); } catch { /* shown */ }
    }
    setDa(da) {
        this.state.da = da;
        const ids = new Set(da.lines.map((l) => l.id));                     // a removed coil is no longer selected
        for (const k of Object.keys(this.state.sel)) { if (!ids.has(Number(k))) { delete this.state.sel[k]; } }
        this.state.header = { printed_customer: da.printed_customer, order_datetime: da.order_datetime, ship_date: da.ship_date, date: da.date };
        // keep the DA list on the left in step with the DA open on the right (coil count and tons change with every saved coil)
        const row = this.state.list && this.state.list.rows.find((x) => x.id === da.id);
        if (row) { row.coils = da.lines.length; row.mtl = da.total_mtl; }
    }
    startNewDa() {
        this.state.next = null;
        const li = this.state.list || {}, one = (a) => (a && a.length === 1 ? String(a[0].id) : "");
        // no contract first: the three parties. A signed contract can still be chosen under "More details".
        const nm = (a) => (a && a.length === 1 ? a[0].name : "");
        this.state.newDa = { contract_id: "", supplier_id: one(li.suppliers), supplier_name: nm(li.suppliers),
            purchase_in_id: one(li.purchase_ins), purchase_in_name: nm(li.purchase_ins), sold_out_id: "", sold_out_name: "",
            name: "", date: localDay(), order_datetime: "", ship_date: "", printed_customer: "" };
        this.state.partyLook = { term: "", rows: [] }; this.state.dupes = null; this.state.da = null; this.state.line = null;
        this.state.pl = { supplier: { term: "", rows: [] }, pin: { term: "", rows: [] } };
        this.focusSoon("#ei-fd-daname");
    }
    // The three parties: type a name or an old code, pick it (Enter takes the first row). Everything already in the system is
    // offered; a name that is not there yet is added as new. No other question.
    plInput(role, ev) {
        const term = ev.target.value, box = this.state.pl[role];
        box.term = term;
        clearTimeout(this.timers["pl_" + role]);
        this.timers["pl_" + role] = setTimeout(async () => {
            const rows = term.trim() ? await this.orm.call(MODEL, "party_search", [role === "pin" ? "pin" : "supplier", term]) : [];
            if (box.term === term) { box.rows = rows; }
        }, 200);
    }
    async plPick(role, row) {
        const p = await this.call("party_take", [role === "pin" ? "pin" : "supplier", row]);
        if (!p) { return; }
        const d = this.state.newDa;
        if (role === "pin") { d.purchase_in_id = String(p.id); d.purchase_in_name = p.name; }
        else { d.supplier_id = String(p.id); d.supplier_name = p.name; }
        this.state.pl[role] = { term: "", rows: [] }; this.state.error = "";
        this.advanceSoon(role === "supplier" ? ".ei-fd-supplier" : ".ei-fd-pin");     // the next box that is there (one may be filled already)
    }
    async plKey(role, ev) {
        const box = this.state.pl[role];
        if (ev.key === "Escape") { box.rows = []; return; }
        if (ev.key === "ArrowDown") { const o = ev.target.parentElement.querySelector(".ei-fd-lookrows button"); if (o) { ev.preventDefault(); o.focus(); } return; }
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        const term = ev.target.value;
        if (!term.trim()) { return; }
        clearTimeout(this.timers["pl_" + role]);
        const rows = await this.orm.call(MODEL, "party_search", [role === "pin" ? "pin" : "supplier", term]);
        const hit = rows.find((r) => r.kind !== "new");      // Enter never creates a party from a part of a name
        if (hit) { this.plPick(role, hit); } else { box.rows = rows; this.noMatch(term); }
    }
    plClear(role) {
        const d = this.state.newDa;
        if (role === "pin") { d.purchase_in_id = ""; d.purchase_in_name = ""; } else { d.supplier_id = ""; d.supplier_name = ""; }
        this.focusSoon(role === "pin" ? "#ei-fd-pin" : "#ei-fd-supplier");
    }
    // Sold (OUT) on the DA: type a name or a code; it is offered on every new coil. Empty = not sold yet.
    async partyLookInput(ev) {
        const term = ev.target.value;
        this.state.partyLook.term = term;
        clearTimeout(this.timers.party);
        this.timers.party = setTimeout(async () => {
            const rows = term.trim() ? await this.orm.call(MODEL, "party_search", ["customer", term]) : [];
            if (this.state.partyLook.term === term) { this.state.partyLook.rows = rows; }
        }, 200);
    }
    async pickSoldOut(row) {
        const p = await this.call("party_take", ["customer", row]);
        if (!p) { return; }
        if (this.state.newDa) { this.state.newDa.sold_out_id = String(p.id); this.state.newDa.sold_out_name = p.name; }
        this.state.partyLook = { term: "", rows: [] }; this.state.error = "";
        this.focusSoon("#ei-fd-gocoil");                    // on to the coil, on the same screen
    }
    async soldKey(ev) {
        if (ev.key === "Escape") { this.state.partyLook.rows = []; return; }
        if (ev.key === "ArrowDown") { const o = ev.target.parentElement.querySelector(".ei-fd-lookrows button"); if (o) { ev.preventDefault(); o.focus(); } return; }
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        const term = ev.target.value;
        if (!term.trim()) { this.ensureDa(); return; }             // not sold yet: straight on to the coil
        clearTimeout(this.timers.party);
        const rows = await this.orm.call(MODEL, "party_search", ["customer", term]);
        const hit = rows.find((r) => r.kind !== "new");
        if (hit) { await this.pickSoldOut(hit); } else { this.state.partyLook.rows = rows; this.noMatch(term); }
    }
    clearSoldOut() { this.state.newDa.sold_out_id = ""; this.state.newDa.sold_out_name = ""; }
    // the item of a coil on a feeding-account DA: any material; its line in the account is found or opened
    async itemLookInput(ev) {
        const term = ev.target.value;
        if (this.state.line && this.state.line.contract_line_id) { this.state.line.contract_line_id = ""; this.state.preview = null; }   // a new text: the old item no longer counts
        this.state.itemMsg = "";
        this.state.itemLook = { term, rows: this.state.itemLook ? this.state.itemLook.rows : [] };
        clearTimeout(this.timers.item);
        this.timers.item = setTimeout(async () => {
            const rows = await this.orm.call(MODEL, "product_search", [term]);
            if (this.state.itemLook && this.state.itemLook.term === term) { this.state.itemLook.rows = rows; }   // a slower, older answer never wins
        }, 200);
    }
    async itemKey(ev) {
        if (ev.key === "ArrowDown") { const o = ev.target.parentElement.querySelector(".ei-fd-lookrows button"); if (o) { ev.preventDefault(); o.focus(); } return; }
        if (ev.key !== "Enter" || !this.state.itemLook) { return; }
        ev.preventDefault();
        // Enter takes the first row for exactly what is typed now, never a row of an older search still on screen
        const term = ev.target.value;
        clearTimeout(this.timers.item);
        const rows = term.trim() ? await this.orm.call(MODEL, "product_search", [term]) : this.state.itemLook.rows;
        const hit = rows.find((r) => r.kind !== "new" && r.name.trim().toLowerCase() === term.trim().toLowerCase()) || rows.find((r) => r.kind !== "new" && !r.similar);
        if (hit) { this.pickItem(hit); } else {
            this.state.itemLook.rows = rows;
            this.state.itemMsg = `“${term}” is not in the item list yet. Pick a similar one below, or press “+ Add new item” to add it.`;
        }
    }
    async openItems() {
        // show the list at once, and never wipe what the person already typed while it loads
        if (!this.state.itemLook) { this.state.itemLook = { term: "", rows: [] }; }
        const rows = await this.orm.call(MODEL, "product_search", [""]);
        if (this.state.itemLook && !this.state.itemLook.term) { this.state.itemLook.rows = rows; }
        this.focusSoon("#ei-fd-item");
    }
    async pickItem(row) {
        if (row.kind === "new") { row = { id: await this.call("product_take", [row.name]), name: row.name }; }
        try {
            const r = await this.call("ensure_line", [this.state.da.id, row.id]);
            this.setDa(r.da);
            this.state.line.contract_line_id = String(r.contract_line_id);
            // the size printed in the item's name decides thickness and width: a new item never keeps the previous item's size
            if (r.dims) { this.state.line.thickness = r.dims.thickness; this.state.line.width = r.dims.width; }
            this.state.itemLook = null; this.state.itemMsg = ""; this.state.error = "";
            this.state.missing = this.state.missing.filter((m) => m.key !== "item");
            this.refresh();
            this.focusSoon("#ei-fd-coil");
        } catch { /* shown */ }
    }
    // No "Create draft DA" step: when the DA number and the parties are there, the coil boxes open on the same screen.
    // The draft is kept behind the scenes so nothing typed is lost. The same DA number never becomes a second copy.
    async ensureDa(force = false) {
        const n = this.state.newDa;
        if (!n || this.state.busy) { return; }
        if (!n.name.trim()) { this.state.error = "Type the DA number first."; this.focusSoon("#ei-fd-daname"); return; }
        if (!n.supplier_id && !n.contract_id) { this.state.error = "Choose the Supplier first."; this.focusSoon("#ei-fd-supplier"); return; }
        if (!n.purchase_in_id && !n.contract_id) { this.state.error = "Choose Purchased By (Purchase IN) first."; this.focusSoon("#ei-fd-pin"); return; }
        this.state.busy = true; this.state.error = "";
        try {
            if (!force) {
                const found = await this.call("da_find", [n.name]);
                if (found.length) { this.state.dupes = found; return; }
                const similar = await this.call("da_similar", [n.name, n.supplier_id || false]);       // 40038934NV / 40038934NOV
                if (similar.length) { this.state.dupes = similar; return; }
            }
            const id = await this.call("da_create", [n]);
            this.state.newDa = null; this.state.dupes = null;
            await this.loadList();
            await this.openDa(id);
            this.newLine();
            this.focusSoon("#ei-fd-item");
        } catch { /* shown */ } finally { this.state.busy = false; }
    }
    async openExisting(row, addCoil) {
        this.state.newDa = null; this.state.dupes = null;
        await this.openDa(row.id);
        if (addCoil && this.state.da && this.state.da.editable) { this.newLine(); this.focusSoon("#ei-fd-item"); }
    }
    async saveHeader() {
        try { this.setDa(await this.call("da_save_header", [this.state.da.id, this.state.header])); } catch { /* shown */ }
    }
    setHeader(key, ev) {                 // saved by itself a moment after typing: no separate Save button for the printed details
        this.state.header[key] = ev.target.value;
        clearTimeout(this.timers.head);
        this.timers.head = setTimeout(() => this.saveHeader(), 700);
    }
    // Attach DA (Optional): never needed to save or submit; replace and remove are for a draft, by whoever may do it
    async attach(ev, replaceId = false) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) { return; }
        const data = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(file); });
        try {
            this.setDa(await this.call("attach", [this.state.da.id, file.name, data, file.type, replaceId]));
            this.state.docIndex = 0;
            this.toast(replaceId ? "Paper replaced." : "Paper attached.");
        } catch { /* shown */ }
        ev.target.value = "";
    }
    async detach(a) {
        if (!window.confirm(`Remove ${a.name} from DA ${this.state.da.name}? The removal is written on the DA.`)) { return; }
        try { this.setDa(await this.call("detach", [this.state.da.id, a.id])); this.state.docIndex = 0; this.toast("Paper removed."); } catch { /* shown */ }
    }

    // ------------------------------------------------------------------ contract quantity (500 MTL: 425 entered, 75 remaining)
    get quotaPct() {
        const q = this.state.da && this.state.da.quota, t = q ? grams(q.total) : 0;
        return t ? Math.max(0, Math.min(100, Math.round((grams(q.entered) / t) * 100))) : 0;
    }
    quotaStart(mode) {
        const d = this.state.da, q = d.quota, m = /^(\d{4})-(\d{2})/.exec(d.date || "");
        this.state.quotaUi = { mode, name: m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : "", total: mode === "adjust" && q ? String(toNum(q.total)) : "", reason: "" };
        if (mode === "new") { this.focusSoon("#ei-fd-qnewtotal"); }
    }
    async quotaLink(id) {
        try { this.setDa(await this.call("quota_link", [this.state.da.id, id || false])); this.state.quotaUi = null; } catch { /* shown */ }
    }
    async quotaSaveNew() {
        const u = this.state.quotaUi;
        this.state.busy = true;
        try { this.setDa(await this.call("quota_create", [this.state.da.id, u.name, u.total])); this.state.quotaUi = null; this.toast(`Contract ${u.name}: ${fmt(u.total, 3)} MTL.`); }
        catch { /* shown */ } finally { this.state.busy = false; }
    }
    async quotaSaveAdjust() {
        const u = this.state.quotaUi, q = this.state.da.quota;
        this.state.busy = true;
        try { this.setDa(await this.call("quota_adjust", [this.state.da.id, q.id, u.total, u.reason])); this.state.quotaUi = null; this.toast("Total changed; the reason is kept on the contract."); }
        catch { /* shown */ } finally { this.state.busy = false; }
    }
    // the coil being typed would go past the contract: say so before Save (the server refuses it anyway)
    get overQuota() {
        const d = this.state.da, l = this.state.line, q = d && d.quota;
        if (!q || !l || !l.weight_kg) { return null; }
        const was = l.id ? grams((d.lines.find((x) => x.id === l.id) || {}).mtl) : 0;
        const room = grams(q.remaining) + was, now = Math.round(toNum(l.weight_kg));
        return now > room ? { room: room / 1000, mtl: now / 1000 } : null;
    }

    // ------------------------------------------------------------------ Apply Rate to Selected
    get selCount() { return Object.values(this.state.sel).filter(Boolean).length; }
    get selectedIds() { return Object.keys(this.state.sel).filter((k) => this.state.sel[k]).map(Number); }
    get selBasis() {
        const d = this.state.da, ids = new Set(this.selectedIds), b = { formula: false, direct: false };
        const forced = this.state.rate.method && this.methodOf(this.state.rate.method).basis;
        for (const l of d ? d.lines : []) {
            if (!ids.has(l.id)) { continue; }
            const basis = forced || this.methodOf(l.method).basis;
            if (basis === "direct") { b.direct = true; } else { b.formula = true; }
        }
        return b;
    }
    toggleSel(id, on) { this.state.sel[id] = on; this.state.ratePlan = null; }
    selAll(on) {
        const sel = {};
        if (on) { for (const l of this.state.da.lines) { sel[l.id] = true; } }
        this.state.sel = sel; this.state.ratePlan = null;
    }
    setRate(k, ev) { this.state.rate[k] = ev.target.value; this.state.ratePlan = null; }
    copyPrevRate() {
        const d = this.state.da, last = d.lines[d.lines.length - 1];
        if (!last) { return; }
        Object.assign(this.state.rate, { basic_rate: last.basic_rate ? String(last.basic_rate) : "", sale_offset: String(last.sale_offset || 0),
            purchase_rate: String(last.purchase_rate || ""), sale_rate: String(last.sale_rate || "") });
        if (this.methodOf(last.method).basis !== "direct") { this.state.rate.purchase_rate = ""; this.state.rate.sale_rate = last.sale_typed ? String(last.sale_rate) : ""; }
        else { this.state.rate.basic_rate = ""; this.state.rate.sale_offset = ""; }
        this.state.ratePlan = null;
    }
    async previewRates(recalc = false) {
        const rates = recalc ? {} : { ...this.state.rate };
        if (!recalc && !Object.values(rates).some((v) => v !== "")) { this.state.error = "Type the rate to apply first."; return; }
        this.state.busy = true;
        try { this.state.ratePlan = { ...(await this.call("apply_rates", [this.state.da.id, this.selectedIds, rates, false])), rates }; }
        catch { /* shown */ } finally { this.state.busy = false; }
    }
    async applyRates() {
        const p = this.state.ratePlan;
        this.state.busy = true;
        try {
            const r = await this.call("apply_rates", [this.state.da.id, p.rows.map((x) => x.id), p.rates, true]);
            this.setDa(r.da); this.state.ratePlan = null; this.state.rate = blankRate(); this.state.sel = {};
            this.toast(`Rate applied to ${r.count} coil(s).`);
        } catch { /* shown */ } finally { this.state.busy = false; }
    }

    // ------------------------------------------------------------------ Add Multiple Coils
    startBulk() {
        const d = this.state.da, last = d.lines[d.lines.length - 1];
        if (!last) { return; }
        const basis = this.methodOf(last.method).basis, codes = [last.customer_code, last.trade_code, last.pl_code].filter(Boolean).map((c) => c.code);
        this.state.line = null; this.state.ratePlan = null;
        this.state.bulk = {
            count: 20, rows: [], unit: "MTL", basis, from: last.coil_no, cn: basis !== "direct", cnOn: false, sameCn: false, cnAmount: "", cnText: "",
            label: [last.product, last.method_label, last.customer && last.customer.name, codes.join(" / ")].filter(Boolean).join(" · "),
            shared: { contract_line_id: last.contract_line_id, grade: last.grade, thickness: last.thickness, width: last.width, method: pickOf(last.method),
                basic_rate: last.basic_rate ? String(last.basic_rate) : "", sale_offset: String(last.sale_offset || 0), sale_typed: last.sale_typed,
                sale_rate: String(last.sale_rate || ""), purchase_rate: String(last.purchase_rate || ""), loss_reason: last.loss_reason, rate_note: last.rate_note,
                customer_id: last.customer && last.customer.id, customer_code_id: last.customer_code && last.customer_code.id,
                trade_code_id: last.trade_code && last.trade_code.id, pl_code_id: last.pl_code && last.pl_code.id },
        };
        this.focusSoon(".ei-fd-bcount");
    }
    addRows() {
        const b = this.state.bulk, n = Math.min(200, Math.max(1, this.toInt(b.count)));
        for (let i = 0; i < n; i++) { b.rows.push({ key: ++bulkKey, coil_no: "", qty: "", cn_amount: "", cn_text: "" }); }
        this.focusSoon(`.ei-fd-btable tbody tr:nth-child(${b.rows.length - n + 1}) .ei-fd-bcoil`);
    }
    removeBulkRow(i) { this.state.bulk.rows.splice(i, 1); }
    // two columns copied from Excel (coil number, weight) fill the rows from this one down; one column fills that column
    bulkPaste(ev, i, field) {
        const text = (ev.clipboardData && ev.clipboardData.getData("text/plain")) || "";
        const lines = text.replace(/\r/g, "").split("\n").filter((x) => x.trim() !== "");
        if (lines.length < 2 && !text.includes("\t")) { return; }                   // one value: the browser pastes it
        ev.preventDefault();
        const rows = this.state.bulk.rows;
        lines.forEach((ln, k) => {
            const r = rows[i + k];
            if (!r) { return; }
            const cols = ln.split("\t").map((x) => x.trim());
            if (field === "coil_no") { r.coil_no = cols[0]; if (cols.length > 1) { r.qty = cols[1].replace(/,/g, ""); } }
            else { r.qty = cols[0].replace(/,/g, ""); }
        });
        const left = lines.length - (rows.length - i);
        if (left > 0) { this.toast(`${left} pasted line(s) had no row: add rows and paste them again.`, "warning"); }
    }
    get bulkTotals() {
        const b = this.state.bulk, d = this.state.da;
        let g = 0, filled = 0;
        for (const r of b ? b.rows : []) {
            if (r.coil_no.trim() || r.qty !== "") { filled++; }
            const kg = toNum(kgOf(r.qty, b.unit));
            if (!Number.isNaN(kg)) { g += Math.round(kg); }
        }
        const q = d && d.quota, entered = q ? grams(q.entered) + g : 0;
        return { filled, mtl: g / 1000, entered: entered / 1000, after: q ? (grams(q.total) - entered) / 1000 : 0 };
    }
    async saveBulk() {
        const b = this.state.bulk;
        if (this.state.busy) { return; }
        if (b.rows.some((r) => (r.coil_no.trim() === "") !== (r.qty === ""))) { this.state.error = "Every row needs both its coil number and its weight (or remove the row)."; return; }
        const rows = b.rows.filter((r) => r.coil_no.trim()).map((r) => ({ coil_no: r.coil_no.trim(), weight_kg: kgOf(r.qty, b.unit),
            cn_amount: !b.cnOn ? "" : b.sameCn ? b.cnAmount : r.cn_amount, cn_text: !b.cnOn ? "" : b.sameCn ? b.cnText : r.cn_text }));
        this.state.busy = true;
        try {
            const r = await this.call("save_lines", [this.state.da.id, b.shared, rows]);
            this.setDa(r.da); this.state.bulk = null;
            this.toast(`${r.created} coil(s) saved together.`);
        } catch { /* shown */ } finally { this.state.busy = false; }
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
    async deleteDa() {
        const d = this.state.da;
        if (!window.confirm(`Delete draft DA ${d.name} with its ${d.lines.length} coil(s)? It was never submitted; the deletion is recorded.`)) { return; }
        try {
            this.state.list = await this.call("da_delete", [d.id]);
            this.state.da = null; this.state.line = null; this.state.preview = null;
            this.toast(`Draft DA ${d.name} deleted.`);
        } catch { /* shown */ }
    }
    // Copy Previous: a new coil with the last coil's item, codes, method and rates; coil number, weight and credit note stay empty
    copyPrevious() {
        const d = this.state.da, last = d && d.lines[d.lines.length - 1];
        if (last) { this.duplicateLine(last); }
    }
    get showPractice() { return !!(this.state.list && this.state.list.show_practice); }
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
    get signedContracts() { return this.state.list ? this.state.list.contracts : []; }

    // ------------------------------------------------------------------ real entry: one coil
    newLine() {
        const l = blankLine(), d = this.state.da;
        if (d.contract_lines.length === 1) {
            const cl = d.contract_lines[0];
            l.contract_line_id = String(cl.id); l.basic_rate = cl.basic_rate ? String(cl.basic_rate) : "";
            if (cl.target_customer) { l.customer = cl.target_customer; }
        }
        if (d.sold_out) { l.customer = d.sold_out; }           // Sold (OUT) of the DA; change it per coil when a coil goes elsewhere
        const last = d.lines[d.lines.length - 1];
        if (last) {            // the next coil of the same DA usually goes to the same customer with the same codes
            l.customer = last.customer; l.customer_code = last.customer_code; l.trade_code = last.trade_code; l.pl_code = last.pl_code;
            l.method = pickOf(last.method); l.basic_rate = last.basic_rate ? String(last.basic_rate) : l.basic_rate;
        }
        const auto = d.auto_codes || {};
        for (const f of ["customer_code", "trade_code", "pl_code"]) { if (!l[f] && auto[f]) { l[f] = auto[f]; } }
        this.state.line = l; this.state.preview = null; this.state.missing = []; this.state.itemMsg = ""; this.state.error = "";
        this.checkCodes();
        this.focusSoon(l.contract_line_id ? "#ei-fd-coil" : "#ei-fd-item");
    }
    // a new coil with the repeatable details of an existing one; the coil number, weight and credit note are left empty
    duplicateLine(row) {
        const l = blankLine();
        Object.assign(l, { contract_line_id: String(row.contract_line_id), grade: row.grade, method: pickOf(row.method),
            basic_rate: row.basic_rate ? String(row.basic_rate) : "", sale_offset: String(row.sale_offset || 0), sale_typed: row.sale_typed,
            sale_rate: row.sale_typed ? String(row.sale_rate || "") : "", purchase_rate: row.method === "direct_no_commission" ? String(row.purchase_rate || "") : "",
            customer: row.customer, customer_code: row.customer_code, trade_code: row.trade_code, pl_code: row.pl_code, rate_note: row.rate_note });
        this.state.line = l; this.state.preview = null; this.state.missing = []; this.state.itemMsg = "";
        this.focusSoon("#ei-fd-coil");
        this.refresh(); this.checkCodes();
    }
    editLine(row) {
        this.state.line = { ...blankLine(), ...row, method: pickOf(row.method), contract_line_id: String(row.contract_line_id), weight_kg: String(row.weight_kg || ""),
            unit: "MTL", qty: row.weight_kg ? String(parseFloat((row.weight_kg / 1000).toFixed(6))) : "", small_ok: !!(row.weight_kg && row.weight_kg < SMALL_KG),
            basic_rate: row.basic_rate ? String(row.basic_rate) : "", sale_offset: String(row.sale_offset || 0),
            cn_amount: row.cn_amount ? String(row.cn_amount) : "", sale_rate: String(row.sale_rate || ""), purchase_rate: String(row.purchase_rate || "") };
        this.state.missing = []; this.state.itemMsg = "";
        this.refresh(); this.checkCodes();
    }
    closeLine() { this.state.line = null; this.state.preview = null; this.state.missing = []; this.state.itemMsg = ""; this.state.codeCheck = null; this.state.itemLook = null; }
    setLine(key, ev) {
        const v = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        this.state.line[key] = v;
        const fk = { coil_no: "coil", qty: "weight", basic_rate: "rate", purchase_rate: "rate", sale_rate: "rate", loss_reason: "loss" }[key];
        if (fk && this.state.missing.length) { this.state.missing = this.state.missing.filter((m) => m.key !== fk); }
        if (key === "qty") { this.state.line.weight_kg = kgOf(v, this.state.line.unit); this.state.line.small_ok = false; }
        if (key === "contract_line_id" && this.cl && !this.state.line.basic_rate) { this.state.line.basic_rate = String(this.cl.basic_rate || ""); }
        this.refresh();
    }
    setUnit(unit) {
        const l = this.state.line;
        l.unit = unit; l.weight_kg = kgOf(l.qty, unit); l.small_ok = false;
        this.refresh();
    }
    pickMethod(key) {
        const l = this.state.line;
        l.method = key;
        this.state.missing = this.state.missing.filter((m) => m.key !== "method");
        this.refresh();
        this.focusSoon(".ei-fd-editor .ei-fd-rate input");
    }
    payload() {
        const l = this.state.line;
        return { contract_line_id: l.contract_line_id, coil_no: l.coil_no, grade: l.grade, thickness: l.thickness, width: l.width, weight_kg: l.weight_kg, method: l.method,
            basic_rate: l.basic_rate, sale_offset: l.sale_offset, sale_typed: l.sale_typed, sale_rate: l.sale_rate, purchase_rate: l.purchase_rate,
            cn_amount: l.cn_amount, cn_text: l.cn_text, loss_reason: l.loss_reason, rate_note: l.rate_note,
            customer_id: l.customer && l.customer.id, customer_code_id: l.customer_code && l.customer_code.id,
            trade_code_id: l.trade_code && l.trade_code.id, pl_code_id: l.pl_code && l.pl_code.id, small_weight_ok: !!l.small_ok };
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
        const problems = this.lineProblems();
        this.state.missing = problems;
        if (problems.length) { this.state.error = ""; this.fixField(problems[0]); return; }
        if (this.smallWeight && !this.state.line.small_ok) { this.state.error = `${this.state.line.weight_kg} kg is only ${this.mtl} MTL. Choose MTL, or tick “Yes, the weight is in kg”.`; return; }
        this.state.busy = true;
        try {
            const r = await this.call("save_line", [this.state.da.id, this.state.line.id || false, this.payload()]);
            this.setDa(r.da);
            const saved = r.da.lines.find((x) => x.id === r.line_id);
            this.toast(saved && saved.code_issue ? "Saved. Check the code warning before submitting." : `Saved: coil ${saved ? saved.coil_no : ""}, ${saved ? fmt(saved.mtl, 3) : ""} MTL.`,
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
        this.focusSoon("#ei-fd-look"); this.openLookScroll();
    }
    lookInput(ev) {
        this.state.look.term = ev.target.value; this.state.look.ambiguous = 0;
        clearTimeout(this.timers.look);
        this.timers.look = setTimeout(() => { this.timers.look = null; this.runLook(); }, 200);
    }
    async runLook() {
        const s = this.state.look, kind = { customer_code: "customer", trade_code: "trade", pl_code: "pl" }[s.field];
        const seq = ++this.lookSeq, term = s.term, field = s.field;
        s.busy = true;
        try {
            const rows = field === "customer" ? await this.orm.call(MODEL, "party_search", ["customer", term])
                : await this.orm.call(MODEL, "code_search", [kind, term, this.state.da.printed_customer || ""]);
            if (seq === this.lookSeq && this.state.look.field === field) { this.state.look.rows = rows; }   // an older, slower answer never wins
        } finally { if (seq === this.lookSeq) { s.busy = false; } }
    }
    async choose(row) {
        const f = this.state.look.field;
        if (f === "customer") {
            const p = await this.call("party_take", ["customer", row]);      // an old code or a new name becomes the customer at once
            if (!p) { return; }
            row = p;
        }
        this.state.line[f] = f === "customer" ? { id: row.id, name: row.name } : row;
        this.state.look = { field: null, term: "", rows: [], busy: false }; this.state.error = "";
        this.refresh(); this.checkCodes();
        this.advanceSoon(`.ei-fd-pick[data-f="${f}"] .ei-fd-link`);
    }
    clearPick(f) { this.state.line[f] = null; this.refresh(); this.checkCodes(); }
    openLookScroll() { setTimeout(() => { const el = document.querySelector(".ei-fd-look"); if (el) { el.scrollIntoView({ block: "nearest" }); } }, 80); }
    // ------------------------------------------------------------------ codes: checked together, filled by themselves where verified
    checkCodes() {
        clearTimeout(this.timers.codes);
        this.timers.codes = setTimeout(async () => {
            const l = this.state.line;
            if (!l || !this.state.da) { this.state.codeCheck = null; return; }
            const v = { trade_code_id: l.trade_code && l.trade_code.id, pl_code_id: l.pl_code && l.pl_code.id,
                customer_code_id: l.customer_code && l.customer_code.id, customer_id: l.customer && l.customer.id };
            try { this.state.codeCheck = await this.orm.call(MODEL, "check_codes", [this.state.da.id, v]); } catch { this.state.codeCheck = null; }
        }, 150);
    }
    useCode(f, o) { this.state.line[f] = o; this.refresh(); this.checkCodes(); }
    async allowPair() {
        const reason = window.prompt("Why are these purchase and P&L codes right for this coil? (kept on the coil)");
        if (!reason || !reason.trim()) { return; }
        try {
            const da = await this.call("allow_pair", [this.state.da.id, this.state.line.id, reason]);
            this.setDa(da); const row = da.lines.find((x) => x.id === this.state.line.id);
            if (row) { this.state.line.pair_allowed = row.pair_allowed; }
            this.toast("Codes allowed on this coil; the reason is kept.");
        } catch { /* shown */ }
    }
    // ------------------------------------------------------------------ Sold To changed on a draft: which coils follow
    get soldFollowers() {
        const d = this.state.da, old = d && d.sold_out;
        return d ? d.lines.filter((l) => !l.customer || (old && l.customer.id === old.id)).length : 0;
    }
    soldChangeStart() { this.state.soldChange = { term: "", rows: [], picked: null }; this.focusSoon("#ei-fd-soldnew"); }
    soldChangeInput(ev) {
        const sc = this.state.soldChange, term = ev.target.value; sc.term = term;
        clearTimeout(this.timers.sold);
        this.timers.sold = setTimeout(async () => { const rows = term.trim() ? await this.orm.call(MODEL, "party_search", ["customer", term]) : []; if (sc.term === term) { sc.rows = rows; } }, 200);
    }
    async soldChangeKey(ev) {
        if (ev.key === "Escape") { this.state.soldChange = null; return; }
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        const term = ev.target.value; if (!term.trim()) { return; }
        const rows = await this.orm.call(MODEL, "party_search", ["customer", term]);
        const hit = rows.find((r) => r.kind !== "new");
        if (hit) { this.soldChangePick(hit); } else { this.state.soldChange.rows = rows; this.noMatch(term); }
    }
    soldChangePick(row) { this.state.soldChange.picked = row; this.state.error = ""; }
    async soldChangeApply(mode) {
        try { this.setDa(await this.call("da_set_sold_out", [this.state.da.id, this.state.soldChange.picked, mode])); this.state.soldChange = null; this.toast("Sold To changed."); }
        catch { /* shown */ }
    }
    async lookKey(ev) {
        if (ev.key === "Escape") { this.state.look.field = null; return; }
        if (ev.key === "ArrowDown") { const o = ev.target.parentElement.querySelector(".ei-fd-lookrows button"); if (o) { ev.preventDefault(); o.focus(); } return; }
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        // always the search for exactly what is typed now: an earlier search still on its way never answers this Enter
        this.state.look.term = ev.target.value; clearTimeout(this.timers.look); this.timers.look = null;
        await this.runLook();
        const t = this.state.look.term.trim().toLowerCase(), rows = this.state.look.rows.filter((r) => r.kind !== "new");
        const exact = rows.find((r) => (r.code || "").toLowerCase() === t || (r.ref || "").toLowerCase() === t || (r.name || "").trim().toLowerCase() === t);
        // a code is an accounting choice: Enter takes it only when it is certain (the exact code or name, or the only match);
        // several codes matching a few letters stay listed for the person to pick (a customer name keeps the first match)
        const hit = exact || (this.state.look.field === "customer" || rows.length === 1 ? rows[0] : null);
        if (hit) { this.choose(hit); }
        else if (rows.length) { this.state.error = ""; this.state.look.ambiguous = rows.length; const o = document.querySelector(".ei-fd-look .ei-fd-lookrows button"); if (o) { o.focus(); } }
        else if (this.state.look.term) { this.noMatch(this.state.look.term); }
    }

    focusSoon(sel) {
        const go = () => { const el = document.querySelector(sel); if (el && document.activeElement !== el) { el.focus(); if (el.setSelectionRange && el.value) { el.setSelectionRange(el.value.length, el.value.length); } } return !!el; };
        setTimeout(() => { if (!go()) { setTimeout(go, 120); } }, 20);
    }
    toast(message, type = "success") { this.notification.add(message, { type }); }
}

registry.category("actions").add("ei_da_feeding", EiDaFeeding);
