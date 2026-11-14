// Load before styles so workspace and operations keep the same appearance on navigation.
(() => {
  const key = "agent-dairy-theme:" + new URL(".", document.baseURI).pathname;
  function apply(theme) {
    const value = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = value;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content",
      value === "dark" ? "#0b1626" : "#0b2440");
    try { localStorage.setItem(key, value); } catch {}
  }
  let saved;
  try { saved = localStorage.getItem(key); } catch {}
  apply(saved);
  window.portalTheme = {apply};
})();
