import { Component, onMounted, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { Record } from "@web/model/relational_model/record";

// Undo / redo of edits on a record, like a spreadsheet: the arrows beside the save controls and Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) when the
// cursor is not inside a text box (inside one, the browser's own undo of the typing is left alone).
// What it undoes: edits to the record's own fields (text, numbers, dates, choices, links to another record), one step at a time, as many
// as were made on this record in this visit. An undo is just another edit: it is saved by the normal rules, so it needs the same right to
// write, a locked or approved record refuses it like any other change, and the record's history shows both. What it does NOT do: add,
// remove or reorder lines (those are one click away: Discard), or reverse a business action (approve, post, pay): those have their own
// reversal with a reason and a second person.
const SIMPLE = new Set(["char", "text", "integer", "float", "monetary", "boolean", "date", "datetime", "selection", "many2one"]);
const MAX_STEPS = 100;
const histories = new WeakMap();
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function historyFor(record) {
    let h = histories.get(record);
    if (!h || h.resId !== record.resId) {            // another record: a fresh history
        h = { resId: record.resId, undo: [], redo: [], busy: false, bus: proxy({ n: 0 }) };
        histories.set(record, h);
    }
    return h;
}

patch(Record.prototype, {
    update(changes, ...rest) {
        try {
            if (this.model && this.model.root === this && this.resModel) {
                const h = historyFor(this);
                if (!h.busy) {
                    const before = {}, after = {};
                    for (const [name, value] of Object.entries(changes || {})) {
                        const type = this.fields[name] && this.fields[name].type;
                        if (SIMPLE.has(type) && !same(this.data[name], value)) { before[name] = this.data[name]; after[name] = value; }
                    }
                    if (Object.keys(after).length) {
                        h.undo.push({ before, after });
                        if (h.undo.length > MAX_STEPS) { h.undo.shift(); }
                        h.redo.length = 0;
                        h.bus.n++;
                    }
                }
            }
        } catch {
            /* never let the history get in the way of an edit */
        }
        return super.update(changes, ...rest);
    },
    discard(...args) {
        const h = histories.get(this);
        if (h) { h.undo.length = 0; h.redo.length = 0; h.bus.n++; }         // Discard throws the edits away: there is nothing left to undo
        return super.discard(...args);
    },
});

const ICON_UNDO = "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 010 11H11";
const ICON_REDO = "M15 14l5-5-5-5M20 9H9.5a5.5 5.5 0 000 11H13";

export class EiUndoRedo extends Component {
    static template = "ei_app_shell.UndoRedo";
    props = useProps({ model: t.any() });

    setup() {
        this.onKey = (ev) => this.handleKey(ev);
        onMounted(() => document.addEventListener("keydown", this.onKey));
        onWillUnmount(() => document.removeEventListener("keydown", this.onKey));
    }

    get hist() { const root = this.props.model.root; return root ? historyFor(root) : null; }
    get canUndo() { const h = this.hist; if (h) { h.bus.n; } return !!h && h.undo.length > 0 && !h.busy; }
    get canRedo() { const h = this.hist; if (h) { h.bus.n; } return !!h && h.redo.length > 0 && !h.busy; }
    get iconUndo() { return ICON_UNDO; }
    get iconRedo() { return ICON_REDO; }
    get undoTip() { const h = this.hist; return h && h.undo.length ? this.describe(h.undo.at(-1), "Undo") : "Nothing to undo"; }
    get redoTip() { const h = this.hist; return h && h.redo.length ? this.describe(h.redo.at(-1), "Redo") : "Nothing to redo"; }
    describe(step, verb) {
        const labels = Object.keys(step.after).map((n) => (this.props.model.root.fields[n] || {}).string || n);
        return `${verb}: ${labels.slice(0, 3).join(", ")}${labels.length > 3 ? "..." : ""}`;
    }

    async step(from, to, key) {
        const root = this.props.model.root, h = this.hist;
        if (!root || !h || !from.length || h.busy) { return; }
        const entry = from.pop();
        h.busy = true;
        try {
            await root.update(entry[key]);
            to.push(entry);
        } catch {
            from.push(entry);                  // the record refused it (locked, invalid): the step stays where it was
        } finally {
            h.busy = false;
            h.bus.n++;
        }
    }
    undo() { const h = this.hist; return h && this.step(h.undo, h.redo, "before"); }
    redo() { const h = this.hist; return h && this.step(h.redo, h.undo, "after"); }

    handleKey(ev) {
        if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) { return; }
        const k = ev.key.toLowerCase();
        if (k !== "z" && k !== "y") { return; }
        const el = ev.target;
        if (el && el.closest && el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true'], .o_field_html")) { return; }       // typing: the browser undoes the typing
        if (document.querySelector(".modal.show, .o_dialog")) { return; }
        ev.preventDefault();
        if (k === "y" || ev.shiftKey) { this.redo(); } else { this.undo(); }
    }
}

patch(FormController, { components: { ...FormController.components, EiUndoRedo } });
