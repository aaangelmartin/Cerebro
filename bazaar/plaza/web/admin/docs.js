// admin docs: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("docs", {
  title: "nav.admin.docs",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.docs")));
    root.appendChild(K.state("empty", t("shell.soon"), "docs"));
  },
});
