import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

// "Sign-in PIN" in the name menu: the person sets, changes or removes their own four-digit PIN. The password is asked for every time,
// nothing is kept in the browser, and the server (res.users.ei_set_pin) decides what is an acceptable PIN.
export class EiPinDialog extends Component {
    static template = "ei_pin_login.PinDialog";
    static components = { Dialog };
    props = useProps({ close: t.function() });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ loading: true, info: null, password: "", pin: "", confirm: "", error: "", busy: false, done: "" });
        onWillStart(async () => {
            this.state.info = await this.orm.call("res.users", "ei_pin_info", []);
            this.state.loading = false;
        });
    }

    get canSave() { return /^\d{4}$/.test(this.state.pin) && this.state.confirm === this.state.pin && !!this.state.password && !this.state.busy; }
    get setOnText() {
        const raw = this.state.info && this.state.info.set_on;
        const when = raw ? new Date(raw.replace(" ", "T") + "Z") : null;       // the server answers in UTC
        return when && !isNaN(when) ? when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
    }

    digits(field, ev) { this.state[field] = ev.target.value.replace(/\D/g, "").slice(0, 4); ev.target.value = this.state[field]; }

    async run(method, args, doneText) {
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.orm.call("res.users", method, [], args);
            this.state.done = doneText;
            this.state.info = await this.orm.call("res.users", "ei_pin_info", []);
            this.state.password = this.state.pin = this.state.confirm = "";
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || _t("That did not work. Nothing was changed.");
        } finally {
            this.state.busy = false;
        }
    }

    save() { if (this.canSave) { return this.run("ei_set_pin", { password: this.state.password, pin: this.state.pin, confirm: this.state.confirm }, _t("Your PIN is saved. On the sign-in page, choose the PIN tab, type your user name and the four digits.")); } }
    remove() { if (this.state.password && !this.state.busy) { return this.run("ei_remove_pin", { password: this.state.password }, _t("Your PIN is removed. Sign in with your password.")); } else { this.state.error = _t("Type your password first."); } }
}

registry.category("user_menuitems").add("ei_pin", function eiPinItem() {
    const dialog = useService("dialog");
    return {
        type: "item",
        id: "ei_pin",
        description: _t("Sign-in PIN"),
        hide: !session.ei_pin_allowed,
        callback: () => dialog.add(EiPinDialog, {}),
        sequence: 52,
    };
});
