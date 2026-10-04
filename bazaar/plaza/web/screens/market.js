// market: placeholder until fork F3 builds it (CONTRACT.md, section 4).
Plaza.screen("market", {
  title: "nav.market",
  render(root) {
    root.appendChild(K.pageHead(t("nav.market")));
    root.appendChild(K.state("empty", t("shell.soon"), "market"));
  },
});
