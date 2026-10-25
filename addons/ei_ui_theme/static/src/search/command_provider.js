import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Odoo's own Ctrl+K palette gets our permission-aware search on every screen. Results arrive already filtered
// server-side; the palette only shows them.
registry.category("command_categories").add("ei_search", {}, { sequence: 35 });
registry.category("command_provider").add("ei_search", {
    async provide(options) {
        const q = (options.searchValue || "").trim();
        if (q.length < 2) {
            return [];
        }
        const orm = useService("orm");
        const action = useService("action");
        let res;
        try {
            res = await orm.call("ei.search", "search", [q]);
        } catch {
            return [];
        }
        return res.groups.flatMap((g) =>
            g.hits.map((h) => ({
                name: `${g.label}: ${h.title}${h.subtitle ? " - " + h.subtitle : ""}`,
                category: "ei_search",
                async action() {
                    const act = await orm.call("ei.search", "open", [h.model, h.res_id]);
                    if (act) {
                        await action.doAction(act);
                    }
                },
            }))
        );
    },
});
