import { Component, onMounted, onWillUnmount, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// Documents beside the record: a "Documents" button on a record that has attachments opens them in a panel on the right while the record
// stays on the left, so a checker compares the scanned contract, gate pass or supplier PDF with what was typed, without downloading. On a
// phone the panel covers the screen and Close returns to the record. PDFs and pictures are shown; anything else can be downloaded.
export class EiDocViewer extends Component {
    static template = "ei_app_shell.DocViewer";
    props = useProps({ record: t.any() });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ docs: [], open: false, index: 0, key: "", top: 76 });
        this.onKey = (ev) => { if (ev.key === "Escape" && this.state.open && !document.querySelector(".modal.show, .o_dialog")) { this.close(); } };
        onMounted(() => { document.addEventListener("keydown", this.onKey); this.load(this.props.record); });
        onWillUpdateProps((next) => this.load(next.record));
        onWillUnmount(() => { document.removeEventListener("keydown", this.onKey); document.body.classList.remove("ei-docview-open"); });
    }

    async load(record, again = false) {
        const key = record && record.resId ? `${record.resModel}:${record.resId}` : "";
        if (key === this.state.key && !again) { return; }
        this.state.key = key;
        this.state.index = 0;
        if (!key) { this.state.docs = []; this.close(); return; }
        try {
            const docs = await this.orm.call("ei.documents", "list_for", [record.resModel, record.resId]);
            if (this.state.key === key) { this.state.docs = docs; if (!docs.length) { this.close(); } }
        } catch {
            this.state.docs = [];
        }
    }

    get doc() { return this.state.docs[this.state.index] || null; }
    async toggle() {
        if (this.state.open) { this.close(); return; }
        const cp = document.querySelector(".o_action_manager > .o_form_view .o_control_panel") || document.querySelector(".o_action_manager");
        this.state.top = cp ? Math.max(0, Math.round(cp.getBoundingClientRect()[cp.classList.contains("o_control_panel") ? "bottom" : "top"])) : 76;   // under the record's own controls
        this.state.open = true;
        document.body.classList.add("ei-docview-open");
        await this.load(this.props.record, true);                 // a document added in the chatter since the record opened is listed too
    }
    close() { this.state.open = false; document.body.classList.remove("ei-docview-open"); }
    show(i) { this.state.index = i; }
    step(d) { const n = this.state.docs.length; if (n) { this.state.index = (this.state.index + d + n) % n; } }
    size(b) { return b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`; }
}

patch(FormController, { components: { ...FormController.components, EiDocViewer } });
