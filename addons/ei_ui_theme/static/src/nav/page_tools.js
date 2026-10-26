import { Component, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";

// Small page tools that Odoo's own views do not have:
//  * a density switch for lists (comfortable or compact), remembered in this browser;
//  * "label: value" captions on every cell of a list, taken from the column titles, so that on a phone a line item can be a card
//    (the CSS in screens.scss hides the header row and prints the caption in front of each value).
const KEY = "ei.density";
const read = () => { try { return localStorage.getItem(KEY) === "compact"; } catch { return false; } };

export class EiPageTools extends Component {
    static template = "ei_ui_theme.PageTools";
    setup() {
        this.state = proxy({ list: false, compact: read(), top: 0, right: 0 });
        this.timer = null;
        this.schedule = () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.scan(), 120); };
        onMounted(() => {
            this.apply();
            this.observer = new MutationObserver(this.schedule);
            this.observer.observe(document.body, { childList: true, subtree: true });
            window.addEventListener("resize", this.schedule);
            this.scan();
        });
        onWillUnmount(() => { clearTimeout(this.timer); this.observer.disconnect(); window.removeEventListener("resize", this.schedule); });
    }
    scan() {
        const pager = document.querySelector(".o_list_view .o_control_panel .o_cp_pager");
        const table = document.querySelector(".o_list_view .o_list_table");
        this.state.list = !!(pager && table) && window.innerWidth >= 768;
        if (this.state.list) {
            const r = pager.getBoundingClientRect();
            const chat = document.querySelector(".ei-chatter-toggle");
            this.state.top = Math.round(r.top + (r.height - 36) / 2);
            this.state.right = Math.round(window.innerWidth - r.left + 10);
            void chat;
        }
        if (window.innerWidth < 768) { this.captions(); }
    }
    captions() {
        for (const table of document.querySelectorAll(".o_form_view .o_field_x2many .o_list_table")) {
            const heads = [...table.querySelectorAll("thead th")];
            const labels = {};
            for (const th of heads) {
                if (!th.dataset.name) { continue; }
                const el = th.querySelector("[data-tooltip]") || th;
                labels[th.dataset.name] = (el.getAttribute("data-tooltip") || th.innerText || "").trim();
            }
            for (const td of table.querySelectorAll("tbody td[name]")) {
                const label = labels[td.getAttribute("name")];
                if (label && td.dataset.label !== label) { td.dataset.label = label; }
            }
            // the totals row: the same captions, by column position, and nothing printed for a column that has no total
            let col = 0;                                   // a totals cell may span several columns: count by span, not by index
            for (const td of table.querySelectorAll("tfoot tr td")) {
                const th = heads[col], el = th && (th.querySelector("[data-tooltip]") || th);
                const label = el ? (el.getAttribute("data-tooltip") || th.innerText || "").trim() : "";
                td.dataset.label = label ? "Total: " + label : "Total";
                if (td.innerText.trim()) { delete td.dataset.empty; } else { td.dataset.empty = "1"; }
                col += td.colSpan || 1;
            }
        }
    }
    apply() { document.body.classList.toggle("ei-density-compact", this.state.compact); }
    toggle() {
        this.state.compact = !this.state.compact;
        try { localStorage.setItem(KEY, this.state.compact ? "compact" : "comfortable"); } catch { /* not remembered */ }
        this.apply();
    }
}

registry.category("main_components").add("ei_page_tools", { Component: EiPageTools });
