import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onPatched, onWillStart, proxy, useProps } from "@odoo/owl";

const MODEL = "ei.assistant";
const NUMBER = /^(?:[A-Za-z.$]{0,4}\s?)?-?[\d,]+(?:\.\d+)?(?:\s?MTL)?$/;

export class EiAssistant extends Component {
    static template = "ei_assistant.Assistant";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ starters: [], messages: [], input: "", busy: false });
        this.nextId = 1;
        this.stick = false;
        onWillStart(async () => {
            try {
                this.state.starters = await this.orm.call(MODEL, "starters", []);
            } catch {
                this.state.starters = [];
            }
        });
        onMounted(() => this.focusInput());
        onPatched(() => {
            if (this.stick) {
                this.stick = false;
                const log = document.getElementById("ei-ask-log");
                if (log) { log.scrollTop = log.scrollHeight; }
                this.focusInput();
            }
        });
    }

    focusInput() {
        const box = document.getElementById("ei-ask-q");
        if (box) { box.focus(); }
    }
    isNumber(cell) { return NUMBER.test(String(cell).trim()); }
    onInput(ev) { this.state.input = ev.target.value; }
    async onSubmit() {
        const text = this.state.input.trim();
        if (!text || this.state.busy) { return; }
        this.state.input = "";
        await this.ask(text);
    }
    push(message) {
        this.state.messages.push({ id: this.nextId++, ...message });
        this.stick = true;
    }
    async ask(text) {
        this.push({ who: "me", text });
        await this.call(() => this.orm.call(MODEL, "ask", [text]));
    }
    async pickParty(option) {
        this.push({ who: "me", text: option.label });
        await this.call(() => this.orm.call(MODEL, "ask_party", [option.party_id]));
    }
    async call(fn) {
        this.state.busy = true;
        try {
            this.push({ who: "bot", reply: await fn(), error: "" });
        } catch (e) {
            this.push({ who: "bot", reply: null, error: (e && e.data && e.data.message) || "Something went wrong. Nothing was changed." });
        }
        this.state.busy = false;
    }
    async openSource(message, index) {
        if (index === null || index === undefined) { return; }
        message.openError = "";
        try {
            const act = await this.orm.call(MODEL, "open_source", [message.reply.sources[index]]);
            if (act) { await this.action.doAction(act); }
        } catch (e) {
            message.openError = (e && e.data && e.data.message) || "Your role cannot open that.";
        }
    }
    clear() { this.state.messages = []; this.focusInput(); }
}
registry.category("actions").add("ei_assistant", EiAssistant);

// A button in the top bar, on every screen
export class EiAskButton extends Component {
    static template = "ei_assistant.AskButton";
    setup() { this.action = useService("action"); }
    open() { return this.action.doAction("ei_assistant.action_ei_assistant"); }
}
registry.category("systray").add("ei_assistant.ask", { Component: EiAskButton }, { sequence: 2 });
