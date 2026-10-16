(function initActionMenus(global) {
  function bind(root = document) {
    const menus = () => [...root.querySelectorAll("details.action-menu")];
    const summary = (menu) => menu.querySelector("summary");
    const buttons = (menu) => [...menu.querySelectorAll(".action-menu-items button:not(:disabled):not([hidden])")];
    function position(menu) {
      const panel = menu.querySelector(".action-menu-items");
      if (!panel) return;
      panel.style.transform = "";
      panel.style.top = "";
      panel.style.bottom = "";
      const bounds = panel.getBoundingClientRect();
      const width = root.documentElement.clientWidth;
      const offset = Math.max(8 - bounds.left, Math.min(0, width - 8 - bounds.right));
      panel.style.transform = `translateX(${offset}px)`;
      const trigger = summary(menu).getBoundingClientRect();
      if (bounds.bottom > global.innerHeight - 8 && trigger.top > bounds.height + 8) {
        panel.style.top = "auto";
        panel.style.bottom = "calc(100% + 4px)";
      }
    }
    root.addEventListener("toggle", (event) => {
      const menu = event.target;
      if (!menu.matches?.("details.action-menu")) return;
      summary(menu).setAttribute("aria-expanded", String(menu.open));
      if (!menu.open) return;
      menus().forEach((other) => { if (other !== menu) other.open = false; });
      position(menu);
    }, true);
    root.addEventListener("click", (event) => {
      const menu = event.target.closest?.("details.action-menu");
      menus().forEach((other) => {
        if (other !== menu || event.target.closest(".action-menu-items button")) other.open = false;
      });
    });
    root.addEventListener("keydown", (event) => {
      const menu = event.target.closest?.("details.action-menu");
      if (event.key === "Escape") {
        const opened = menus().find((item) => item.open);
        if (opened) { event.preventDefault(); opened.open = false; summary(opened).focus(); }
        return;
      }
      if (!menu || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      menu.open = true;
      const items = buttons(menu).filter((button) => button.getClientRects().length);
      if (!items.length) return;
      const index = items.indexOf(root.activeElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
        : event.key === "ArrowUp" ? (index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length) : (index + 1) % items.length;
      items[next].focus();
    });
    global.addEventListener("resize", () => menus().filter((menu) => menu.open).forEach(position));
    menus().forEach((menu) => summary(menu).setAttribute("aria-expanded", String(menu.open)));
  }
  global.FicFrameActionMenus = { bind };
})(window);
