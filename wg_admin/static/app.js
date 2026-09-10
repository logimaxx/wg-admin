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

  function showQr(url, configUrl) {
    const img = $("#qr-image");
    if (img) img.src = url;
    const download = $("#qr-download");
    if (download) {
      if (configUrl) {
        download.href = configUrl;
        download.hidden = false;
      } else {
        download.hidden = true;
      }
    }
    openModal("qr-modal");
  }

  function syncExistingKey() {
    const toggle = $("[data-existing-key]");
    const fields = $("[data-existing-fields]");
    if (!toggle || !fields) return;
    fields.hidden = !toggle.checked;
    const keyInput = $('input[name="public_key"]', fields);
    if (keyInput) keyInput.required = toggle.checked;
    const psk = $('input[name="use_psk"]');
    if (psk && toggle.dataset.pskTouched !== "1") {
      psk.checked = !toggle.checked;
    }
  }

  document.addEventListener("change", (event) => {
    if (event.target.closest("[data-existing-key]")) {
      syncExistingKey();
    }
    if (event.target.closest('input[name="use_psk"]')) {
      const toggle = $("[data-existing-key]");
      if (toggle) toggle.dataset.pskTouched = "1";
    }
  });

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
      showQr(qr.dataset.qr, qr.dataset.config);
    }
    const edit = event.target.closest("[data-edit]");
    if (edit) {
      const form = $("#edit-form");
      form.action = edit.dataset.editAction;
      $("#edit-name").value = edit.dataset.editName || "";
      $("#edit-ips").value = edit.dataset.editIps || "";
      $("#edit-keepalive").value = edit.dataset.editKeepalive || "";
      $("#edit-notes").value = edit.dataset.editNotes || "";
      $("#edit-client-dns").value = edit.dataset.editClientDns || "";
      $("#edit-client-allowed").value = edit.dataset.editClientAllowed || "";
      $("#edit-client-endpoint").value = edit.dataset.editClientEndpoint || "";
      openModal("edit-peer");
    }
    const sortBtn = event.target.closest("[data-sort]");
    if (sortBtn) {
      sortPeers(sortBtn.dataset.sort);
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
  const tbody = table ? $("tbody", table) : null;
  if (tbody) {
    $$("tr[data-peer]", tbody).forEach((row, index) => {
      row.dataset.index = String(index);
    });
  }

  function rowText(row) {
    return [row.dataset.name, row.dataset.ips, row.dataset.notes, row.dataset.peer]
      .join(" ")
      .toLowerCase();
  }

  function applyFilter() {
    if (!tbody) return;
    const input = $("[data-filter-peers]");
    const needle = (input?.value || "").trim().toLowerCase();
    let visible = 0;
    $$("tr[data-peer]", tbody).forEach((row) => {
      const show = !needle || rowText(row).includes(needle);
      row.hidden = !show;
      if (show) visible += 1;
    });
    const empty = $("[data-filter-empty]");
    if (empty) empty.hidden = visible !== 0;
  }

  let sortState = { key: "", dir: 1 };
  function sortPeers(key) {
    if (!tbody) return;
    if (sortState.key === key) sortState.dir *= -1;
    else {
      sortState.key = key;
      sortState.dir = key === "name" || key === "ips" ? 1 : -1;
    }
    const rows = $$("tr[data-peer]", tbody);
    const value = (row) => {
      if (key === "handshake") return Number(row.dataset.handshakeTs || 0);
      if (key === "transfer") return Number(row.dataset.transferBytes || 0);
      if (key === "ips") return row.dataset.ips || "";
      if (key === "name") return (row.dataset.name || "").toLowerCase();
      return Number(row.dataset.index || 0);
    };
    rows.sort((a, b) => {
      const left = value(a);
      const right = value(b);
      const cmp = left < right ? -1 : left > right ? 1 : Number(a.dataset.index) - Number(b.dataset.index);
      return cmp * sortState.dir;
    });
    rows.forEach((row) => tbody.appendChild(row));
    $$("[data-sort]").forEach((btn) => btn.removeAttribute("aria-sort"));
    const active = $(`[data-sort="${key}"]`);
    if (active) active.setAttribute("aria-sort", sortState.dir === 1 ? "ascending" : "descending");
  }

  const filterInput = $("[data-filter-peers]");
  if (filterInput) {
    filterInput.addEventListener("input", applyFilter);
  }

  if (table) {
    const created = table.dataset.openQr;
    if (created) {
      const button = $$(`button[data-qr]`).find((el) => (el.dataset.qr || "").includes(`/peers/${created}/`));
      if (button) showQr(button.dataset.qr, button.dataset.config);
    }
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
          if (peer.handshake_ts !== undefined) row.dataset.handshakeTs = String(peer.handshake_ts);
          if (peer.transfer_bytes !== undefined) row.dataset.transferBytes = String(peer.transfer_bytes);
        }
      } catch {
        /* keep last painted values */
      }
    };
    setInterval(refresh, 8000);
  }
})();
