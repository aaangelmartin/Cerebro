// Matchmaker: the queue, why each pair was proposed, and what is stuck. Limits are "set" and "overlap", no more.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;

  Plaza.adminScreen("matchmaker", {
    title: "nav.admin.matchmaker",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      const actions = el("div", { class: "adm-actions" });
      root.appendChild(A.head(t("nav.admin.matchmaker"), t("admin.mm.sub"), actions));
      root.appendChild(K.endpoint("GET /plaza/admin/api/matchmaker", "POST /plaza/admin/api/action {pause | resume | refresh | expire | exclude | include | force}"));
      const body = root.appendChild(el("div", { class: "adm-matchmaker" }));
      const again = () => w.again();
      const w = A.watch(body, "/admin/api/matchmaker", (d) => {
        K.clear(actions);
        K.add(actions, [
          d.paused ? A.actBtn(t("admin.mm.resume"), { action: "resume" }, again, { kind: "primary" }) : A.actBtn(t("admin.mm.pause"), { action: "pause" }, again, { confirm: true }),
          A.actBtn(t("admin.mm.refresh"), { action: "refresh" }, again, { icon: "refresh" })]);
        const queue = d.queue || [], f = d.funnel || {}, r = d.rules || {};
        const kinds = {};
        queue.forEach((m) => { kinds[m.kind] = (kinds[m.kind] || 0) + 1; });
        body.appendChild(el("div", { class: "adm-strip" }, K.label(t("admin.mm.state")), K.pill(t("status." + (d.paused ? "paused" : "on")), d.paused ? "pause" : "ok"),
          K.label(t("admin.mm.kinds")), Object.keys(kinds).length ? Object.entries(kinds).map(([k, n]) => K.chip(t("admin.kind." + k) + " " + n)) : K.chip(t("admin.none")),
          K.label(t("admin.mm.candidates")), K.id(K.num(d.candidates || 0)), K.label(t("admin.mm.cooling")), K.id(K.num(d.cooling || 0))));

        body.appendChild(K.panel({ title: t("admin.mm.queue"), note: t("admin.mm.queueNote", { n: queue.length }), icon: "matchmaker", flush: true },
          queue.length ? K.table([
            { label: t("admin.col.card"), render: (m) => el("span", { class: "adm-ref" }, K.id(m.ref || "–"), m.ref_back ? [K.icon("swap", 11), K.id(m.ref_back)] : null) },
            { label: t("admin.col.match"), render: (m) => K.id(m.id) },
            { label: t("admin.col.pair"), render: (m) => A.pair(m.seller, m.buyer, m.kind !== "sale") },
            { label: t("admin.col.suggested"), num: true, render: (m) => (m.kind === "sale" ? K.price(m.price) : t("admin.kind." + m.kind)) },
            { label: t("admin.col.state"), render: (m) => [A.stateChip(m.state), m.forced ? K.chip(t("admin.mm.forced"), "warn") : null] },
            { label: t("admin.col.limits"), render: (m) => A.limits(m.overlap) },
            { label: t("admin.col.why"), render: (m) => el("span", { class: "adm-why" }, m.why || "") },
            { label: t("admin.col.age"), num: true, render: (m) => el("span", { class: m.stalled ? "tone-warn" : null }, t(m.age_ticks === 1 ? "common.tick1" : "common.ticks", { n: K.num(m.age_ticks || 0) })) },
            { label: "", render: (m) => el("span", { class: "adm-rowacts" }, A.actBtn(t("admin.mm.expire"), { action: "expire", match: m.id }, again, { confirm: true }),
                A.actBtn(t("admin.mm.exclude"), { action: "exclude", match: m.id }, again, { confirm: true })) },
          ], queue, { onrow: (m) => Plaza.go("/plaza/admin/trades?match=" + m.id) }) : K.state("empty", t("admin.mm.empty"), t("admin.mm.emptyText"))));

        const low = body.appendChild(el("div", { class: "adm-grid adm-matchmaker-low" }));
        const stalled = d.stalled || [];
        low.appendChild(K.panel({ title: t("admin.mm.stuck"), note: t("admin.mm.stuckNote", { n: K.num(r.stall_ticks || 0) }), icon: "alert", flush: true },
          stalled.length ? el("div", { class: "adm-rows" }, stalled.map((m) => el("div", { class: "adm-row" },
            el("span", { class: "adm-row-name" }, K.id(m.id), " ", K.id(m.ref || ""), " ", A.pair(m.seller, m.buyer, m.kind !== "sale")),
            el("span", { class: "adm-row-value tone-warn" }, t("admin.mm.quiet", { n: K.num(m.quiet_ticks || m.age_ticks || 0) })))))
            : el("div", { class: "adm-quiet" }, K.icon("check", 14), t("admin.mm.noStuck"))));
        low.appendChild(K.panel({ title: t("admin.mm.rules"), icon: "shield", flush: true }, A.rows([
          [t("admin.mm.rule.value"), t("admin.mm.rule.valueText")],
          [t("admin.mm.rule.limits"), t("admin.mm.rule.limitsText")],
          [t("admin.mm.rule.teams"), t("admin.mm.rule.teamsText")],
          [t("admin.mm.rule.proposal"), typeof r.proposal_ticks === "number" ? t("common.ticks", { n: K.num(r.proposal_ticks) }) : null],
          [t("admin.mm.rule.offer"), typeof r.offer_ticks === "number" ? t("common.ticks", { n: K.num(r.offer_ticks) }) : null],
          [t("admin.mm.rule.pass"), typeof r.pass_ticks === "number" ? t("common.ticks", { n: K.num(r.pass_ticks) }) : null],
        ])));
        const ex = d.excluded_matches || [];
        low.appendChild(K.panel({ title: t("admin.mm.excluded"), note: String(ex.length), flush: true },
          ex.length ? el("div", { class: "adm-rows" }, ex.map((id) => el("div", { class: "adm-row" }, el("span", { class: "adm-row-name" }, K.id(id)),
            A.actBtn(t("admin.mm.include"), { action: "include", match: id }, again)))) : el("div", { class: "adm-quiet" }, t("admin.mm.noExcluded")),
          A.rows([[t("admin.funnel.proposed"), K.num(f.proposed || 0)], [t("admin.funnel.offer"), K.num(f.offer_on_v07 || 0)],
                  [t("admin.funnel.accepted"), K.num(f.accepted || 0)], [t("admin.funnel.settled"), K.num(f.settled || 0), f.settled ? "ok" : null]])));

      });
      // Forcing a pair is the one thing here that writes a match by hand: a seller, a buyer, a card and a price.
      const inp = (name, ph, type) => el("input", { class: "input", name, placeholder: ph, type: type || "text", "aria-label": ph, autocomplete: "off" });
      const fs = inp("seller", "t04"), fb = inp("buyer", "t16"), fr = inp("ref", "SAL-10"), fp = inp("price", "58", "number");
      root.appendChild(K.panel({ title: t("admin.mm.force"), note: t("admin.mm.forceNote"), icon: "hand" },
        el("form", { class: "adm-form", onsubmit: (e) => {
          e.preventDefault();
          const price = parseInt(fp.value, 10);
          if (!/^t\d\d$/.test(fs.value) || !/^t\d\d$/.test(fb.value) || !/^[A-Z]{3}-\d\d$/.test(fr.value) || !(price >= 1 && price <= 2000)) { K.toast(t("admin.mm.forceBad"), "bad"); return; }
          A.act({ action: "force", seller: fs.value, buyer: fb.value, ref: fr.value, price }, again);
        } }, K.label(t("common.seller")), fs, K.label(t("common.buyer")), fb, K.label(t("admin.col.card")), fr, K.label(t("common.price")), fp,
          el("button", { class: "btn sm", type: "submit" }, t("admin.mm.forceGo")))));
      return w.stop;
    },
  });
})();
