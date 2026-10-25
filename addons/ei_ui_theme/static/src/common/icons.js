// Stroke icons (24x24). Odoo 20 does not style Font Awesome, so every icon is drawn inline and marked aria-hidden.
export const ICON_PATHS = {
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
    in: "M12 4v14M6 13l6 6 6-6",
    out: "M12 20V6M6 11l6-6 6 6",
    refresh: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
    tags: "M3 12V3h9l9 9-9 9zM7.5 7.5v.01",
    chevron: "M9 6l6 6-6 6",
    clip: "M9 3h6v3H9zM6 5H5v16h14V5h-1M9 14l2 2 4-4",
    send: "M22 2L11 13M22 2l-7 20-4-9-9-4z",
    list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    circle: "M12 3a9 9 0 100 18 9 9 0 000-18",
    search: "M11 4a7 7 0 100 14 7 7 0 000-14M21 21l-4.5-4.5",
    bell: "M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 004 0",
    moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
    sun: "M12 8a4 4 0 100 8 4 4 0 000-8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
    dots: "M5 12h.01M12 12h.01M19 12h.01",
    user: "M12 12a4 4 0 100-8 4 4 0 000 8M4 21a8 8 0 0116 0",
    party: "M17 20v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M10 11a4 4 0 100-8 4 4 0 000 8M21 20v-1a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8",
    code: "M8 6l-6 6 6 6M16 6l6 6-6 6",
    invoice: "M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2zM9 8h6M9 12h6",
    bill: "M6 2h9l5 5v15H6zM14 2v6h6M9 12h6M9 16h4",
    statement: "M4 4h16v16H4zM4 9h16M9 9v11",
    shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
    snooze: "M12 7v5l3 2M12 3a9 9 0 100 18 9 9 0 000-18",
    flag: "M5 21V4M5 4h11l-2 4 2 4H5",
};
// icon names used by the server (Font Awesome style) -> our names
export const ICON_ALIAS = {
    "fa-university": "bank", "fa-check-square-o": "clip", "fa-paper-plane-o": "send", "fa-money": "cash", "fa-file-text-o": "doc",
    "fa-truck": "truck", "fa-list-alt": "list", "fa-balance-scale": "scale", "fa-exclamation-triangle": "alert", "fa-file-o": "doc",
    "fa-tags": "tags", "fa-upload": "upload", "fa-inbox": "inbox", "fa-arrow-circle-down": "in", "fa-arrow-circle-up": "out",
    "fa-line-chart": "chart", "fa-check": "check", "fa-circle-o": "circle", "fa-refresh": "refresh", "fa-angle-right": "chevron",
};
export function iconPath(name) {
    return ICON_PATHS[ICON_ALIAS[name] || name] || ICON_PATHS.circle;
}
