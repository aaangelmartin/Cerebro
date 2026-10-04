// admin overview: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("overview", {
  title: "nav.admin.overview",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.overview")));
    root.appendChild(K.state("empty", t("shell.soon"), "overview"));
  },
});
