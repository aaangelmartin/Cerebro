/* Frozen snapshot shim for v07 Market: every public read is answered from files recorded after the game closed;
   every write, stream and cross-origin request is inert. */
(function () {
  "use strict";
  var BASE = "/Cerebro/market";
  var INDEX = {"api/board":{"f":"0001.json"},"api/board/history":{"f":"0002.json"},"api/board/live":{"f":"0003.json"},"api/card/CHA-01":{"f":"0004.json"},"api/card/CHA-02":{"f":"0005.json"},"api/card/CHA-03":{"f":"0006.json"},"api/card/CHA-04":{"f":"0007.json"},"api/card/CHA-05":{"f":"0008.json"},"api/card/CHA-06":{"f":"0009.json"},"api/card/CHA-07":{"f":"0010.json"},"api/card/CHA-08":{"f":"0011.json"},"api/card/CHA-09":{"f":"0012.json"},"api/card/CHA-10":{"f":"0013.json"},"api/card/CHA-11":{"f":"0014.json"},"api/card/CHA-12":{"f":"0015.json"},"api/card/LAT-01":{"f":"0016.json"},"api/card/LAT-02":{"f":"0017.json"},"api/card/LAT-03":{"f":"0018.json"},"api/card/LAT-04":{"f":"0019.json"},"api/card/LAT-05":{"f":"0020.json"},"api/card/LAT-06":{"f":"0021.json"},"api/card/LAT-07":{"f":"0022.json"},"api/card/LAT-08":{"f":"0023.json"},"api/card/LAT-09":{"f":"0024.json"},"api/card/LAT-10":{"f":"0025.json"},"api/card/LAT-11":{"f":"0026.json"},"api/card/LAT-12":{"f":"0027.json"},"api/card/LAV-01":{"f":"0028.json"},"api/card/LAV-02":{"f":"0029.json"},"api/card/LAV-03":{"f":"0030.json"},"api/card/LAV-04":{"f":"0031.json"},"api/card/LAV-05":{"f":"0032.json"},"api/card/LAV-06":{"f":"0033.json"},"api/card/LAV-07":{"f":"0034.json"},"api/card/LAV-08":{"f":"0035.json"},"api/card/LAV-09":{"f":"0036.json"},"api/card/LAV-10":{"f":"0037.json"},"api/card/LAV-11":{"f":"0038.json"},"api/card/LAV-12":{"f":"0039.json"},"api/card/MAL-01":{"f":"0040.json"},"api/card/MAL-02":{"f":"0041.json"},"api/card/MAL-03":{"f":"0042.json"},"api/card/MAL-04":{"f":"0043.json"},"api/card/MAL-05":{"f":"0044.json"},"api/card/MAL-06":{"f":"0045.json"},"api/card/MAL-07":{"f":"0046.json"},"api/card/MAL-08":{"f":"0047.json"},"api/card/MAL-09":{"f":"0048.json"},"api/card/MAL-10":{"f":"0049.json"},"api/card/MAL-11":{"f":"0050.json"},"api/card/MAL-12":{"f":"0051.json"},"api/card/RET-01":{"f":"0052.json"},"api/card/RET-02":{"f":"0053.json"},"api/card/RET-03":{"f":"0054.json"},"api/card/RET-04":{"f":"0055.json"},"api/card/RET-05":{"f":"0056.json"},"api/card/RET-06":{"f":"0057.json"},"api/card/RET-07":{"f":"0058.json"},"api/card/RET-08":{"f":"0059.json"},"api/card/RET-09":{"f":"0060.json"},"api/card/RET-10":{"f":"0061.json"},"api/card/RET-11":{"f":"0062.json"},"api/card/RET-12":{"f":"0063.json"},"api/card/SAL-01":{"f":"0064.json"},"api/card/SAL-02":{"f":"0065.json"},"api/card/SAL-03":{"f":"0066.json"},"api/card/SAL-04":{"f":"0067.json"},"api/card/SAL-05":{"f":"0068.json"},"api/card/SAL-06":{"f":"0069.json"},"api/card/SAL-07":{"f":"0070.json"},"api/card/SAL-08":{"f":"0071.json"},"api/card/SAL-09":{"f":"0072.json"},"api/card/SAL-10":{"f":"0073.json"},"api/card/SAL-11":{"f":"0074.json"},"api/card/SAL-12":{"f":"0075.json"},"api/collections":{"f":"0076.json"},"api/connect/status":{"f":"0077.json","s":401},"api/floor":{"f":"0078.json","seq":2935,"epoch":"3df97eca"},"api/health":{"f":"0079.json"},"api/lots":{"f":"0080.json"},"api/market":{"f":"0081.json"},"api/matches":{"f":"0082.json"},"api/me":{"f":"0083.json","s":401},"api/offers":{"f":"0084.json"},"api/openapi.json":{"f":"0085.json"},"api/opportunities":{"f":"0086.json"},"api/stats":{"f":"0087.json"},"api/status":{"f":"0088.json"},"api/team/t01":{"f":"0089.json"},"api/team/t02":{"f":"0090.json"},"api/team/t03":{"f":"0091.json"},"api/team/t04":{"f":"0092.json"},"api/team/t05":{"f":"0093.json"},"api/team/t06":{"f":"0094.json"},"api/team/t07":{"f":"0095.json"},"api/team/t08":{"f":"0096.json"},"api/team/t09":{"f":"0097.json"},"api/team/t10":{"f":"0098.json"},"api/team/t11":{"f":"0099.json"},"api/team/t12":{"f":"0100.json"},"api/team/t13":{"f":"0101.json"},"api/team/t14":{"f":"0102.json"},"api/team/t15":{"f":"0103.json"},"api/team/t16":{"f":"0104.json"},"api/team/t17":{"f":"0105.json"},"api/team/t18":{"f":"0106.json"},"api/teams":{"f":"0107.json"},"api/wall":{"f":"0108.json"}};
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
