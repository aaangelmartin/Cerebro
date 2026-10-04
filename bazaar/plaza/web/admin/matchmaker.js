// admin matchmaker: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("matchmaker", {
  title: "nav.admin.matchmaker",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.matchmaker")));
    root.appendChild(K.state("empty", t("shell.soon"), "matchmaker"));
  },
});
