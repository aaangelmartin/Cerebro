// admin teams: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("teams", {
  title: "nav.admin.teams",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.teams")));
    root.appendChild(K.state("empty", t("shell.soon"), "teams"));
  },
});
