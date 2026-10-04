// connect: placeholder until fork F1 builds it (CONTRACT.md, section 4).
Plaza.screen("connect", {
  title: "nav.connect",
  render(root) {
    root.appendChild(K.pageHead(t("nav.connect")));
    root.appendChild(K.state("empty", t("shell.soon"), "connect"));
  },
});
