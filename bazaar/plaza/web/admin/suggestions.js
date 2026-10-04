// admin suggestions: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("suggestions", {
  title: "nav.admin.suggestions",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.suggestions")));
    root.appendChild(K.state("empty", t("shell.soon"), "suggestions"));
  },
});
