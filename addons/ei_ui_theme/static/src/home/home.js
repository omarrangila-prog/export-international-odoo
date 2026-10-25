import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { iconPath } from "../common/icons";
import { EiSearchBox } from "../search/search_box";

const SCHEME_COOKIE = "color_scheme";
const FILTERS = [
    { key: "all", label: "All" },
    { key: "mine", label: "Assigned to me" },
    { key: "overdue", label: "Overdue" },
    { key: "escalated", label: "Escalated" },
];
const PRIORITY_WORD = { high: "High", medium: "Medium", low: "Normal" };
const VISIBLE_TASKS = 8;
const SNOOZE = [[1, "Until tomorrow"], [3, "For 3 days"], [7, "For a week"]];

function niceMax(v) {
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].find((x) => x * p >= v) || 10;
    return m * p;
}

function compact(n) {
    const a = Math.abs(n);
    if (a >= 1e6) { return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M"; }
    if (a >= 1e3) { return Math.round(n / 1e3) + "k"; }
    return String(Math.round(n));
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
            toast: null, tables: { cashflow: false, aging: false }, tip: null, snoozed: null, allTasks: false,
        });
        this.filters = FILTERS;
        this.snoozeChoices = SNOOZE;
        this.toastTimer = null;
        this.onKey = (ev) => this.handleKey(ev);
        this.onDocClick = (ev) => { if (this.state.menu && !ev.target.closest(".ei-menu, .ei-more")) { this.state.menu = null; this.lastFocus = null; } };
        onWillStart(() => this.load());
        onMounted(() => { document.addEventListener("keydown", this.onKey); document.addEventListener("click", this.onDocClick); });
        onWillUnmount(() => { document.removeEventListener("keydown", this.onKey); document.removeEventListener("click", this.onDocClick); clearTimeout(this.toastTimer); });
    }

    // ------------------------------------------------------------------ data
    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("ei.home", "get_data", []);
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
        if (key === "kpis") { return d.kpis.length > 0; }
        if (key === "alerts") { return true; }
        if (key === "work") { return d.work.items.length > 0 || d.work.counts.snoozed > 0 || d.work.counts.others > 0 || true; }
        if (key === "charts") { return Object.keys(d.charts).length > 0; }
        if (key === "pipeline") { return d.pipeline.length > 0; }
        if (key === "activity") { return d.activity.length > 0; }
        if (key === "quick") { return d.quick.length > 0; }
        if (key === "system") { return !!d.system; }
        return false;
    }
    get kpiMain() { return this.state.data.kpis.slice(0, 4); }
    get kpiMore() { return this.state.data.kpis.slice(4); }
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
            if (this.state.filter === "overdue") { return t.overdue; }
            if (this.state.filter === "escalated") { return t.status === "escalated"; }
            return true;
        });
    }
    filterCount(key) {
        const c = this.state.data.work.counts;
        if (key === "all") { return this.state.data.work.total; }
        return { mine: c.mine, overdue: c.overdue, escalated: c.escalated }[key] || 0;
    }
    get cashflow() {
        const c = this.state.data.charts.cashflow;
        const top = Math.max(1, ...c.days.map((d) => Math.max(d.invoiced, d.received)));
        const max = niceMax(top);          // a friendly top of the scale, so the middle tick is a round number too
        return {
            ...c, max, ticks: [1, 0.5, 0].map((f) => ({ f, label: compact(max * f) })),
            cols: c.days.map((d) => ({ ...d, hi: (d.invoiced / max) * 100, hr: (d.received / max) * 100 })),
        };
    }
    get aging() {
        const a = this.state.data.charts.aging;
        const max = Math.max(1, ...a.rows.map((r) => r.value));
        return { ...a, rows: a.rows.map((r, i) => ({ ...r, w: (r.value / max) * 100, step: i })) };
    }
    shortName(item) { return item.title.length > 48 ? item.title.slice(0, 47) + "..." : item.title; }
    showTip(col) { this.state.tip = col; }
    hideTip() { this.state.tip = null; }

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
            if (this.state.dialog) { this.closeDialog(); ev.stopPropagation(); } else if (this.state.menu) { this.closeMenu(); }
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
    onQuick(q) { return this.call("open_quick", [q.key]); }
    onStep(s) { return this.call("open_step", [s.key]); }
    onTask(t) { return this.call("open_task", [t.model, t.res_id], "ei.work"); }
    onActivity(a) { return this.call("open", [a.model, a.res_id], "ei.search"); }
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
