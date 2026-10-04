// Activity & moderation: every event and message, newest first, and the switches that stop a team or the market.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;
  const KINDS = ["", "agent", "offer", "deal", "announce", "connect", "match"];
  const TONE = { deal: "ok", settle: "ok", announce: "signal", accept: "ok", connect: "", note: "", want: "", offer: "" };

  /** One floor item as a sentence. Everything in it is already public on the floor or on the game's feed. */
  A.item = function (i) {
    const price = typeof i.price === "number" ? " · " + K.price(i.price) : "";
    const where = i.venue ? " · " + i.venue : "", to = i.to ? " → " + i.to : "";
    if (i.text) return (i.ref ? i.ref + price + to + " · " : "") + i.text;
    if (i.kind === "offer") return t(i.side === "bid" ? "admin.act.bid" : "admin.act.ask") + " " + (i.ref || "") + (i.ref_back ? " ⇄ " + i.ref_back : "") + price + to + where + (i.offer ? " · #" + i.offer : "");
    if (i.kind === "deal") return (i.ref || (i.refs || []).join(", ")) + price + to + where + (i.dealer ? " · " + i.dealer : "");
    return [i.ref, i.match].filter(Boolean).join(" · ") + price + to + where;
  };

  Plaza.adminScreen("activity", {
    title: "nav.admin.activity",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root) {
      const pick = { kind: "", team: "" };
      const actions = el("div", { class: "adm-actions" });
      root.appendChild(A.head(t("admin.activity.title"), t("admin.activity.sub"), actions));
      root.appendChild(K.endpoint("GET /plaza/admin/api/activity?kind=&team=", "POST /plaza/admin/api/action {on | off | pause | resume | hide | unhide | block | unblock}"));
      const filters = root.appendChild(el("div", { class: "adm-strip" }));
      const body = root.appendChild(el("div", { class: "adm-activity" }));
      const again = () => w.again();
      const teamIn = el("input", { class: "input adm-activity-team", placeholder: "t16", "aria-label": t("admin.col.team"), value: pick.team,
        onchange: () => { pick.team = /^t\d\d$/.test(teamIn.value) ? teamIn.value : ""; teamIn.value = pick.team; again(); } });
      const drawFilters = () => {
        K.clear(filters);
        K.add(filters, [K.label(t("admin.activity.kind")), el("div", { class: "adm-seg", role: "group" }, KINDS.map((k) => el("button", { type: "button", class: pick.kind === k ? "active" : null,
          "aria-pressed": String(pick.kind === k), onclick: () => { pick.kind = k; drawFilters(); again(); } }, k ? t("admin.act.kind." + k) : t("common.all")))),
          K.label(t("admin.col.team")), teamIn]);
      };
      drawFilters();
      const w = A.watch(body, "/admin/api/activity", (d) => {
        const adm = d.admin || {}, hidden = new Set(adm.hidden || []), blocked = new Set(adm.blocked || []);
        K.clear(actions);
        K.add(actions, [
          adm.mm_paused ? A.actBtn(t("admin.mm.resume"), { action: "resume" }, again) : A.actBtn(t("admin.mm.pause"), { action: "pause" }, again, { confirm: true }),
          adm.enabled === false ? A.actBtn(t("admin.activity.on"), { action: "on" }, again, { kind: "primary" }) : A.actBtn(t("admin.activity.off"), { action: "off" }, again, { confirm: true, kind: "danger" })]);
        const items = (d.items || []).filter((i) => !API.mock || ((!pick.kind || i.kind === pick.kind || i.src === pick.kind) && (!pick.team || i.team === pick.team))).slice().reverse();
        if (blocked.size) body.appendChild(el("div", { class: "adm-strip" }, K.label(t("admin.activity.blocked")), [...blocked].map((b) => A.actBtn(b + " · " + t("admin.teams.unblock"), { action: "unblock", team: b }, again))));
        body.appendChild(K.panel({ title: t("admin.activity.stream"), note: t("admin.activity.streamNote", { n: items.length, hidden: hidden.size }), icon: "activity", flush: true },
          items.length ? el("div", { class: "adm-events" }, items.slice(0, 200).map((i) => {
            const gone = hidden.has(i.seq) || i.hidden;
            return el("div", { class: "adm-event" + (gone ? " is-hidden" : "") },
              el("span", { class: "adm-event-tick" }, K.tick(i.tick)), A.team(i.team || "–"),
              el("span", { class: "adm-event-kind tone-" + (TONE[i.kind] || "") }, i.kind || ""), el("span", { class: "adm-event-src" }, i.src || ""),
              el("span", { class: "adm-event-text" }, A.item(i)),
              i.src === "game" ? null : el("span", { class: "adm-rowacts" },
                gone ? A.actBtn(t("admin.activity.unhide"), { action: "unhide", message: i.seq }, again) : A.actBtn(t("admin.activity.hide"), { action: "hide", message: i.seq }, again, { confirm: true }),
                i.team && !blocked.has(i.team) ? A.actBtn(t("admin.teams.block"), { action: "block", team: i.team }, again, { confirm: true }) : null));
          })) : K.state("empty", t("admin.activity.empty"), t("admin.activity.emptyText"))));
      }, () => ({ kind: pick.kind, team: pick.team }));
      return w.stop;
    },
  });
})();
