// Sign-in page: the Password / PIN switch. Without this script the page is Odoo's ordinary password form.
// Only one of the two secret fields is ever sent (the other one is disabled) and the hidden `type` says which it is.
(function () {
    const KEY = "ei.login.mode";
    function remembered() { try { return window.localStorage.getItem(KEY); } catch { return null; } }
    function remember(mode) { try { window.localStorage.setItem(KEY, mode); } catch { /* private window: the choice simply is not kept */ } }

    function init() {
        const tabs = document.querySelector(".ei-login-tabs");
        const form = tabs && tabs.closest("form");
        if (!form) { return; }
        const passwordBox = form.querySelector(".o_caps_lock_warning");
        const password = form.querySelector("#password");
        const pinBox = form.querySelector(".ei-pin-field");
        const pin = form.querySelector("#ei_pin");
        const type = form.querySelector("input[name=type]");
        const login = form.querySelector("#login");
        if (!passwordBox || !password || !pinBox || !pin || !type) { return; }

        function apply(mode, focus) {
            const usePin = mode === "pin";
            passwordBox.classList.toggle("d-none", usePin);
            pinBox.classList.toggle("d-none", !usePin);
            password.disabled = usePin;
            password.required = !usePin;
            pin.disabled = !usePin;
            pin.required = usePin;
            type.value = usePin ? "ei_pin" : "password";
            form.dataset.eiMode = mode;
            for (const b of tabs.querySelectorAll(".ei-login-tab")) { b.setAttribute("aria-pressed", String(b.dataset.mode === mode)); }
            if (focus) { (login && !login.value ? login : usePin ? pin : password).focus(); }
        }

        const fromQuery = new URLSearchParams(window.location.search).get("mode") === "pin" ? "pin" : null;
        apply(tabs.dataset.serverMode === "pin" ? "pin" : fromQuery || remembered() || "password", false);
        for (const b of tabs.querySelectorAll(".ei-login-tab")) {
            b.addEventListener("click", () => { remember(b.dataset.mode); apply(b.dataset.mode, true); });
        }
        pin.addEventListener("input", () => { pin.value = pin.value.replace(/\D/g, "").slice(0, 4); });
    }

    if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})();
