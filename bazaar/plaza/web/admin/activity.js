// admin activity: placeholder until fork F4 builds it (CONTRACT.md, section 4).
Plaza.adminScreen("activity", {
  title: "nav.admin.activity",
  render(root) {
    root.appendChild(K.pageHead(t("nav.admin.activity")));
    root.appendChild(K.state("empty", t("shell.soon"), "activity"));
  },
});
