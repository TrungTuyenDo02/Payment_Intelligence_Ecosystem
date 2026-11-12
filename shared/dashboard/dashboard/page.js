(() => {
  "use strict";
  // Tabs: the URL hash keeps the open tab (bookmarkable); without JS every panel is visible.
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const panels = [...document.querySelectorAll('[role="tabpanel"]')];
  function show(id) {
    if (!panels.some((p) => p.dataset.tab === id)) id = panels[0].dataset.tab;
    tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === id)));
    panels.forEach((p) => { p.hidden = p.dataset.tab !== id; });
  }
  tabs.forEach((t) => t.addEventListener("click", () => {
    history.replaceState(null, "", "#" + t.dataset.tab);
    show(t.dataset.tab);
    window.scrollTo({ top: 0 });
  }));
  show(location.hash.slice(1));

  // Theme toggle (light/dark); remembered per browser when storage is available.
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem("pie-theme");
    if (saved) root.dataset.theme = saved;
  } catch (e) { /* storage unavailable: follow the OS setting */ }
  document.querySelector(".theme").addEventListener("click", () => {
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("pie-theme", root.dataset.theme); } catch (e) { /* ignore */ }
  });

  // Tooltip for every mark with data-tip; crosshair on line charts.
  const tip = document.querySelector(".tooltip");
  let cross = null;
  function place(ev) {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  document.addEventListener("pointerover", (ev) => {
    const el = ev.target.closest && ev.target.closest("[data-tip]");
    if (!el) return;
    tip.innerHTML = el.dataset.tip;
    tip.hidden = false;
    place(ev);
    if (el.dataset.cx) {
      cross = el.ownerSVGElement.querySelector(".crosshair");
      cross.setAttribute("x1", el.dataset.cx);
      cross.setAttribute("x2", el.dataset.cx);
      cross.style.visibility = "visible";
    }
  });
  document.addEventListener("pointermove", (ev) => { if (!tip.hidden) place(ev); });
  document.addEventListener("pointerout", (ev) => {
    const el = ev.target.closest && ev.target.closest("[data-tip]");
    if (!el) return;
    tip.hidden = true;
    if (cross) { cross.style.visibility = "hidden"; cross = null; }
  });
})();
