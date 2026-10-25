import { useService } from "@web/core/utils/hooks";
import { Component, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { iconPath } from "../common/icons";

const DELAY = 220;
const MIN = 2;

/** Universal search: parties, old codes, contracts, DAs, orders, truck loadings, invoices and bank references.
 *  Results come from the server already filtered by the user's access; nothing is cached in the browser. */
export class EiSearchBox extends Component {
    static template = "ei_ui_theme.SearchBox";
    props = useProps({ placeholder: t.string().optional(), autofocus: t.boolean().optional() });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ q: "", data: null, active: -1, open: false, loading: false, failed: false });
        this.timer = null;
        onWillUnmount(() => clearTimeout(this.timer));
    }

    get flat() {
        return this.state.data ? this.state.data.groups.flatMap((g) => g.hits) : [];
    }
    icon(name) { return iconPath(name); }
    indexOf(hit) { return this.flat.indexOf(hit); }

    /** split a text around the typed words so the match can be highlighted without injecting HTML */
    parts(text) {
        const q = this.state.q.trim();
        if (!q) { return [{ t: text, m: false }]; }
        const i = text.toLowerCase().indexOf(q.toLowerCase());
        if (i < 0) { return [{ t: text, m: false }]; }
        return [{ t: text.slice(0, i), m: false }, { t: text.slice(i, i + q.length), m: true }, { t: text.slice(i + q.length), m: false }].filter((p) => p.t);
    }

    onFocus() { if (this.state.data) { this.state.open = true; } }
    onBlur() { this.state.open = false; }

    focus() { const el = document.getElementById("ei-search-q"); if (el) { el.focus(); el.select(); } }

    onInput(ev) {
        this.state.q = ev.target.value;
        clearTimeout(this.timer);
        if (this.state.q.trim().length < MIN) {
            this.state.data = null; this.state.open = false; return;
        }
        this.state.loading = true;
        this.timer = setTimeout(() => this.run(), DELAY);
    }
    async run() {
        const q = this.state.q.trim();
        try {
            const res = await this.orm.call("ei.search", "search", [q]);
            if (q === this.state.q.trim()) {
                this.state.data = res; this.state.active = res.total ? 0 : -1; this.state.open = true; this.state.failed = false;
            }
        } catch {
            this.state.failed = true; this.state.data = null; this.state.open = true;
        }
        this.state.loading = false;
    }
    onKeydown(ev) {
        const n = this.flat.length;
        if (ev.key === "ArrowDown" && n) { ev.preventDefault(); this.state.open = true; this.state.active = (this.state.active + 1) % n; }
        else if (ev.key === "ArrowUp" && n) { ev.preventDefault(); this.state.active = (this.state.active - 1 + n) % n; }
        else if (ev.key === "Enter") {
            ev.preventDefault();
            const hit = this.flat[this.state.active];
            if (this.state.open && hit) { this.pick(hit); } else { clearTimeout(this.timer); this.run(); }
        } else if (ev.key === "Escape") { this.state.open = false; ev.stopPropagation(); }
    }
    async pick(hit) {
        this.state.open = false;
        const act = await this.orm.call("ei.search", "open", [hit.model, hit.res_id]);
        if (act) { await this.action.doAction(act); }
    }
}
