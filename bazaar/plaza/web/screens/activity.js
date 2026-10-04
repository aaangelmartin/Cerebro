// activity: placeholder until fork F2 builds it (CONTRACT.md, section 4).
Plaza.screen("activity", {
  title: "nav.activity",
  render(root) {
    root.appendChild(K.pageHead(t("nav.activity")));
    root.appendChild(K.state("empty", t("shell.soon"), "activity"));
  },
});
