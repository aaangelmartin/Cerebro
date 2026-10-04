// Suggestions: what teams ask for and report. Each one gets a status and, if we want, a reply the team sees.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;
  const STATUS = ["open", "planned", "done", "dismissed"];
  const TONE = { open: "signal", planned: "", done: "ok", dismissed: "" };
  const TOPIC_TONE = { bug: "bad", price: "", feature: "", other: "" };

  Plaza.adminScreen("suggestions", {
    title: "nav.admin.suggestions",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      let filter = "", openId = null;
      const drafts = {};                                             // a reply being written survives the 5 s refresh
      root.appendChild(A.head(t("nav.admin.suggestions"), t("admin.sug.sub")));
      root.appendChild(K.endpoint("GET /plaza/admin/api/suggestions", "POST /plaza/admin/api/action {suggestion, id, status, reply}"));
      const body = root.appendChild(el("div", { class: "adm-suggestions" }));
      const again = () => w.again();
      const w = A.watch(body, "/admin/api/suggestions", (d) => {
        const c = d.counts || {}, all = d.suggestions || [];
        body.appendChild(el("div", { class: "adm-strip" }, K.label(t("admin.col.state")), el("div", { class: "adm-seg", role: "group" }, [""].concat(STATUS).map((s) =>
          el("button", { type: "button", class: filter === s ? "active" : null, "aria-pressed": String(filter === s), onclick: () => { filter = s; w.redraw(); } },
            s ? t("admin.sug.status." + s) : t("common.all"), s ? el("span", { class: "adm-seg-n" }, String(c[s] || 0)) : null)))));
        const rows = all.filter((s) => !filter || s.status === filter).slice().sort((a, b) => (b.tick || 0) - (a.tick || 0));
        body.appendChild(K.panel({ title: t("admin.sug.inbox"), note: t("admin.sug.inboxNote", { n: all.length, open: c.open || 0 }), icon: "suggest", flush: true },
          rows.length ? el("div", { class: "adm-sug-list" }, rows.map((s) => {
            const isOpen = openId === s.id;
            const row = el("div", { class: "adm-sug" + (isOpen ? " is-open" : "") },
              el("div", { class: "adm-sug-head" }, K.id(s.id), A.team(s.team), K.chip(t("admin.sug.topic." + (s.topic || "other")), TOPIC_TONE[s.topic] || ""),
                el("div", { class: "adm-sug-text" }, el("span", null, s.text || ""), el("span", { class: "adm-sug-meta" }, K.tick(s.tick), s.reply ? " · " + t("admin.sug.replied", { reply: s.reply }) : "")),
                K.chip(t("admin.sug.status." + (s.status || "open")), TONE[s.status] || ""),
                K.btn(t(isOpen ? "common.cancel" : "admin.sug.reply"), { small: true, onclick: () => { openId = isOpen ? null : s.id; w.redraw(); } })));
            if (isOpen) {
              const ta = el("textarea", { class: "input adm-sug-reply", rows: "2", maxlength: "280", placeholder: t("admin.sug.replyPh"), "aria-label": t("admin.sug.reply"),
                oninput: () => { drafts[s.id] = ta.value; } }, drafts[s.id] !== undefined ? drafts[s.id] : s.reply || "");
              row.appendChild(el("div", { class: "adm-sug-form" }, ta, el("div", { class: "adm-actions" }, STATUS.map((st) =>
                K.btn(t("admin.sug.status." + st), { small: true, kind: st === s.status ? "primary" : null, title: "POST /plaza/admin/api/action {suggestion}",
                  onclick: () => A.act({ action: "suggestion", id: s.id, status: st, reply: ta.value.trim() }, () => { delete drafts[s.id]; openId = null; return again(); }, t("admin.sug.saved")) })))));
            }
            return row;
          })) : K.state("empty", t("admin.sug.empty"), t("admin.sug.emptyText"))));
      });
      return w.stop;
    },
  });
})();
