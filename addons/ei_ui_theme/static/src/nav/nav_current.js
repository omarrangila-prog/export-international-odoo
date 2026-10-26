import { onMounted, onPatched, useListener } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

// Odoo does not mark which top-bar entry is the one you are in. The bar shows it (a filled pill, like the Overview
// design), so the entry that holds the open screen is marked here: aria-current tells screen readers the same thing.
function opensAction(menu, actionId) {
    return menu.actionID === actionId || (menu.childrenTree || []).some((child) => opensAction(child, actionId));
}

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        const mark = () => this.eiMarkCurrent();
        onMounted(mark);
        onPatched(mark);
        useListener(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => setTimeout(mark, 0));
    },
    eiMarkCurrent() {
        const root = document.querySelector(".o_main_navbar");
        const action = this.actionService.currentController && this.actionService.currentController.action;
        if (!root) { return; }
        root.querySelectorAll("[aria-current]").forEach((el) => el.removeAttribute("aria-current"));
        if (!action || !this.currentApp) { return; }
        const section = this.currentAppSections.find((s) => opensAction(s, action.id));
        const el = section && root.querySelector(`[data-section="${section.id}"]`);
        const target = el && el.closest("a, button");
        if (target) { target.setAttribute("aria-current", "page"); }
    },
});
