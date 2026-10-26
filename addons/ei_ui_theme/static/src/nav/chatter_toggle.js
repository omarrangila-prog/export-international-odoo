import { Component, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";

// The activity panel (messages, notes, reminders) used to take a third of every record. This button, beside the pager, hides or shows it;
// the choice is remembered in this browser. Where the record is already narrow, Odoo puts the panel below the sheet and there is nothing to hide.
const KEY = "ei.chatter.hidden";
// the record comes first: the activity panel is closed until a person opens it (and then stays as they left it)
const read = () => { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } };

export class EiChatterToggle extends Component {
    static template = "ei_ui_theme.ChatterToggle";
    setup() {
        this.state = proxy({ present: false, hidden: read(), top: 0, right: 0 });
        this.update = () => this.measure();
        onMounted(() => {
            this.apply();
            this.observer = new MutationObserver(this.update);
            this.observer.observe(document.body, { childList: true, subtree: true });
            window.addEventListener("resize", this.update);
            this.update();
        });
        onWillUnmount(() => { this.observer.disconnect(); window.removeEventListener("resize", this.update); });
    }
    measure() {
        const panel = document.querySelector(".o_form_view .o-mail-ChatterContainer");         // still in the page when it is hidden
        const pager = document.querySelector(".o_form_view .o_control_panel .o_cp_pager");
        const anchor = pager || document.querySelector(".o_form_view .o_control_panel");
        const present = !!document.querySelector(".o_form_view .o_form_renderer") && !!panel && !!anchor;
        this.state.present = present;
        if (present) {
            const r = anchor.getBoundingClientRect();
            this.state.top = Math.round(pager ? r.top + (r.height - 36) / 2 : r.top + 22);
            this.state.right = Math.round(pager ? window.innerWidth - r.left + 10 : 24);
        }
    }
    apply() { document.body.classList.toggle("ei-chatter-off", this.state.hidden); }
    toggle() {
        this.state.hidden = !this.state.hidden;
        try { localStorage.setItem(KEY, this.state.hidden ? "1" : "0"); } catch { /* the choice just is not remembered */ }
        this.apply();
        setTimeout(() => this.measure(), 0);
        window.dispatchEvent(new Event("resize"));
    }
}

registry.category("main_components").add("ei_chatter_toggle", { Component: EiChatterToggle });
