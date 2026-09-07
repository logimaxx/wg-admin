(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const THEME_KEY = "wg-admin-theme";

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function storedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      if (value === "light" || value === "dark") return value;
    } catch {
      /* private mode */
    }
    return null;
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }
  function syncThemeToggle() {
    const button = $("[data-theme-toggle]");
    if (!button) return;
    const next = currentTheme() === "dark" ? "light" : "dark";
    const label = `Switch to ${next} mode`;
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  }
  function applyTheme(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    if (persist) {
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch {
        /* private mode */
      }
    }
    syncThemeToggle();
  }

  applyTheme(storedTheme() || systemTheme(), false);
  const media = window.matchMedia("(prefers-color-scheme: light)");
  const onSystemTheme = () => {
    if (!storedTheme()) applyTheme(systemTheme(), false);
  };
  if (media.addEventListener) media.addEventListener("change", onSystemTheme);
  else media.addListener(onSystemTheme);

  function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.hidden = false;
  }
  function closeModals() {
    $$(".modal").forEach((el) => {
      el.hidden = true;
    });
  }

  document.addEventListener("click", (event) => {
    const themeToggle = event.target.closest("[data-theme-toggle]");
    if (themeToggle) {
      applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
      return;
    }
    const open = event.target.closest("[data-open]");
    if (open) {
      openModal(open.dataset.open);
      return;
    }
    if (event.target.closest("[data-close]") || event.target.classList.contains("modal")) {
      closeModals();
    }
    const copy = event.target.closest("[data-copy]");
    if (copy) {
      navigator.clipboard.writeText(copy.dataset.copy).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => {
          copy.textContent = "Copy";
        }, 1200);
      });
    }
    const qr = event.target.closest("[data-qr]");
    if (qr) {
      const img = $("#qr-image");
      if (img) img.src = qr.dataset.qr;
      openModal("qr-modal");
    }
    const edit = event.target.closest("[data-edit]");
    if (edit) {
      const form = $("#edit-form");
      form.action = edit.dataset.editAction;
      $("#edit-name").value = edit.dataset.editName || "";
      $("#edit-ips").value = edit.dataset.editIps || "";
      $("#edit-keepalive").value = edit.dataset.editKeepalive || "";
      $("#edit-notes").value = edit.dataset.editNotes || "";
      openModal("edit-peer");
    }
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModals();
  });

  const table = $("table[data-status-url]");
  if (table) {
    const refresh = async () => {
      try {
        const res = await fetch(table.dataset.statusUrl, { headers: { Accept: "application/json" } });
        if (!res.ok) return;
        const data = await res.json();
        for (const peer of data.peers || []) {
          const row = table.querySelector(`tr[data-peer="${CSS.escape(peer.public_key)}"]`);
          if (!row) continue;
          const led = $("[data-led]", row);
          if (led) led.className = `led ${peer.handshake_class}`;
          const handshake = $("[data-handshake]", row);
          if (handshake) handshake.textContent = peer.handshake;
          const transfer = $("[data-transfer]", row);
          if (transfer) transfer.textContent = peer.transfer;
          const endpoint = $("[data-endpoint]", row);
          if (endpoint) endpoint.textContent = peer.endpoint;
        }
      } catch {
        /* keep last painted values */
      }
    };
    setInterval(refresh, 8000);
  }
})();
