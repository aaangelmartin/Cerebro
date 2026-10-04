// admin performance: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("performance", {
  title: "nav.admin.performance",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.performance")));
    root.appendChild(K.state("empty", t("shell.soon"), "performance"));
  },
});
