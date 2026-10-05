#!/usr/bin/env python3
"""Build the landing page of the public site (https://nglmrtn.com/Cerebro/).

Reads template.html (head, base styles and the winner poster) and fills in the system map,
the doors and the entrance animation. Usage: python3 build.py [out.html]
"""
import sys, html, pathlib
HERE = pathlib.Path(__file__).resolve().parent
OUT = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "index.html")
TEMPLATE = (HERE / "template.html").read_text(encoding="utf-8")

# ---- the system map, as drawn on the pitch deck slide "What did you build? Your agent." ----
# id, title, subtitle, x, y, w, bar colour, one line for the caption
N = [
 ("rec", "Recorder", "every event, replayable", 45, 77, 250, "#4C9BE0", "Records every event of the game, replayable."),
 ("signals", "Signals watcher", "news, rumours, sources", 45, 257, 250, "#4C9BE0", "Reads the news and the rumours, and weighs their sources."),
 ("market", "v07 Market", "private matching, auctions", 45, 437, 250, "#45B883", "Private matching and auctions for other teams' agents."),
 ("lab", "Lab", "replay, lessons, gate", 45, 617, 250, "#45B883", "Replays the recordings, tests each lesson, and a gate promotes it."),
 ("council", "Council", "three opinions, majority", 739, 47, 250, "#E3A33B", "Three opinions vote on the big moves; the majority decides."),
 ("fast", "Fast loop", "acts every tick", 1115, 107, 230, "#45B883", "Acts every tick on the policies in force."),
 ("rails", "Rails", "veto in code", 1425, 107, 230, "#E2564D", "Code that vetoes any move that loses value."),
 ("exec", "Executor", "sends, then verifies", 1425, 307, 230, "#F4F1EA", "Sends what survives the rails, then verifies it."),
 ("game", "The game", "dealers, teams, duels", 1425, 517, 230, "#6A727B", "The Bazaar: five dealers, eighteen teams and the duels."),
 ("duels", "Duels + guard", "model, code fallback", 1115, 337, 230, "#9B7FE6", "A bounded model plays each duel, with a code fallback and a guard."),
 ("broker", "Fair broker", "the Market Test", 1115, 537, 230, "#9B7FE6", "Matches the crossing pairs in the Market Test."),
 ("workshop", "Workshop", "fix, tests, deploy", 395, 657, 250, "#E2564D", "Writes the fix, runs the tests and deploys while the bot plays."),
 ("dash", "Dashboard", "every decision visible", 739, 657, 250, "#4C9BE0", "Shows every decision before it is sent."),
 ("human", "Human", "policy, approvals, caps", 1085, 697, 250, "#F4F1EA", "Sets policy, approvals and caps."),
]
HUB = ("cerebro", "Cerebro", "The strategist: writes policy in plain language.")
# nodes it joins, path, label, label centre x, y, label box width
E = [
 ("game rec", "M1655 560 L1700 560 L1700 30 L170 30 L170 77", "feed", 923, 30, 86, True),
 ("rec cerebro", "M170 120 L864 390", "events", 517, 254, 90, False),
 ("signals cerebro", "M170 300 L864 390", "news", 517, 344, 66, False),
 ("cerebro council", "M864 390 L864 90", "vote", 864, 239, 66, False),
 ("cerebro fast", "M864 390 L1230 150", "policies", 1047, 269, 114, False),
 ("fast rails", "M1230 150 L1540 150", "orders", 1385, 149, 90, False),
 ("rails exec", "M1540 150 L1540 350", "pass / veto", 1540, 249, 150, False),
 ("exec game", "M1540 350 L1540 560", "offers", 1540, 454, 90, False),
 ("rec lab", "M170 120 L170 660", "replay", 170, 389, 90, False),
 ("lab cerebro", "M170 660 L864 390", "lessons", 517, 524, 102, False),
 ("cerebro workshop", "M864 390 L520 700", "tickets · fixes", 692, 544, 198, False),
 ("dash cerebro", "M864 700 L864 390", "state", 864, 590, 78, False),
 ("human dash", "M1210 740 L864 700", "sees", 1037, 719, 66, False),
 ("human cerebro", "M1210 740 L864 390", "approvals", 1131, 660, 126, False),   # moved off "overlay"
 ("fast duels", "M1230 150 L1230 380", "duels", 1230, 264, 78, False),
 ("cerebro broker", "M864 390 L1230 580", "overlay", 1104, 512, 102, False),      # moved off the hub's edge
 ("market cerebro", "M170 480 L864 390", "matches", 517, 434, 102, False),
]
PULSES = [  # the deck's five dots: tick, improve, repair, human (two)
 (9, "#F4F1EA", 7, "M170 120 L864 390 L1230 150 L1540 150 L1540 350 L1540 560 L1700 560 L1700 30 L170 30 L170 120"),
 (7, "#45B883", 5, "M170 120 L170 660 L864 390"),
 (7, "#E2564D", 5, "M864 390 L520 700 L864 390"),
 (7, "#E3A33B", 5, "M1210 740 L864 700 L864 390"),
 (6, "#E3A33B", 4, "M1210 740 L864 390"),
]
T0 = 1.86  # the pulses start once the map has drawn itself
# The entrance radiates from the centre: ring 1 is every part joined to Cerebro (nearest first), ring 2 the rest.
def _len(d):
    p = [float(x) for x in d.replace("M", " ").replace("L", " ").split()]
    return sum(((p[i + 2] - p[i]) ** 2 + (p[i + 3] - p[i + 1]) ** 2) ** .5 for i in range(0, len(p) - 2, 2))
