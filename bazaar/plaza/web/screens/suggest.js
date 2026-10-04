// suggest: placeholder until fork F3 builds it (CONTRACT.md, section 4).
Plaza.screen("suggest", {
  title: "nav.suggest", needsTeam: true,
  render(root) {
    root.appendChild(K.pageHead(t("nav.suggest")));
    root.appendChild(K.state("empty", t("shell.soon"), "suggest"));
  },
});
