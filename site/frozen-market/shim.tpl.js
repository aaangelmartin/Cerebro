/* Frozen snapshot shim for v07 Market: every public read is answered from files recorded after the game closed;
   every write, stream and cross-origin request is inert. */
(function () {
  "use strict";
  var BASE = "/Cerebro/market";
  var INDEX = /*INDEX*/;
  // GitHub Pages serves a route as a folder ("/board/"); the router expects "/board".
  try {
    var p = location.pathname;
    if (p.length > BASE.length + 1 && p.charAt(p.length - 1) === "/") history.replaceState({}, "", p.slice(0, -1) + location.search + location.hash);
  } catch (e) {}
  var realFetch = window.fetch.bind(window);
  var mem = {};
  function json(status, obj) { return new Response(JSON.stringify(obj), { status: status, headers: { "Content-Type": "application/json" } }); }
  var FROZEN = { ok: false, error: "frozen", message: "Frozen snapshot · read-only" };
  function flash() { var r = document.getElementById("frozen-ribbon"); if (!r) return; r.classList.add("flash"); setTimeout(function () { r.classList.remove("flash"); }, 900); }
  window.fetch = function (input, opts) {
    var url = typeof input === "string" ? input : (input && input.url) || String(input);
    var method = ((opts && opts.method) || (input && input.method) || "GET").toUpperCase();
    var u;
    try { u = new URL(url, document.baseURI); } catch (e) { return Promise.resolve(json(403, FROZEN)); }
    if (u.origin !== location.origin) {
      if (/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) return realFetch(input, opts);
      return Promise.resolve(json(403, FROZEN));
    }
    if (method !== "GET") { flash(); return Promise.resolve(json(403, FROZEN)); }
    // Recorded data still names the live paths ("/plaza/art/LAV-01.svg"): they live under this snapshot.
    if (u.pathname.indexOf("/plaza/") === 0) u = new URL(BASE + u.pathname.slice(6) + u.search, location.origin);
    var inBase = u.pathname.indexOf(BASE + "/") === 0;
    var rel = inBase ? u.pathname.slice(BASE.length + 1) : null;
    if (rel === "AGENTS.md" || u.pathname === "/AGENTS.md") return realFetch(BASE + "/AGENTS.md");
    if (rel === null) return Promise.resolve(json(404, { ok: false, error: "not_in_snapshot", message: "Not part of the frozen snapshot" }));
    if (rel.indexOf("api/") !== 0 && rel.indexOf("admin") !== 0) return realFetch(u.pathname + u.search);
    var e = INDEX[rel];
    if (!e) return Promise.resolve(json(404, { ok: false, error: "not_in_snapshot", message: "Not part of the frozen snapshot" }));
    if (rel === "api/floor" && /(^|[?&])since=[1-9]/.test(u.search)) return Promise.resolve(json(200, { epoch: e.epoch || "frozen", seq: e.seq || 0, items: [] }));
    if (!mem[e.f]) mem[e.f] = realFetch(BASE + "/frozen/d/" + e.f).then(function (r) { return r.text(); });
    return mem[e.f].then(function (t) { return new Response(t, { status: e.s || 200, headers: { "Content-Type": "application/json" } }); });
  };
  var XO = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, url) {
    var u = new URL(url, document.baseURI);
    if (String(m).toUpperCase() !== "GET" || u.origin !== location.origin) throw new Error("Frozen snapshot · read-only");
    return XO.apply(this, arguments);
  };
  if (navigator.sendBeacon) navigator.sendBeacon = function () { return false; };
  try { window.EventSource = undefined; } catch (e) {}            // the floor falls back to its (frozen) polling
  window.WebSocket = function () { throw new Error("Frozen snapshot · read-only"); };
})();
