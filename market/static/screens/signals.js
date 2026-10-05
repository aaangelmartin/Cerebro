// signals: "hidden demand" and "hidden supply" for the connected team's own cards, as a block other screens place.
//   Signals.block(ctx, "sell" | "buy" | "both") -> a node that loads and refreshes itself; Signals.stop(node)
// Levels and counts are coarse on purpose: no price of anybody and no team is ever shown.
(function () {
  "use strict";
  const { el } = K;
  const stops = new WeakMap();

  function row(s, side, ctx) {
    const pub = side === "sell" ? s.best_public_bid : s.best_public_ask;
    const send = K.btn(t(side === "sell" ? "sig.sellIt" : "sig.buyIt"), { small: true, kind: "primary", onclick: () => {
      send.disabled = true;                                 // listed with no limit of ours: the agent decides each price
      API.post("/api/me/cards", { op: "add", list: side === "sell" ? "spares" : "wants", ref: s.ref })
        .then(() => K.toast(t("sig.listed", { ref: s.ref }), "ok"), (e) => { send.disabled = false; K.toast((e && e.message) || t("common.error"), "bad"); });
    } });
    return el("div", { class: "sig-item" },
      K.card(s, { size: "sm", owned: side === "sell", href: "/Cerebro/market/card/" + s.ref }),
      el("div", { class: "sig-main" },
        el("div", { class: "sig-top" }, el("span", { class: "sig-name" }, s.name || s.ref),
          el("span", { class: "chip sig-level " + s.level }, t("sig.level." + s.level))),
        el("div", { class: "id" }, s.ref.replace("-", " · ") + "  ·  " + t(s.teams === "4+" ? "sig.agents4" : "sig.agents2")),
        el("div", { class: "id muted" }, typeof pub === "number" ? t(side === "sell" ? "sig.bid" : "sig.ask", { price: K.price(pub) })
          : t("sig.ref", { price: K.price(s.reference_price) })),
        send));
  }

  function block(ctx, which) {
    const box = el("div", { class: "sig-block" });
    if (!ctx.me) return box;
    const draw = (d) => {
      K.clear(box);
      const parts = [];
      if (which !== "buy") {
        parts.push(K.panel({ title: t("sig.demand"), note: t("sig.demandSub"), icon: "activity" },
          (d.sell || []).length ? el("div", { class: "sig-list" }, d.sell.map((s) => row(s, "sell", ctx))) : el("p", { class: "muted" }, t("sig.noDemand")),
          el("p", { class: "muted sig-note" }, t("sig.note", { tick: K.tick(d.next_refresh_tick) }))));
      }
      if (which !== "sell" && ((d.buy || []).length || which === "buy")) {
        parts.push(K.panel({ title: t("sig.supply"), note: t("sig.supplySub"), icon: "activity" },
          (d.buy || []).length ? el("div", { class: "sig-list" }, d.buy.map((s) => row(s, "buy", ctx))) : el("p", { class: "muted" }, t("sig.noSupply")),
          el("p", { class: "muted sig-note" }, t("sig.note", { tick: K.tick(d.next_refresh_tick) }))));
      }
      K.add(box, parts);
    };
    let seen = false;
    const stop = API.poll("/api/me/signals", 30000, (d) => {
      if (seen && !box.isConnected) return stop();           // the screen was left
      seen = true;
      draw(d);
    }, () => {});
    stops.set(box, stop);
    return box;
  }

  window.Signals = { block, stop(node) { const s = stops.get(node); if (s) s(); } };
})();
