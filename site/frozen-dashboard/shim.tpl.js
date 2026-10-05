/* Frozen snapshot shim: every API read is answered from files recorded at the end of the game; every write is inert. */
(function () {
  "use strict";
  try { if (!localStorage.getItem("bazaar.lang")) localStorage.setItem("bazaar.lang", "en"); } catch (e) {}
  var INDEX = /*INDEX*/;
  var base = new URL(".", document.baseURI);
  var realFetch = window.fetch.bind(window);
  var served = {}, mem = {};
  function json(status, obj) { return new Response(JSON.stringify(obj), { status: status, headers: { "Content-Type": "application/json" } }); }
  function flash() {
    var r = document.getElementById("frozen-ribbon"); if (!r) return;
    r.classList.add("flash"); setTimeout(function () { r.classList.remove("flash"); }, 900);
  }
  function pick(path, q) {
    var list = INDEX[path]; if (!list) return null;
    var i, e, best = null;
    for (i = 0; i < list.length; i++) if (list[i].q === q) return list[i];
    var sinceLike = /(^|&)(since|since_seq)=/.test(q);
    if (served[path] && sinceLike) {
      for (i = 0; i < list.length; i++) { e = list[i]; if (e.s && (!best || e.n < best.n)) best = e; }
      if (best) return best;
    }
    for (i = 0; i < list.length; i++) { e = list[i]; if (!best || e.n > best.n) best = e; }
    return best;
  }
  window.fetch = function (input, opts) {
    var url = typeof input === "string" ? input : (input && input.url) || String(input);
    var method = ((opts && opts.method) || (input && input.method) || "GET").toUpperCase();
    var u;
    try { u = new URL(url, document.baseURI); } catch (e) { return realFetch(input, opts); }
    var rel = u.pathname.indexOf(base.pathname) === 0 ? u.pathname.slice(base.pathname.length) : null;
    var isApi = rel !== null && rel.indexOf("api/") === 0;
    var isPlaza = u.origin === location.origin && u.pathname.indexOf("/plaza/") === 0;
    if (u.origin !== location.origin) {
      if (/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) return realFetch(input, opts);
      return Promise.resolve(json(403, { ok: false, error: "frozen", message: "Frozen snapshot · read-only" }));
    }
    if (method !== "GET") { flash(); return Promise.resolve(json(403, { ok: false, error: "frozen", message: "Frozen snapshot · read-only" })); }
    if (isPlaza) return Promise.resolve(json(404, { ok: false, error: "not_in_snapshot", message: "Not part of the public snapshot" }));
    if (!isApi) return realFetch(input, opts);
    var path = rel, q = u.search.replace(/^\?/, "");
    var e = pick(path, q);
    served[path] = true;
    if (!e) return Promise.resolve(json(404, { ok: false, error: "not_in_snapshot", message: "Not part of the frozen snapshot" }));
    if (!mem[e.f]) mem[e.f] = realFetch(new URL("frozen/d/" + e.f, base).href).then(function (r) { return r.text(); });
    return mem[e.f].then(function (t) { return new Response(t, { status: 200, headers: { "Content-Type": "application/json" } }); });
  };
  // belt and braces: no XHR, beacons or sockets to anything but this origin's static files
  var XO = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, url) {
    var u = new URL(url, document.baseURI);
    if (String(m).toUpperCase() !== "GET" || u.origin !== location.origin) throw new Error("Frozen snapshot · read-only");
    return XO.apply(this, arguments);
  };
  if (navigator.sendBeacon) navigator.sendBeacon = function () { return false; };
  window.WebSocket = function () { throw new Error("Frozen snapshot · read-only"); };
  window.EventSource = function () { throw new Error("Frozen snapshot · read-only"); };
})();
