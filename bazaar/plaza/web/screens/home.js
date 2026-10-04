// home: placeholder until fork F2 builds it (CONTRACT.md, section 4).
Plaza.screen("home", {
  title: "nav.home", needsTeam: true,
  render(root) {
    root.appendChild(K.pageHead(t("nav.home")));
    root.appendChild(K.state("empty", t("shell.soon"), "home"));
  },
});
