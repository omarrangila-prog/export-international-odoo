import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

// Stroke icons (24x24). Odoo 20 does not style Font Awesome, so icons are drawn inline.
const PATHS = {
    bank: "M3 21h18M5 21V10M9 21V10M15 21V10M19 21V10M2 10l10-7 10 7",
    cash: "M2 6h20v12H2zM12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5M6 12h.01M18 12h.01",
    doc: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h7M9 17h7",
    truck: "M1 6h13v10H1zM14 10h5l3 3v3h-8zM6 19.5a2 2 0 100-4 2 2 0 000 4M18 19.5a2 2 0 100-4 2 2 0 000 4",
    scale: "M12 3v18M6 21h12M4 7h16M4 7l-2.5 6a3.2 3.2 0 005 0zM20 7l-2.5 6a3.2 3.2 0 005 0z",
    inbox: "M3 13l3-8h12l3 8v6H3zM3 13h5a4 4 0 008 0h5",
    check: "M5 12.5l4.5 4.5L19 7",
    alert: "M12 3l10 18H2zM12 10v5M12 18v.01",
    upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
    chart: "M3 20h18M5 16l4-5 4 3 6-8",
    down: "M12 4v14M6 13l6 6 6-6",
    up: "M12 20V6M6 11l6-6 6 6",
    refresh: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
    tags: "M3 12V3h9l9 9-9 9zM7.5 7.5v.01",
    chevron: "M9 6l6 6-6 6",
    clip: "M9 3h6v3H9zM6 5H5v16h14V5h-1M9 14l2 2 4-4",
    send: "M22 2L11 13M22 2l-7 20-4-9-9-4z",
    list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    circle: "M12 3a9 9 0 100 18 9 9 0 000-18",
};
const ICON_MAP = {
    "fa-university": "bank", "fa-check-square-o": "clip", "fa-paper-plane-o": "send", "fa-money": "cash",
    "fa-file-text-o": "doc", "fa-truck": "truck", "fa-list-alt": "list", "fa-balance-scale": "scale",
    "fa-exclamation-triangle": "alert", "fa-file-o": "doc", "fa-tags": "tags", "fa-upload": "upload",
    "fa-inbox": "inbox", "fa-arrow-circle-down": "down", "fa-arrow-circle-up": "up", "fa-line-chart": "chart",
    "fa-check": "check", "fa-circle-o": "circle", "fa-refresh": "refresh", "fa-angle-right": "chevron",
};

export class EiHome extends Component {
    static template = "ei_ui_theme.Home";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ loading: true, data: null, error: false });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("ei.home", "get_data", []);
            this.state.error = false;
        } catch (e) {
            this.state.error = true;
        }
        this.state.loading = false;
    }

    async open(method, key) {
        const act = await this.orm.call("ei.home", method, [key]);
        if (act) {
            await this.action.doAction(act);
        }
    }

    icon(name) { return PATHS[ICON_MAP[name] || name] || PATHS.circle; }

    onTask(key) { return this.open("open_task", key); }
    onQuick(key) { return this.open("open_quick", key); }
    onMoney(key) { return this.open("open_money", key); }
    onStep(key) { return this.open("open_step", key); }
    onRefresh() { return this.load(); }
}

registry.category("actions").add("ei_home", EiHome);
