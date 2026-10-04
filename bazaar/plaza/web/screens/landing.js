// landing: placeholder until fork F1 builds it (CONTRACT.md, section 4).
Plaza.screen("landing", {
  title: "nav.landing",
  render(root) {
    root.appendChild(K.pageHead(t("nav.landing")));
    root.appendChild(K.state("empty", t("shell.soon"), "landing"));
  },
});
