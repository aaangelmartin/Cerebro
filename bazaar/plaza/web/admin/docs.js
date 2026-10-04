// API · for agents (the host's): every route of the panel, drawn from the server's own list, and the table
// screen -> action -> call that shows nothing here needs hands.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;
  // What each button of the panel sends. The action names are checked against the server's list below.
  const COVER = [
    ["overview", "read", "GET /plaza/admin/api/overview"],
    ["performance", "read", "GET /plaza/admin/api/performance"],
    ["matchmaker", "read", "GET /plaza/admin/api/matchmaker"],
    ["matchmaker", "pause", { action: "pause" }], ["matchmaker", "resume", { action: "resume" }], ["matchmaker", "refresh", { action: "refresh" }],
    ["matchmaker", "expire", { action: "expire", match: "m-ba346d6c75" }], ["matchmaker", "exclude", { action: "exclude", match: "m-ba346d6c75" }],
    ["matchmaker", "include", { action: "include", match: "m-ba346d6c75" }],
    ["matchmaker", "force", { action: "force", seller: "t04", buyer: "t16", ref: "SAL-10", price: 58 }],
    ["trades", "read", "GET /plaza/admin/api/trades?state=&team="],
    ["trades", "hideMsg", { action: "hide", match: "m-ba346d6c75", message: 2 }], ["trades", "unhideMsg", { action: "unhide", match: "m-ba346d6c75", message: 2 }],
    ["teams", "read", "GET /plaza/admin/api/teams"], ["teams", "record", "GET /plaza/admin/api/activity?team=t16"],
    ["teams", "block", { action: "block", team: "t16" }], ["teams", "unblock", { action: "unblock", team: "t16" }],
    ["activity", "read", "GET /plaza/admin/api/activity?kind=&team=&since="],
    ["activity", "hide", { action: "hide", message: 301 }], ["activity", "unhide", { action: "unhide", message: 301 }],
    ["activity", "off", { action: "off" }], ["activity", "on", { action: "on" }],
    ["suggestions", "read", "GET /plaza/admin/api/suggestions"],
    ["suggestions", "suggestion", { action: "suggestion", id: "s-0001", status: "planned", reply: "On the card page today." }],
    ["venue", "read", "GET /plaza/admin/api/venue"],
    ["docs", "read", "GET /plaza/admin/api/openapi"],
  ];

  Plaza.adminScreen("docs", {
    title: "nav.admin.docs",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      root.appendChild(A.head(t("nav.admin.docs"), t("admin.docs.sub")));
      root.appendChild(K.endpoint("GET /plaza/admin/api/openapi", "X-Plaza-Admin: <data/live/plaza_admin.token> → http://127.0.0.1:8793"));
      const body = root.appendChild(el("div", { class: "adm-docs" }));
      const w = A.watch(body, "/admin/api/openapi", (d) => {
        const routes = [];
        Object.entries(d.paths || {}).forEach(([path, methods]) => Object.entries(methods).forEach(([m, o]) => routes.push({ method: m.toUpperCase(), path, ...o })));
        const admin = routes.filter((r) => r["x-who"] === "admin"), pub = routes.filter((r) => r["x-who"] !== "admin");
        const live = new Set(admin.map((r) => r.method + " " + r.path));
        const post = admin.find((r) => r.method === "POST");
        const actions = post ? String(post.summary || "").split(":").slice(1).join(":").split(",").map((s) => s.trim().replace(/\.$/, "")).filter(Boolean) : [];
        body.appendChild(el("p", { class: "adm-note" }, t("admin.docs.how")));
        const routeTable = (list) => K.table([
          { label: t("admin.docs.call"), render: (r) => el("span", { class: "adm-call" }, el("b", null, r.method), " ", r.path) },
          { label: t("admin.docs.what"), render: (r) => r.summary || "" },
          { label: t("admin.docs.screen"), render: (r) => r["x-screen"] || "–" },
          { label: t("admin.docs.example"), render: (r) => (r["x-example"] ? el("a", { class: "adm-link", href: r["x-example"], target: "_blank", rel: "noopener" }, t("admin.docs.open")) : "–") },
        ], list);
        body.appendChild(K.panel({ title: t("admin.docs.panel"), note: t("admin.docs.panelNote", { n: admin.length }), icon: "api", flush: true },
          admin.length ? routeTable(admin) : K.state("empty", t("admin.noData"))));
        const rows = COVER.map(([screen, what, call]) => {
          const isPost = typeof call !== "string";
          const key = isPost ? "POST /plaza/admin/api/action" : call.split("?")[0];
          const there = live.has(key) && (!isPost || !actions.length || actions.includes(call.action));
          return { screen, what, call, isPost, there };
        });
        const missing = rows.filter((r) => !r.there).length;
        body.appendChild(K.panel({ title: t("admin.docs.cover"), note: t(missing ? "admin.docs.coverMissing" : "admin.docs.coverNote", { n: missing }), icon: "check", flush: true },
          K.table([
            { label: t("admin.docs.screen"), render: (r) => t("nav.admin." + r.screen) },
            { label: t("admin.docs.action"), render: (r) => t("admin.docs.do." + r.what) },
            { label: t("admin.docs.call"), render: (r) => el("span", { class: "adm-call" }, r.isPost ? [el("b", null, "POST"), " /plaza/admin/api/action ", JSON.stringify(r.call)] : [el("b", null, r.call.split(" ")[0]), " ", r.call.split(" ").slice(1).join(" ")]) },
            { label: t("admin.docs.who"), render: (r) => (r.there ? K.chip(t("admin.docs.hostAgent"), "ok") : K.chip(t("admin.docs.notYet"))) },
          ], rows),
          missing ? null : el("div", { class: "adm-quiet" }, K.icon("hand", 14), t("admin.docs.byHand"))));
        body.appendChild(K.panel({ title: t("admin.docs.public"), note: t("admin.docs.publicNote", { n: pub.length }), icon: "doc", flush: true },
          pub.length ? routeTable(pub) : K.state("empty", t("admin.noData")),
          el("div", { class: "adm-actions adm-pad" }, K.btn("AGENTS.md", { small: true, href: "/plaza/AGENTS.md", icon: "doc" }), K.btn("openapi.json", { small: true, href: "/plaza/api/openapi.json", icon: "api" }))));
      });
      return w.stop;
    },
  });
})();
