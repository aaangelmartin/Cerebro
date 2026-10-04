// agents: placeholder until fork F1 builds it (CONTRACT.md, section 4).
Plaza.screen("agents", {
  title: "nav.agents",
  render(root) {
    root.appendChild(K.pageHead(t("nav.agents")));
    root.appendChild(K.state("empty", t("shell.soon"), "agents"));
  },
});