R1 = sorted((e for e in E if "cerebro" in e[0].split()), key=lambda e: _len(e[1]))
J1 = {e[0]: j for j, e in enumerate(R1)}
NJ1 = {(set(e[0].split()) - {"cerebro"}).pop(): j for j, e in enumerate(R1)}
J2 = {"fast rails": 0, "fast duels": 0, "rec lab": 1, "human dash": 1, "rails exec": 2, "exec game": 3, "game rec": 4}
NJ2 = {"rails": 0, "duels": 0, "exec": 2, "game": 3}
def edge(n, d, dash):
    if n in J1: cls, j = " r1" + ("" if n.split()[0] == "cerebro" else " rev"), J1[n]
    else: cls, j = " r2", J2[n]
    return '<path class="e%s%s" style="--j:%d" data-n="%s" %sd="%s"/>' % (cls, " dash" if dash else "", j, n, "" if dash else 'pathLength="1" ', d)
edges = "".join(edge(n, d, dash) for (n, d, _, _, _, _, dash) in E)
labels = "".join('<g class="lb" data-n="%s"><rect x="%d" y="%d" width="%d" height="28"/><text x="%d" y="%d">%s</text></g>' % (n, x - w // 2, y - 14, w, x, y + 7, html.escape(t))
                 for (n, _, t, x, y, w, _) in E)
pulses = "".join('<circle class="p" r="%d" fill="%s" opacity="0"><set attributeName="opacity" to="1" begin="%.1fs" fill="freeze"/><animateMotion dur="%ds" begin="%.1fs" repeatCount="indefinite" path="%s"/></circle>' % (r, c, T0, d, T0, p)
                 for (r, c, d, p) in PULSES)
def node(o, n):
    i, t, s, x, y, w, c, d = n
    hum = i == "human"
    ring, j = (" r1", NJ1[i]) if i in NJ1 else (" r2", NJ2[i])
    return ('<g class="n%s%s" tabindex="0" role="img" aria-label="%s: %s" data-id="%s" data-name="%s" data-d="%s" style="--j:%d;--k:%s">'
            '<rect class="nb" x="%d" y="%d" width="%d" height="86"%s/><rect class="nk" x="%d" y="%d" width="8" height="86"/>'
            '<text class="nt" x="%d" y="%d">%s</text><text class="ns" x="%d" y="%d">%s</text></g>'
            % (ring, " hum" if hum else "", html.escape(t), html.escape(d), i, html.escape(t), html.escape(d), j, c, x, y, w,
               ' stroke-dasharray="6 6"' if i == "game" else "", x, y, x + 24, y + 39, html.escape(t), x + 24, y + 67, html.escape(s)))
nodes = "".join(node(o, n) for o, n in enumerate(N))
hub = ('<g class="n hubn" tabindex="0" role="img" aria-label="%s: %s" data-id="cerebro" data-name="%s" data-d="%s" style="--k:#E3A33B">'
       '<rect class="nb" x="674" y="300" width="380" height="180"/><text class="ct" x="864" y="398">CEREBRO</text>'
       '<text class="ns" x="864" y="442">strategist · policy in plain language</text></g>'
       % (HUB[1], html.escape(HUB[2]), HUB[1], html.escape(HUB[2])))
MAP = ('<svg class="net" viewBox="30 6 1686 788" preserveAspectRatio="xMidYMid meet" role="group" aria-label="System map: Cerebro in the centre, connected to recorder, signals watcher, council, lab, fast loop, rails, executor, duels, broker, workshop, dashboard, market and the human">'
       '<g class="es">%s</g><g class="lbs" aria-hidden="true">%s</g><g class="ps" aria-hidden="true">%s</g><g class="ns_">%s%s</g></svg>') % (edges, labels, pulses, nodes, hub)
PARTS = "".join('<li style="--k:%s"><b>%s</b><span>%s</span></li>' % (c, html.escape(t), html.escape(d)) for (_, t, _, _, _, _, c, d) in [(HUB[0], HUB[1], "", 0, 0, 0, "#E3A33B", HUB[2])] + N)
LEGEND = ('<span class="legend" aria-hidden="true"><i style="--t:#F4F1EA">tick</i><i style="--t:#45B883">improve</i><i style="--t:#E2564D">repair</i><i style="--t:#E3A33B">human in the loop</i></span>')

def ic(body): return '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true">%s</svg>' % body
I_REPO = ic('<path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.6 4.5l-3.2 15"/>')
I_DASH = ic('<rect x="3" y="4" width="18" height="16"/><path d="M3 9.5h18M9.5 9.5V20"/>')
I_MKT = ic('<path d="M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4"/>')
I_VID = ic('<rect x="3" y="5" width="18" height="14"/><path d="M10 9.2v5.6l5-2.8z"/>')
I_PIT = ic('<rect x="3" y="4" width="18" height="12"/><path d="M12 16v4M8 20h8"/>')
ARROW = '<svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
ARROW_UP = '<svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9"/></svg>'
def row(r, cls, href, icon, title, tag, line, extra="", arrow=ARROW, ext=False):
    t = '<em>%s</em>' % tag if tag else ""
    rel = ' rel="noopener"' if ext else ""
    return ('<a style="--r:%d" class="row %s" href="%s"%s>%s<span class="tx"><span class="nm"><b>%s</b>%s</span><span class="ds">%s</span>%s</span>%s</a>'
            % (r, cls, href, rel, icon, title, t, line, extra, arrow))
ROWS = "".join([
 row(0, "repo", "https://github.com/aaangelmartin/Cerebro", I_REPO, "GitHub repo", "", "All the code, the docs and the story of the weekend.",
     '<span class="url">github.com/aaangelmartin/Cerebro</span>', ARROW_UP, True),
 row(1, "", "dashboard/", I_DASH, "Dashboard", "Frozen snapshot", "What the team watched: the Brain, the bot, duels and the lab."),
 row(2, "", "market/", I_MKT, "v07 Market", "Frozen snapshot", "The market we built for other teams' agents."),
 row(3, "", "video/", I_VID, "Video", "", "How we built it and how it works inside, in three minutes."),
 row(4, "", "pitch/", I_PIT, "Pitch deck", "", "The pitch that won, slide by slide."),
])

CSS = r"""
/* A still ground: the product black. The two panels carry the grid. */
main{z-index:1}

/* Below the poster: the system map from the pitch deck on the left, where to go on the right. */
.below{flex:1 1 0;min-height:0;display:grid;grid-template-columns:minmax(0,2.72fr) minmax(0,1fr);gap:var(--gap)}
.works{min-width:0;min-height:0;display:flex;flex-direction:column;background:var(--bg);border:1px solid var(--line);position:relative;overflow:hidden}
.works::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:44px 44px;opacity:.34;-webkit-mask-image:radial-gradient(90% 90% at 50% 45%,#000 20%,transparent 100%);mask-image:radial-gradient(90% 90% at 50% 45%,#000 20%,transparent 100%)}
.net{position:relative;flex:1 1 0;min-height:0;width:100%;display:block;padding:clamp(6px,1.2vh,14px) clamp(6px,.8vw,14px) clamp(2px,.6vh,8px)}
.net .e{fill:none;stroke:#2D323A;stroke-width:2;transition:stroke .16s,opacity .16s,stroke-width .16s}
.net .e.dash{stroke-dasharray:6 6}
.net .lb rect{fill:var(--bg)}
.net .lb text{font-family:var(--font-num);font-size:19px;fill:#A4ABB3;text-anchor:middle;transition:fill .16s}
.net .lb{transition:opacity .16s}
.net .n{cursor:default;outline:none;transition:opacity .16s}
.net .nb{fill:#0E1013;stroke:#2D323A;stroke-width:1;transition:stroke .16s,fill .16s}
.net .nk{fill:var(--k)}
.net .nt{font-family:var(--font-ui);font-weight:700;font-size:28px;fill:#ECEEF0}
.net .ns{font-family:var(--font-ui);font-size:19px;fill:#A4ABB3}
.net .hum .nb{fill:#F4F1EA}.net .hum .nt,.net .hum .ns{fill:#08090B}
.net .hubn .nb{fill:#14171B;stroke:#E3A33B;stroke-width:3}
.net .hubn .ns{fill:#E3A33B;text-anchor:middle}
.net .hubn{transform-box:fill-box;transform-origin:50% 50%}
.net .ct{font-family:var(--font-display);font-weight:800;font-size:96px;fill:#ECEEF0;letter-spacing:.01em;text-anchor:middle}
/* Hover or focus a part: its lines light up, the rest steps back. */
.net.focus .e{opacity:.22}.net.focus .lb{opacity:.2}.net.focus .n{opacity:.42}
.net.focus .e.on{opacity:1;stroke:#ECEEF0;stroke-width:2.6}
.net.focus .lb.on{opacity:1}.net.focus .lb.on text{fill:#ECEEF0}
.net.focus .n.on,.net.focus .n.near{opacity:1}
.net .n.on .nb,.net .n:focus-visible .nb{stroke:var(--k);stroke-width:2.5}
.net .hum.on .nb,.net .hum:focus-visible .nb{stroke:#E3A33B;stroke-width:4}
.net .hubn.on .nb{stroke-width:4.5}
.cap{position:relative;flex:none;display:flex;align-items:baseline;gap:12px;min-height:clamp(34px,5.2vh,46px);padding:clamp(7px,1.15vh,11px) clamp(12px,1.3vw,20px);border-top:1px solid var(--line);background:var(--s1);font-size:clamp(13px,1.05vw,16px);line-height:1.25;white-space:nowrap;overflow:hidden}
.cap b{font-weight:700;letter-spacing:-.01em;color:var(--ink);flex:none}
.cap .d{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;min-width:0}
.cap.idle b{font-size:1.06em}
.legend{margin-left:auto;flex:none;display:flex;gap:clamp(10px,1.1vw,18px);padding-left:14px;font-family:var(--font-num);font-size:clamp(10px,.78vw,12px);letter-spacing:.02em;color:var(--ink-2)}
.legend i{font-style:normal;display:inline-flex;align-items:center;gap:7px}
.legend i::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--t);flex:none}
.parts{display:none}

nav.go{min-width:0;min-height:0;display:grid;grid-template-rows:minmax(0,1.5fr) repeat(4,minmax(0,1fr));gap:var(--gap)}
.row{position:relative;min-width:0;min-height:0;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;column-gap:clamp(11px,1.05vw,17px);padding:0 clamp(13px,1.25vw,20px);background:var(--s1);border:1px solid var(--line);color:var(--ink);overflow:hidden;transition:border-color .14s,background .14s}
.row::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--ink);transform:scaleY(0);transform-origin:50% 100%;transition:transform .2s cubic-bezier(.2,.75,.2,1)}
.row:hover,.row:focus-visible{border-color:var(--ink-3);background:var(--s2)}
.row:hover::before,.row:focus-visible::before{transform:scaleY(1)}
.row:focus-visible{outline:1px solid var(--signal);outline-offset:3px}
.row .ic{width:clamp(19px,1.5vw,23px);height:clamp(19px,1.5vw,23px);color:var(--ink-2);flex:none;transition:color .14s}
.row:hover .ic,.row:focus-visible .ic{color:var(--ink)}
.row .tx{min-width:0;display:flex;flex-direction:column;gap:3px}
.row .nm{display:flex;align-items:center;flex-wrap:wrap;gap:3px 10px;min-width:0}
.row b{font-size:clamp(15.5px,1.32vw,20px);font-weight:700;letter-spacing:-.018em;line-height:1.1;white-space:nowrap}
.row em{display:inline-flex;align-items:center;gap:6px;font-style:normal;font-family:var(--font-num);font-size:clamp(8.5px,.66vw,10px);letter-spacing:.08em;text-transform:uppercase;color:var(--ok);white-space:nowrap}
.row em::before{content:"";width:6px;height:6px;background:currentColor;flex:none}
.row .ds{font-size:clamp(11.5px,.88vw,13px);line-height:1.3;color:var(--ink-2);display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.row svg.go{width:17px;height:17px;color:var(--ink-3);flex:none;transition:transform .16s,color .14s}
.row:hover svg.go,.row:focus-visible svg.go{color:var(--ink);transform:translateX(5px)}
.row.repo{background:var(--signal);border-color:var(--signal);color:var(--bg)}
.row.repo::before{background:var(--bg);width:3px}
.row.repo:hover,.row.repo:focus-visible{background:#fff;border-color:#fff}
.row.repo:focus-visible{outline-color:var(--ok)}
.row.repo .ic{width:clamp(22px,1.8vw,28px);height:clamp(22px,1.8vw,28px);color:var(--bg)}
.row.repo b{font-size:clamp(20px,1.95vw,29px);font-weight:800;letter-spacing:-.03em;line-height:1}
.row.repo .ds{color:#2D323A;font-size:clamp(11.5px,.9vw,13.5px)}
.row.repo .url{font-family:var(--font-num);font-size:clamp(9.5px,.72vw,11px);letter-spacing:.01em;color:#1C2026;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.repo svg.go{width:21px;height:21px;color:var(--bg)}
.row.repo:hover svg.go,.row.repo:focus-visible svg.go{color:var(--bg);transform:translate(3px,-3px)}

@media (min-width:901px) and (max-height:760px){.row .ds{display:none}.row.repo .ds{display:-webkit-box;-webkit-line-clamp:1}.row.repo .url{display:none}.cap{min-height:32px}}
@media (min-width:901px) and (max-width:1180px){.legend i:nth-child(n+2){display:none}.legend{display:none}}
@media (min-width:901px) and (max-height:600px){.poster{max-height:33dvh;min-height:0}.row.repo .ds{display:none}}

@media (max-width:900px){
  /* Phone and narrow tablet: the page scrolls; poster, doors, then the parts as a list. */
  html,body{height:auto;overflow:visible;overflow-x:hidden}
  body{height:auto;min-height:100dvh}
  main{height:auto;max-height:none;top:auto;transform:none;justify-content:flex-start;padding:14px 14px 22px}
  .poster{aspect-ratio:auto;max-height:none;height:clamp(200px,34dvh,300px)}
  .meta span{display:block}.meta .dot{display:none}
  .poster .fade{background:linear-gradient(180deg,var(--s1) 0%,rgba(14,16,19,.85) 55%,transparent 100%)}
  .poster .glow{right:-20cqw;top:30cqh;width:140cqw;height:120cqh}
  .words{left:6cqw;right:4cqw;justify-content:flex-start;padding-top:8cqh;gap:min(3.6cqh,2.4cqw)}
  .tag{font-size:min(4.6cqh,2.75cqw);letter-spacing:.12em}
  h1{font-size:min(27cqh,17cqw)}
  .sub{font-size:min(8.4cqh,5.6cqw)}
  .meta{font-size:min(4.4cqh,2.9cqw);white-space:normal;line-height:1.5}
  .cards{right:auto;left:50%;top:auto;bottom:-13cqh;transform:translateX(-50%);--cw:min(13.5cqw,24cqh)}
  .below{display:flex;flex-direction:column-reverse;flex:none}
  nav.go{grid-template-rows:none;grid-auto-rows:auto}
  .row{padding:13px 14px;column-gap:14px}
  .row .ic{width:22px;height:22px}
  .row.repo{padding:16px 14px}
  .row.repo .url{display:none}
  .works::before{display:none}
  .net{display:none}
  .cap{white-space:normal;flex-direction:column;gap:2px;padding:14px;border-top:0;border-bottom:1px solid var(--line)}
  .cap .d,.legend{display:none}
  .parts{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1px;list-style:none;padding:0;background:var(--line)}
  .parts li{background:var(--s1);border-left:2px solid var(--k);padding:9px 10px;display:flex;flex-direction:column;gap:2px;min-width:0}
  .parts li:first-child{grid-column:1/-1}
  .parts b{font-size:13.5px;font-weight:700}
  .parts span{font-size:12px;line-height:1.3;color:var(--ink-2)}
}

%%MOTION%%
@media (prefers-reduced-motion:reduce){.row,.row svg,.row::before,.c,.net *{transition:none}.net .ps{display:none}}
"""

JS = r"""
(function () {
  /* The map: hover or focus a part to see what it does and what it talks to. */
  var map = document.querySelector('.net'), cap = document.querySelector('.cap');
  if (!map || !cap) return;
  var cb = cap.querySelector('b'), cs = cap.querySelector('.d'), idleB = cb.textContent, idleS = cs.textContent;
  var links = map.querySelectorAll('.e,.lb'), nodes = map.querySelectorAll('.n');
  function show(n) {
    var id = n.getAttribute('data-id'), near = {};
    map.classList.add('focus'); n.classList.add('on');
    links.forEach(function (l) {
      var ids = l.getAttribute('data-n').split(' ');
      if (ids.indexOf(id) > -1) { l.classList.add('on'); ids.forEach(function (x) { near[x] = 1; }); }
    });
    nodes.forEach(function (m) { if (near[m.getAttribute('data-id')]) m.classList.add('near'); });
    cb.textContent = n.getAttribute('data-name'); cs.textContent = n.getAttribute('data-d'); cap.classList.remove('idle');
  }
  function hide() {
    map.classList.remove('focus');
    map.querySelectorAll('.on,.near').forEach(function (x) { x.classList.remove('on'); x.classList.remove('near'); });
    cb.textContent = idleB; cs.textContent = idleS; cap.classList.add('idle');
  }
  nodes.forEach(function (n) {
    n.addEventListener('mouseenter', function () { hide(); show(n); });
    n.addEventListener('mouseleave', hide);
    n.addEventListener('focus', function () { hide(); show(n); });
    n.addEventListener('blur', hide);
  });
  document.addEventListener('visibilitychange', function () {
    try { document.hidden ? map.pauseAnimations() : map.unpauseAnimations(); } catch (e) {}
  });
})();
"""


# ---- the entrance: 2 s in all. Poster first, Cerebro at the centre of the map, then its lines out to each part. ----
E1 = "cubic-bezier(.2,.8,.2,1)"; DASH = "stroke-dasharray:1;"
SCALE = 2 / 2.362  # the timeline below is written for 2.362 s and scaled to exactly 2 s
D = .27            # base duration of the map's steps
# selector, keyframes, duration, delay, step, step variable, easing, extra
TIMELINE = [
 (".poster .bar", "bar", .42, 0, 0, "", E1, ""), (".poster .grid", "gridin", .5, .06, 0, "", "ease-out", ""), (".tag", "sweep", .4, .1, 0, "", E1, ""),
 ("h1 .w", "rise", .5, .18, 0, "", E1, ""), ("h1 .d", "drop", .36, .7, 0, "", E1, ""), (".sub", "up", .42, .34, 0, "", E1, ""), (".meta", "up", .42, .42, 0, "", E1, ""),
 (".c", "deal", .48, .3, .07, "--i", E1, ""), (".poster .glow", "glowin", .6, .6, 0, "", "ease-out", ""),
 (".row", "wipe", .44, .6, .04, "--r", E1, ""),
 (".works", "frame", D, .3 - D * .6, 0, "", "ease-out", ""),
 (".net .hubn", "hubin", D * 1.25, .3, 0, "", E1, ""), (".net .hubn .nb", "amber", D * 1.8, .3 + D * .3, 0, "", "ease-out", ""),
 (".net .e.r1:not(.rev)", "draw", D, .75, .022, "--j", E1, DASH), (".net .e.r1.rev", "drawr", D, .75, .022, "--j", E1, DASH),
 (".net .n.r1>*", "pop", D, .75 + D * .7, .022, "--j", E1, ""),
 (".net .e.r2:not(.dash)", "draw", D, 1.2, .09, "--j", E1, DASH), (".net .e.r2.dash", "fadein", D, 1.2, .09, "--j", "ease-out", ""),
 (".net .n.r2>*", "pop", D, 1.2 + D * .7, .09, "--j", E1, ""),
 (".net .lbs", "fadein", D, 1.7, 0, "", "ease-out", ""), (".net .ps", "fadein", D * .6, 2.2, 0, "", "ease-out", ""), (".cap", "fadein", D, .9, 0, "", "ease-out", ""),
]
def _s(x): return ("%.3f" % (x * SCALE)).rstrip("0").rstrip(".") + "s"
def motion():
    out = ["/* Motion: one entrance, about two seconds, then only the map's pulses and the cards' slow sheen keep moving. */",
           "@media (prefers-reduced-motion:no-preference){"]
    for sel, kf, dur, delay, step, var, ease, extra in TIMELINE:
        dl = "calc(%s + var(%s)*%s)" % (_s(delay), var, _s(step)) if step else _s(delay)
        out.append("  %s{%sanimation:%s %s %s backwards;animation-delay:%s}" % (sel, extra, kf, _s(dur), ease, dl))
    out.append("  .c .sheen{animation:sheen 9s linear infinite;animation-delay:calc(3s + var(--i)*.22s)}")
    out += ["  @keyframes bar{from{transform:scaleY(0)}to{transform:scaleY(1)}}",
            "  @keyframes gridin{from{opacity:0}to{opacity:.5}}",
            "  @keyframes sweep{from{transform:translateX(-102%)}to{transform:translateX(0)}}",
            "  @keyframes rise{from{transform:translateY(108%)}to{transform:translateY(0)}}",
            "  @keyframes drop{from{transform:translateY(-140%);opacity:0}to{transform:translateY(0);opacity:1}}",
            "  @keyframes up{from{transform:translateY(14px);opacity:0}to{transform:translateY(0);opacity:1}}",
            "  /* The cards are never transparent: they slide up from under the poster, which clips them. */",
            "  @keyframes deal{from{transform:translateY(calc(330*var(--cw)/140)) rotate(0deg)}to{transform:translateY(calc(var(--y)*var(--cw)/140)) rotate(var(--r))}}",
            "  @keyframes glowin{from{opacity:0}to{opacity:1}}",
            "  @keyframes sheen{0%{transform:translateX(-130%)}16%{transform:translateX(130%)}100%{transform:translateX(130%)}}",
            "  @keyframes frame{from{opacity:0}to{opacity:1}}",
            "  @keyframes hubin{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}",
            "  @keyframes amber{from{stroke:#2D323A}to{stroke:#E3A33B}}",
            "  @keyframes pop{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}",
            "  @keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}",
            "  @keyframes drawr{from{stroke-dashoffset:-1}to{stroke-dashoffset:0}}",
            "  @keyframes fadein{from{opacity:0}to{opacity:1}}",
            "  @keyframes wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}", "}"]
    return "\n".join(out)

BELOW = "\n".join([
 '  <div class="below">',
 '    <section class="works" aria-label="How Cerebro works">' + MAP,
 '      <p class="cap idle"><b>The model proposes. The code disposes.</b><span class="d">Point at a part to see what it does.</span>' + LEGEND + '</p>',
 '      <ul class="parts" aria-label="The parts of Cerebro">' + PARTS + '</ul>',
 '    </section>',
 '    <nav class="go" aria-label="Where to go">' + ROWS + '</nav>',
 '  </div>'])
page = TEMPLATE.replace("/*__CSS__*/", CSS.replace("%%MOTION%%", motion())).replace("<!--__BELOW__-->", BELOW).replace("/*__JS__*/", JS)
open(OUT, "w", encoding="utf-8").write(page)
print("wrote", OUT, len(page.encode()), "bytes")
