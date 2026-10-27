import { Component, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// Approval evidence: an approve / verify / sign / post button on a record first opens a dialog with what is being approved, who prepared it,
// what changed since and by whom, the attached documents, what the approval will do, and whether this person may do it. Nothing happens
// until "Approve" (or the button's own word) is pressed in the dialog; Cancel or Escape leaves the record exactly as it was. The server
// (ei.approval.evidence) decides which buttons these are and what is shown; the approval itself still enforces every rule.
export class EiApprovalDialog extends Component {
    static template = "ei_app_shell.ApprovalDialog";
    static components = { Dialog };
    props = useProps({ ev: t.object(), onConfirm: t.function(), close: t.function() });

    get ev() { return this.props.ev; }
    confirm() {
        if (this.ev.blocked) { return; }
        this.props.onConfirm();
        this.props.close();
    }
}

let buttons = null;                 // {model: [methods]}: asked once per page load

patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const proceed = await super.beforeExecuteActionButton(...arguments);
        if (proceed === false || clickParams.type !== "object" || clickParams.special || this.env.inDialog) { return proceed; }
        const rec = this.model.root;
        if (!rec || !rec.resId) { return proceed; }
        buttons = buttons || this.orm.call("ei.approval.evidence", "approval_buttons", []).catch(() => ({}));
        const map = await buttons;
        if (!(map[rec.resModel] || []).includes(clickParams.name)) { return proceed; }
        let ev = null;
        try {
            ev = await this.orm.call("ei.approval.evidence", "get_evidence", [rec.resModel, rec.resId, clickParams.name]);
        } catch {
            return proceed;                 // the evidence could not be read: the server's own checks still apply to the button
        }
        if (!ev) { return proceed; }
        return new Promise((resolve) => {
            let confirmed = false;
            this.dialogService.add(EiApprovalDialog, { ev, onConfirm: () => { confirmed = true; resolve(proceed); } }, { onClose: () => { if (!confirmed) { resolve(false); } } });
        });
    },
});
