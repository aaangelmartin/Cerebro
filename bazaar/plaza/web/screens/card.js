// card: placeholder until fork F3 builds it (CONTRACT.md, section 4).
Plaza.screen("card", {
  title: "nav.card",
  render(root) {
    root.appendChild(K.pageHead(t("nav.card")));
    root.appendChild(K.state("empty", t("shell.soon"), "card"));
  },
});
