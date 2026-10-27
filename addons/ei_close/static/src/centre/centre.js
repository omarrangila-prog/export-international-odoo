import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

// Reconciliation centre: every reconciliation on one page (R1-R10 and the close). Read-only; `ei.recon.centre` decides what each person
// may see and works out every figure. Each card opens the records behind it.
const fmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const LABEL = { attention: "Needs attention", ok: "Agrees", blocked: "Waiting on others" };

export class EiReconCentre extends Component {
    static template = "ei_close.ReconCentre";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ loading: true, error: "", data: null, open: "" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call("ei.recon.centre", "get_overview", []);
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || "The reconciliations could not be loaded. Nothing was changed.";
        }
        this.state.loading = false;
    }

    label(s) { return LABEL[s] || s; }
    value(f) { return f.money ? fmt.format(f.value || 0) : f.value; }
    money(v) { return v === null || v === undefined ? "-" : fmt.format(v); }
    toggle(key) { this.state.open = this.state.open === key ? "" : key; }
    openCard(c) { if (c.action) { this.action.doAction(c.action); } }
}

registry.category("actions").add("ei_recon_centre", EiReconCentre);
