// offers: placeholder until fork F2 builds it (CONTRACT.md, section 4).
Plaza.screen("offers", {
  title: "nav.offers", needsTeam: true,
  render(root) {
    root.appendChild(K.pageHead(t("nav.offers")));
    root.appendChild(K.state("empty", t("shell.soon"), "offers"));
  },
});
