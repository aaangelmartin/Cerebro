// admin venue: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("venue", {
  title: "nav.admin.venue",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.venue")));
    root.appendChild(K.state("empty", t("shell.soon"), "venue"));
  },
});
