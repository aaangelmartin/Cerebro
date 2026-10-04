// how: placeholder until fork F1 builds it (CONTRACT.md, section 4).
Plaza.screen("how", {
  title: "nav.how",
  render(root) {
    root.appendChild(K.pageHead(t("nav.how")));
    root.appendChild(K.state("empty", t("shell.soon"), "how"));
  },
});
