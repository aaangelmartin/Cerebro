// docs: API for agents. Both tables are drawn from GET /api/openapi.json, the server's own list of live routes,
// so nothing here can name a call that does not exist. The only manual step is pasting the Connect prompt.
Plaza.screen("docs", {
  title: "nav.docs",
  render(root, ctx) {
    const { el } = K;
    const ORDER = ["connect", "home", "cards", "offers", "activity", "market", "card", "settings", "suggest", "landing", "docs", "every screen", "-"];
    const WHO = { agent: ["docs.who.agent", "ok"], team: ["docs.who.team", "ok"], anyone: ["docs.who.anyone", null], session: ["docs.who.session", null] };
    const base = location.origin + API.BASE;
    const short = (path) => path.replace(/^\/Cerebro\/market/, "");
    const screenName = (s) => (s === "-" || !s ? t("docs.agentsOnly") : s === "every screen" ? t("docs.everyScreen") : I18N.t("nav." + s));

    root.appendChild(K.pageHead(t("nav.docs"), t("docs.sub"),
      K.link("/Cerebro/market/agents", { class: "btn sm" }, K.icon("doc", 14), "AGENTS.md"), K.btn(t("docs.copyBase"), { small: true, icon: "copy", onclick: () => K.copy(base + "/api") })));
    root.appendChild(el("div", { class: "docs-facts" },
      el("span", null, el("span", { class: "label" }, t("docs.base")), el("code", null, base + "/api")),
      el("span", null, el("span", { class: "label" }, t("docs.header")), el("code", null, "X-Plaza-Token: <" + t("docs.token") + ">")),
      el("span", { class: "docs-key" }, K.icon("shield", 13), t("docs.gameKey"))));
    const body = root.appendChild(el("div", { class: "docs-body" }));
    body.appendChild(K.state("loading"));
    root.appendChild(K.endpoint("GET /Cerebro/market/api/openapi.json", "GET /Cerebro/market/AGENTS.md"));

    function draw(doc) {
      K.clear(body);
      const ops = [];
      for (const [path, methods] of Object.entries((doc && doc.paths) || {})) {
        for (const [method, op] of Object.entries(methods)) {
          const ex = op.requestBody && op.requestBody.content && op.requestBody.content["application/json"];
          ops.push({ method: method.toUpperCase(), path, what: op.summary || "", who: op["x-who"] || "anyone", screen: op["x-screen"] || "-",
                     body: ex && ex.example !== undefined ? JSON.stringify(ex.example) : null, example: op["x-example"] || null });
        }
      }
      if (!ops.length) { body.appendChild(K.state("empty", t("docs.none"))); return; }
      const rank = (s) => { const i = ORDER.indexOf(s); return i < 0 ? ORDER.length : i; };
      ops.sort((a, b) => rank(a.screen) - rank(b.screen) || a.path.localeCompare(b.path) || a.method.localeCompare(b.method));
      const call = (o) => el("code", { class: "docs-call" }, el("b", null, o.method), " " + short(o.path));
      const who = (o) => { const [key, tone] = WHO[o.who] || WHO.anyone; return K.chip(t(key), tone); };

      body.appendChild(K.panel({ title: t("docs.can"), note: t("docs.canNote", { n: ops.length }), flush: true },
        el("div", { class: "docs-scroll" }, K.table([
          { key: "what", label: t("docs.what") },
          { key: "call", label: t("docs.call"), render: call },
          { key: "body", label: t("docs.example"), render: (o) => (o.body ? el("code", { class: "docs-json" }, o.body)
            : o.example ? el("a", { class: "docs-json docs-link", href: o.example, target: "_blank", rel: "noopener" }, "→ " + t("docs.answer")) : el("span", { class: "muted" }, "–")) },
        ], ops))));

      body.appendChild(K.panel({ title: t("docs.loop"), note: t("docs.loopNote") },
        el("ol", { class: "docs-loop" }, [1, 2, 3, 4, 5].map((i) => el("li", null, t("docs.loop" + i))))));

      const rows = [{ manual: true, screen: "connect", what: t("docs.paste") }].concat(ops);
      body.appendChild(K.panel({ title: t("docs.coverage"), note: t("docs.coverageNote"), flush: true },
        el("div", { class: "docs-scroll" }, K.table([
          { key: "screen", label: t("docs.screen"), render: (o) => el("b", { class: "docs-screen" }, screenName(o.screen)) },
          { key: "what", label: t("docs.action") },
          { key: "call", label: t("docs.endpoint"), render: (o) => (o.manual ? el("span", { class: "muted" }, "– " + t("docs.manual")) : call(o)) },
          { key: "who", label: t("docs.whoCol"), render: (o) => (o.manual ? K.chip(t("docs.who.hand"), "signal") : who(o)) },
        ], rows))));
    }

    API.get("/api/openapi.json").then(draw, (e) => {
      K.clear(body).appendChild(K.state("error", t("common.error"), e && e.message, K.btn("AGENTS.md", { small: true, href: "/Cerebro/market/AGENTS.md" })));
    });
  },
});
