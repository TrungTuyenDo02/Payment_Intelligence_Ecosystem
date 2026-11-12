(() => {
  "use strict";
  // Sidebar: highlight the link of the section in view (the page is one scrolling page).
  const links = [...document.querySelectorAll(".side-nav a")];
  const targets = links.map((a) => document.getElementById(a.hash.slice(1))).filter(Boolean);
  function mark() {
    let current = targets[0];
    for (const t of targets) if (t.getBoundingClientRect().top < 120) current = t;
    links.forEach((a) => a.classList.toggle("active", current && a.hash === "#" + current.id));
  }
  addEventListener("scroll", mark, { passive: true });
  mark();

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

  // Tooltip for every element with data-tip; crosshair on line charts.
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
