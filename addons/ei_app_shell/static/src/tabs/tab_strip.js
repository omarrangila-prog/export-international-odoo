import { Component, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { WebClient } from "@web/webclient/webclient";

const WIDE = "(min-width: 768px)";

export class EiTabStrip extends Component {
    static template = "ei_app_shell.TabStrip";

    setup() {
        this.tabs = useService("ei_tabs");
        this.mq = window.matchMedia(WIDE);
        this.state = proxy({ wide: this.mq.matches });
        this.onMq = () => { this.state.wide = this.mq.matches; };
        onMounted(() => this.mq.addEventListener("change", this.onMq));
        onWillUnmount(() => this.mq.removeEventListener("change", this.onMq));
    }

    get show() { return this.state.wide && this.tabs.tabs.length > 0; }

    onAux(ev, tab) {                      // middle click closes, as in a browser
        if (ev.button === 1) { ev.preventDefault(); this.tabs.close(tab.id); }
    }
    onKeydown(ev, tab) {
        const all = this.tabs.tabs, i = all.findIndex((t) => t.id === tab.id);
        const focus = (n) => { const els = ev.currentTarget.closest(".ei-tabs").querySelectorAll(".ei-tab-link"); els[(n + els.length) % els.length].focus(); };
        if (ev.key === "ArrowRight") { ev.preventDefault(); focus(i + 1); }
        else if (ev.key === "ArrowLeft") { ev.preventDefault(); focus(i - 1); }
        else if (ev.key === "Delete") { ev.preventDefault(); this.tabs.close(tab.id); }
    }
}

patch(WebClient, { components: { ...WebClient.components, EiTabStrip } });
