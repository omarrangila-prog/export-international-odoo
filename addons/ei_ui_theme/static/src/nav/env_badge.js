import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

// A pill in the top bar when this is not the live system. The label comes from the System Parameter `ei.environment_label`.
export class EiEnvBadge extends Component {
    static template = "ei_ui_theme.EnvBadge";
    get label() { return session.ei_environment_label || ""; }
    get short() { return this.label.split(/\s+[-\u2013]\s+/)[0]; }          // "STAGING - synthetic demo data" -> "STAGING" on a phone
}

registry.category("systray").add("ei_env_badge", { Component: EiEnvBadge, isDisplayed: () => !!session.ei_environment_label }, { sequence: 1 });
