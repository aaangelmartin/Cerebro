// settings: placeholder until fork F3 builds it (CONTRACT.md, section 4).
Plaza.screen("settings", {
  title: "nav.settings", needsTeam: true,
  render(root) {
    root.appendChild(K.pageHead(t("nav.settings")));
    root.appendChild(K.state("empty", t("shell.soon"), "settings"));
  },
});
