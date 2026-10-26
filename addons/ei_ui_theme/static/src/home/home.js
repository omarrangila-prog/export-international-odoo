import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { iconPath } from "../common/icons";
import { EiSearchBox } from "../search/search_box";

const SCHEME_COOKIE = "color_scheme";
const FILTERS = [
    { key: "all", label: "All" },
    { key: "act", label: "Needs my action" },
    { key: "team", label: "Team queue" },
    { key: "mine", label: "Assigned to me" },
    { key: "overdue", label: "Overdue" },
    { key: "escalated", label: "Escalated" },
];
const PRIORITY_WORD = { high: "High", medium: "Medium", low: "Normal" };
const VISIBLE_TASKS = 8;
const SNOOZE = [[1, "Until tomorrow"], [3, "For 3 days"], [7, "For a week"]];

// a smooth curve through the points (a Catmull-Rom spline as cubic curves), kept inside the chart's height
function smoothPath(pts, height) {
    const clamp = (y) => Math.min(height, Math.max(0, y));
    let line = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
    for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2, t = 0.18;
        const c1 = [p1[0] + (p2[0] - p0[0]) * t, clamp(p1[1] + (p2[1] - p0[1]) * t)];
        const c2 = [p2[0] - (p3[0] - p1[0]) * t, clamp(p2[1] - (p3[1] - p1[1]) * t)];
        line += ` C${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
    }
    return line;
}

export class EiHome extends Component {
    static template = "ei_ui_theme.Home";
    static components = { EiSearchBox };
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            loading: true, error: false, data: null, filter: "all", showSnoozed: false, menu: null, dialog: null, busy: false,
            toast: null, tables: { aging: false }, snoozed: null, allTasks: false,
            period: "14d", flowTables: {}, flowTip: null, pipeTip: null, ask: "", newMenu: false, allAlerts: false, openDays: {}, phone: window.innerWidth <= 640, folds: {},
        });
        this.filters = FILTERS;
        this.snoozeChoices = SNOOZE;
        this.toastTimer = null;
        this.onKey = (ev) => this.handleKey(ev);
        this.onDocClick = (ev) => {
            if (this.state.menu && !ev.target.closest(".ei-menu, .ei-more")) { this.state.menu = null; this.lastFocus = null; }
            if (this.state.newMenu && !ev.target.closest(".ei-newwrap")) { this.state.newMenu = false; }
        };
        onWillStart(() => this.load());
        this.onResize = () => { this.state.phone = window.innerWidth <= 640; };
        onMounted(() => { document.addEventListener("keydown", this.onKey); document.addEventListener("click", this.onDocClick); window.addEventListener("resize", this.onResize); });
        onWillUnmount(() => { document.removeEventListener("keydown", this.onKey); document.removeEventListener("click", this.onDocClick); window.removeEventListener("resize", this.onResize); clearTimeout(this.toastTimer); });
    }

    // ------------------------------------------------------------------ data
    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("ei.home", "get_data", [this.state.period]);
            this.state.error = false;
        } catch {
            this.state.error = true;
        }
        this.state.loading = false;
    }
    async loadWork() {
        const work = await this.orm.call("ei.work", "tasks", [false]);
        this.state.data.work = work;
        if (this.state.showSnoozed) { this.state.snoozed = (await this.orm.call("ei.work", "tasks", [true])).items; }
        this.state.data.header.approvals = work.items.filter((t) => t.can_act && /approve|verify|post|signoff/.test(t.type)).length;
    }

    // ------------------------------------------------------------------ small helpers used by the template
    icon(name) { return iconPath(name); }
    priorityWord(p) { return PRIORITY_WORD[p] || p; }
    get layout() { return this.state.data.layout.filter((s) => this.hasSection(s)); }
    hasSection(key) {
        const d = this.state.data;
        if (key === "summary") { return this.summaryTiles.length > 0; }
        if (key === "decide") { return true; }
        if (key === "hero") { return d.pipeline.length > 0 || !!d.charts.aging || !!d.charts.material; }
        if (key === "flows") { return d.flows.length > 0 || d.banks.length > 0 || !!d.top_owing; }
        if (key === "recent") { return !!d.recent && d.recent.rows.length > 0; }
        if (key === "kpis") { return this.kpis.length > 0; }
        if (key === "alerts") { return true; }
        if (key === "work") { return d.work.items.length > 0 || d.work.counts.snoozed > 0 || d.work.counts.others > 0 || true; }
        if (key === "charts") { return !!d.charts.material && !!d.charts.aging; }       // with no ageing card the material card sits in the hero
        if (key === "pipeline") { return d.pipeline.length > 0; }
        if (key === "activity") { return d.activity.length > 0; }
        if (key === "quick") { return d.quick.length > 0; }
        if (key === "system") { return !!d.system; }
        return false;
    }
    // one figure, one place: the summary strip carries what customers owe, the bank balance and the bank money to match
    get kpis() {
        const d = this.state.data, here = new Set();
        if (d.layout.includes("summary")) { ["ar", "bank", "waiting"].forEach((k) => here.add(k)); }
        else {
            if (this.agingHero) { here.add("ar"); }
            if (d.banks.length && d.layout.includes("flows")) { here.add("bank"); }
        }
        return d.kpis.filter((k) => !here.has(k.key));
    }
    get hasSummary() { return this.state.data.layout.includes("summary"); }
    // ---- the first screen: five figures (each says what it is made of), then what needs a person
    get summaryTiles() {
        const d = this.state.data, k = (key) => d.kpis.find((x) => x.key === key), out = [];
        const bank = k("bank"), ar = k("ar"), waiting = k("waiting");
        if (bank) { out.push({ key: "bank", label: "Bank balance", tag: "Book balance", value: bank.value, sub: bank.sub, tone: bank.tone, help: bank.help }); }
        if (ar) { out.push({ key: "ar", label: "Customers owe us", tag: "Posted ledger", value: ar.value, sub: ar.sub, tone: ar.tone, help: ar.help }); }
        if (waiting) { out.push({ key: "waiting", label: "Bank money to match", tag: "Not settled yet", value: waiting.value, sub: waiting.sub, tone: waiting.tone, help: waiting.help }); }
        if (ar || bank || waiting) {
            const items = d.work.items, act = items.filter((t) => t.can_act && !t.view_only);
            out.push({ key: "decisions", label: "Waiting for your decision", tag: "Your role", value: String(act.length), sub: act.length ? `${items.length - act.length} more in the team queue` : (items.length ? `Nothing for you; ${items.length} in the team queue` : "Nothing is waiting"), tone: act.length ? "warning" : "ok", help: "Steps your role may perform now. A step you prepared yourself needs a second person." });
        }
        const lifted = d.flows.find((f) => f.key === "lifted");
        if (lifted) { out.push({ key: "lifted", label: "Material lifted", tag: "Verified loadings", value: lifted.text, sub: `${lifted.delta.text} against the days before`, tone: lifted.delta.tone === "bad" ? "warning" : "ok", help: lifted.sub }); }
        return out;
    }
    onSummary(t) {
        if (t.key === "decisions") { this.state.filter = "act"; return this.goTo("work"); }
        if (t.key === "lifted") { return this.onFlow({ key: "lifted" }); }
        return this.onKpi({ key: t.key });
    }
    // ---- what needs a person: every alert (with its next step) and the first decisions, side by side
    get decideAlerts() { return this.state.allAlerts ? this.state.data.alerts : this.state.data.alerts.slice(0, 4); }
    get decideTasks() {
        const items = this.state.data.work.items, act = items.filter((t) => t.can_act && !t.view_only);
        return { mine: act.length > 0, rows: (act.length ? act : items).slice(0, 4), total: act.length || items.length };
    }
    goTo(sec) {
        if (this.foldable(sec) && !this.state.folds[sec]) { this.state.folds[sec] = true; }
        const go = () => {
            const el = document.getElementById("ei-h-" + sec);
            if (el) { el.scrollIntoView({ behavior: "smooth", block: "start" }); el.focus?.({ preventScroll: true }); }
        };
        if (this.isOpen(sec)) { setTimeout(go, 60); }
    }
    // ---- on a phone the secondary sections fold into one-line bars; what needs a person stays open
    foldable(sec) {
        if (!this.state.phone || ["summary", "decide", "alerts", "system"].includes(sec)) { return false; }
        return sec !== "work" || this.state.data.layout.includes("decide");     // the decisions block already shows the first items
    }
    isOpen(sec) { return !this.foldable(sec) || !!this.state.folds[sec]; }
    toggleFold(sec) { this.state.folds[sec] = !this.state.folds[sec]; }
    foldTitle(sec) { return { work: "All work", hero: "Contract to payment", flows: "Money and material", recent: "Recent documents", kpis: "At a glance", charts: "Material on contracts", activity: "What happened recently", quick: "Start something" }[sec] || sec; }
    get kpiMain() { return this.kpis.slice(0, 4); }
    get kpiMore() { return this.kpis.slice(4); }
    get tasks() {
        const rows = this.filteredTasks;
        return this.state.allTasks ? rows : rows.slice(0, VISIBLE_TASKS);
    }
    get hiddenTasks() { return Math.max(0, this.filteredTasks.length - VISIBLE_TASKS); }
    get filteredTasks() {
        const w = this.state.data.work;
        if (this.state.filter === "snoozed") { return this.state.snoozed || []; }
        return w.items.filter((t) => {
            if (this.state.filter === "mine") { return t.assignee_me || t.my_activity; }
            if (this.state.filter === "act") { return t.can_act && !t.view_only; }
            if (this.state.filter === "team") { return !t.can_act || t.view_only; }
            if (this.state.filter === "overdue") { return t.overdue; }
            if (this.state.filter === "escalated") { return t.status === "escalated"; }
            return true;
        });
    }
    filterCount(key) {
        const c = this.state.data.work.counts;
        if (key === "all") { return this.state.data.work.total; }
        const items = this.state.data.work.items;
        if (key === "act") { return items.filter((t) => t.can_act && !t.view_only).length; }
        if (key === "team") { return items.filter((t) => !t.can_act || t.view_only).length; }
        return { mine: c.mine, overdue: c.overdue, escalated: c.escalated }[key] || 0;
    }
    // ---- the Overview cards: every shape below is drawn from the numbers the server counted
    // the pipeline: one card per step. Each step counts its OWN kind of record, so the counts are never drawn as one series; the small bar
    // inside a card is that step's own split between what is done and what waits for a person
    get stages() {
        return this.state.data.pipeline.map((s) => {
            const total = s.count + s.waiting;
            return { ...s, donePct: total ? Math.round((s.count / total) * 100) : 0, waitPct: total ? 100 - Math.round((s.count / total) * 100) : 0, total };
        });
    }
    get ageIcons() { return ["calendar", "snooze", "flag", "alert", "alert"]; }
    get agingHero() {
        const a = this.state.data.charts.aging;
        if (!a) { return null; }
        const total = a.rows.reduce((t, r) => t + r.value, 0);
        const late = a.rows.slice(1).reduce((t, r) => t + r.value, 0);
        const rows = a.rows.map((r, i) => ({ ...r, step: i, pct: total > 0 ? Math.round((r.value / total) * 100) : 0, w: total > 0 ? Math.max(r.value ? 2 : 0, (r.value / total) * 100) : 0 }));
        return { ...a, total, latePct: total > 0 ? Math.round((late / total) * 100) : 0, rows,
            meterLabel: "Share of what customers owe, by how late: " + rows.map((r) => `${r.label} ${r.pct}%`).join(", ") };
    }
    flowMax(f) { return Math.max(1e-9, ...f.series.map((p) => p.v)); }
    flowBars(f) {
        const max = this.flowMax(f);
        return f.series.map((p, i) => ({ ...p, i, h: p.v > 0 ? Math.max(6, (p.v / max) * 100) : 0 }));
    }
    // a smooth line through the daily values (viewBox 0 0 100 40; y grows downwards)
    flowPaths(f) {
        const n = f.series.length;
        const pts = this.flowPoints(f);
        const line = smoothPath(pts, 40);
        return { line, area: `${line} L100,40 L0,40 Z`, endTop: (pts[n - 1][1] / 40) * 100 };
    }
    flowPoints(f) {
        const n = f.series.length, max = this.flowMax(f);
        return f.series.map((p, i) => [n > 1 ? (i / (n - 1)) * 100 : 50, 36 - (p.v / max) * 30]);
    }
    flowDotTop(f, tip) {                   // where the line is on the hovered day, as a share of the chart height
        const i = f.series.findIndex((p) => p.iso === tip.iso);
        return i < 0 ? 50 : (this.flowPoints(f)[i][1] / 40) * 100;
    }
    hoverFlow(ev, f) {
        const box = ev.currentTarget.getBoundingClientRect();
        const rtl = document.documentElement.dir === "rtl";
        const x = rtl ? box.right - ev.clientX : ev.clientX - box.left;
        const i = Math.min(f.series.length - 1, Math.max(0, Math.floor((x / box.width) * f.series.length)));
        this.state.flowTip = { key: f.key, i, left: ((i + 0.5) / f.series.length) * 100 };
    }
    leaveFlow() { this.state.flowTip = null; }
    flowTipOf(f) {
        const t = this.state.flowTip;
        if (!t || t.key !== f.key) { return null; }
        const n = f.series.length;
        return { ...f.series[t.i], left: f.key === "invoiced" && n > 1 ? (t.i / (n - 1)) * 100 : t.left };
    }
    toggleFlowTable(f) { this.state.flowTables[f.key] = !this.state.flowTables[f.key]; }
    stageTip(s) { return `${s.main}. ${s.definition} ${s.waiting ? s.sub + ". " + s.waiting_def : s.sub + "."}`; }
    stageWord(s) { return s.main.replace(/^[\d,.]+\s*/, ""); }       // "10 loadings verified" -> "loadings verified" (the number is shown big above it)
    initials(name) {          // "DEMO Customer - Rehman Traders" -> "RT": the part after the last " - " is the real name
        const plain = String(name || "?").split(" - ").pop();
        return plain.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
    }
    async setPeriod(ev) {
        this.state.period = ev.target.value;
        await this.load();
    }
    onFlow(f) { return this.call("open_flow", [f.key, this.state.period]); }
    // the ageing card opens the receivables report, on the band that was clicked
    onAgeRow(r) {
        const keys = ["current", "d1_30", "d31_60", "d61_90", "d90p"];
        return this.action.doAction("ei_reports.action_report_ar_aging", { additionalContext: r ? { ["search_default_b_" + keys[r.step]]: 1 } : {} });
    }
    onOwing(r) { return this.call("open", ["ei.party360", r.partner_id], "ei.search"); }
    onRecent(r) { return this.call("open", [r.model, r.res_id], "ei.search"); }
    onAsk() {
        const text = this.state.ask.trim();
        if (!text) { return; }
        return this.action.doAction("ei_assistant.action_ei_assistant", { additionalContext: { ei_ask: text } });
    }
    onAskChip(text) { this.state.ask = text; return this.onAsk(); }
    onAskInput(ev) { this.state.ask = ev.target.value; }
    shortName(item) { return item.title.length > 48 ? item.title.slice(0, 47) + "..." : item.title; }

    // ------------------------------------------------------------------ feedback
    say(text, kind = "ok") {
        clearTimeout(this.toastTimer);
        this.state.toast = { text, kind };
        this.toastTimer = setTimeout(() => { this.state.toast = null; }, 5000);
    }
    errorText(e) { return (e && e.data && e.data.message) || "Something went wrong. Nothing was changed."; }

    // ------------------------------------------------------------------ keyboard
    handleKey(ev) {
        if (ev.key === "Escape") {
            if (this.state.dialog) { this.closeDialog(); ev.stopPropagation(); } else if (this.state.newMenu) { this.state.newMenu = false; } else if (this.state.menu) { this.closeMenu(); }
            return;
        }
        // dialog: keep Tab inside it
        if (ev.key === "Tab" && this.state.dialog) {
            const box = document.querySelector(".ei-modal");
            const items = box ? [...box.querySelectorAll("select, input, textarea, button:not([disabled])")] : [];
            if (items.length) {
                const first = items[0], last = items[items.length - 1];
                if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
                else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
                else if (!box.contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
            }
            return;
        }
        // row menu: arrow keys move between its items
        if ((ev.key === "ArrowDown" || ev.key === "ArrowUp") && this.state.menu) {
            const items = [...document.querySelectorAll(".ei-menu button")];
            if (items.length) {
                ev.preventDefault();
                const i = items.indexOf(document.activeElement);
                items[(i + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
            }
            return;
        }
        const tag = (ev.target.tagName || "").toLowerCase();
        if (ev.key === "/" && !ev.ctrlKey && !ev.metaKey && !["input", "textarea", "select"].includes(tag) && !ev.target.isContentEditable) {
            const el = document.getElementById("ei-search-q");
            if (el) { ev.preventDefault(); el.focus(); el.select(); }
        }
    }
    rememberFocus() { if (!this.lastFocus) { this.lastFocus = document.activeElement; } }   // keep the button that opened the menu, not the menu item that has since closed
    restoreFocus() { if (this.lastFocus && document.contains(this.lastFocus)) { this.lastFocus.focus(); } this.lastFocus = null; }
    closeMenu() { this.state.menu = null; this.restoreFocus(); }

    // ------------------------------------------------------------------ clicks: always open the real records
    async call(method, args, model = "ei.home") {
        const act = await this.orm.call(model, method, args);
        if (act) { await this.action.doAction(act); }
    }
    onKpi(k) { return this.call("open_kpi", [k.key]); }
    onAlert(a) { return this.call("open_alert", [a.key]); }
    onStage(s) { return this.call("open_stage", [s.key]); }
    onQuick(q) { this.state.newMenu = false; return this.call("open_quick", [q.key]); }
    toggleNew() { this.state.newMenu = !this.state.newMenu; if (this.state.newMenu) { setTimeout(() => { const el = document.querySelector(".ei-newmenu button"); if (el) { el.focus(); } }, 0); } }
    onStep(s) { return this.call("open_step", [s.key]); }
    onTask(t) { return this.call("open_task", [t.model, t.res_id], "ei.work"); }
    // a digest: repeated events by the same person on the same day ("8 truck loadings created") fold into one line that opens
    get activityRows() {
        const rows = [], byKey = new Map();
        for (const a of this.state.data.activity) {
            const day = a.when.slice(0, 6), key = `${day}|${a.who}|${a.text}`;
            if (!byKey.has(key)) { const g = { key, day, who: a.who, text: a.text, items: [] }; byKey.set(key, g); rows.push(g); }
            byKey.get(key).items.push(a);
        }
        return rows.map((g) => ({ ...g, many: g.items.length >= 3, open: !!this.state.openDays[g.key] }));
    }
    toggleDigest(g) { this.state.openDays[g.key] = !this.state.openDays[g.key]; }
    onActivity(a) { return this.call("open", [a.model, a.res_id], "ei.search"); }
    onReminders() { return this.action.doAction("mail.mail_activity_action_my"); }
    onRefresh() { return this.load(); }
    setFilter(key) {
        this.state.filter = key;
        this.state.allTasks = false;
        if (key === "snoozed") { this.loadWork(); }
    }
    async toggleSnoozed() {
        this.state.showSnoozed = !this.state.showSnoozed;
        this.state.filter = this.state.showSnoozed ? "snoozed" : "all";
        if (this.state.showSnoozed) { this.state.snoozed = (await this.orm.call("ei.work", "tasks", [true])).items; }
    }

    // ------------------------------------------------------------------ My Work actions
    toggleMenu(t, ev) {
        ev.stopPropagation();
        if (this.state.menu === t.id) { this.closeMenu(); return; }
        this.lastFocus = document.activeElement;
        this.state.menu = t.id;
        setTimeout(() => { const first = document.querySelector(".ei-menu button"); if (first) { first.focus(); } }, 0);   // keyboard users land inside the menu
    }
    async snooze(t, days) {
        this.state.menu = null;
        try { await this.orm.call("ei.work", "snooze", [t.model, t.res_id, days]); await this.loadWork(); this.say("Put aside. It comes back " + this.snoozeChoices.find((c) => c[0] === days)[1].toLowerCase() + "."); }
        catch (e) { this.say(this.errorText(e), "bad"); }
    }
    async unsnooze(t) {
        try { await this.orm.call("ei.work", "unsnooze", [t.model, t.res_id]); await this.loadWork(); this.say("Back on your list."); }
        catch (e) { this.say(this.errorText(e), "bad"); }
    }
    async markDone(t) {
        this.state.menu = null;
        try { await this.orm.call("ei.work", "done", [t.my_activity]); await this.loadWork(); this.say("Your reminder is closed. The record itself stays until its step is done."); }
        catch (e) { this.say(this.errorText(e), "bad"); }
    }
    async openAssign(t) {
        this.state.menu = null;
        this.rememberFocus();
        try {
            const users = await this.orm.call("ei.work", "assignable_users", [t.model, t.res_id]);
            this.state.dialog = { kind: "assign", task: t, users, user_id: users.length ? users[0].id : "", deadline: "", note: "", error: "" };
            setTimeout(() => { const el = document.querySelector(".ei-modal select"); if (el) { el.focus(); } }, 0);
        } catch (e) { this.say(this.errorText(e), "bad"); }
    }
    openEscalate(t) {
        this.state.menu = null;
        this.rememberFocus();
        this.state.dialog = { kind: "escalate", task: t, note: "", error: "" };
        setTimeout(() => { const el = document.querySelector(".ei-modal textarea"); if (el) { el.focus(); } }, 0);
    }
    closeDialog() { this.state.dialog = null; this.restoreFocus(); }
    async submitDialog() {
        const d = this.state.dialog;
        if (!d || this.state.busy) { return; }
        this.state.busy = true;
        try {
            if (d.kind === "assign") {
                if (!d.user_id) { d.error = "Choose a person."; this.state.busy = false; return; }
                await this.orm.call("ei.work", "assign", [d.task.model, d.task.res_id, Number(d.user_id), d.deadline || false, d.note || false]);
                const who = d.users.find((u) => u.id === Number(d.user_id));
                this.state.dialog = null; await this.loadWork(); this.say("Assigned to " + (who ? who.name : "them") + ". They get a reminder.");
            } else {
                const res = await this.orm.call("ei.work", "escalate", [d.task.model, d.task.res_id, d.note]);
                this.state.dialog = null; await this.loadWork(); this.say("Escalated to " + res.managers.join(", ") + ".");
            }
        } catch (e) { d.error = this.errorText(e); }
        this.state.busy = false;
    }

    // ------------------------------------------------------------------ theme
    get isDark() { return document.cookie.split(";").map((c) => c.trim()).includes(SCHEME_COOKIE + "=dark"); }
    toggleTheme() {
        document.cookie = `${SCHEME_COOKIE}=${this.isDark ? "light" : "dark"}; path=/; max-age=31536000; samesite=lax`;
        window.location.reload();
    }
}

registry.category("actions").add("ei_home", EiHome);
