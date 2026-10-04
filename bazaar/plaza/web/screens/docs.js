// docs: placeholder until fork F3 builds it (CONTRACT.md, section 4).
Plaza.screen("docs", {
  title: "nav.docs",
  render(root) {
    root.appendChild(K.pageHead(t("nav.docs")));
    root.appendChild(K.state("empty", t("shell.soon"), "docs"));
  },
});
