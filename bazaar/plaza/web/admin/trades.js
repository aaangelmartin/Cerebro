// admin trades: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("trades", {
  title: "nav.admin.trades",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.trades")));
    root.appendChild(K.state("empty", t("shell.soon"), "trades"));
  },
});
