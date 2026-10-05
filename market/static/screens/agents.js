// agents: AGENTS.md as a page. The document is written by the server (agentsdoc.py); this screen only draws it:
// an index on the left, the text in mono, the raw address and a button to copy it whole.
(function () {
  "use strict";
  const { el } = K;

  /** Inline marks of a line: `code` and **bold**. Everything is written as text nodes. */
  function inline(text) {
    const out = [];
    const rx = /(`[^`]+`|\*\*[^*]+\*\*)/g;
    let last = 0, m;
    while ((m = rx.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(m[0][0] === "`" ? el("code", { class: "agents-code" }, m[0].slice(1, -1)) : el("b", null, m[0].slice(2, -2)));
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const slug = (n) => "agents-s" + n;

  /** A small reader of the Markdown the server writes: headings, fences, lists, tables, paragraphs. */
  function parse(md) {
    const blocks = [], toc = [];
    const lines = md.replace(/\r\n?/g, "\n").split("\n");
    let i = 0, n = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++;
        blocks.push(el("pre", { class: "agents-pre", tabindex: "0" }, code.join("\n")));
        continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(line);
      if (h) {
        const level = h[1].length, id = slug(++n), text = h[2];
        blocks.push(el("h" + Math.min(4, level + 1), { class: "agents-h agents-h" + level, id }, inline(text)));
        if (level <= 3) toc.push({ level, id, text: text.replace(/[`*]/g, "") });
        i++;
        continue;
      }
      if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        const head = cells(line), rows = [];
        i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
        blocks.push(el("div", { class: "agents-tablebox" }, el("table", { class: "table agents-table" },
          el("thead", null, el("tr", null, head.map((c) => el("th", null, inline(c))))),
          el("tbody", null, rows.map((r) => el("tr", null, r.map((c) => el("td", null, inline(c)))))))));
        continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), items = [];
        while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
          if (/^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
          else items[items.length - 1] += " " + lines[i].trim();
          i++;
        }
        blocks.push(el(ordered ? "ol" : "ul", { class: "agents-list" }, items.map((it) => el("li", null, inline(it)))));
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|\s*\||\s*([-*]|\d+\.)\s+)/.test(lines[i])) para.push(lines[i++].trim());
      blocks.push(el("p", { class: "agents-p" }, inline(para.join(" "))));
    }
    return { blocks, toc };
  }

  Plaza.screen("agents", {
    title: "nav.agents",
    noOverlay: true,
    render(root) {
      const raw = location.origin + "/Cerebro/market/AGENTS.md";
      let text = null, left = false;
      const copyBtn = K.btn(t("agents.copy"), { kind: "primary", icon: "copy", disabled: true, onclick: () => { if (text) K.copy(text, t("agents.copied")); } });
      root.appendChild(el("header", { class: "page-head agents-head" },
        el("div", null, el("h1", { class: "page-title agents-title" }, "AGENTS.md"), el("p", { class: "page-sub" }, t("agents.sub"))),
        el("div", { class: "agents-actions" }, el("a", { class: "agents-raw", href: "/Cerebro/market/AGENTS.md", target: "_blank", rel: "noopener", title: t("agents.raw") }, raw), copyBtn)));
      const cols = root.appendChild(el("div", { class: "agents-cols" }));
      // The index: a column on a wide screen, a fold at full width above the document on a phone.
      const wide = window.matchMedia("(min-width: 761px)").matches;
      const fold = cols.appendChild(el("details", { class: "agents-fold", open: wide ? "" : null }, el("summary", { class: "agents-fold-sum" }, K.icon("chevron", 14), t("agents.index"))));
      const toc = fold.appendChild(el("nav", { class: "agents-toc", "aria-label": t("agents.index") }));
      const doc = cols.appendChild(el("article", { class: "agents-doc" }, K.state("loading")));
      root.appendChild(K.endpoint("GET /Cerebro/market/AGENTS.md", "GET /Cerebro/market/api/openapi.json"));

      function load() {
        K.clear(doc).appendChild(K.state("loading"));
        API.text("/AGENTS.md").then((md) => {
          if (left) return;
          text = String(md || "");
          if (!text.trim()) { K.clear(doc).appendChild(K.state("empty", null, t("agents.empty"))); return; }
          copyBtn.disabled = false;
          const parsed = parse(text);
          K.add(K.clear(doc), parsed.blocks);
          K.add(K.clear(toc), parsed.toc.filter((h) => h.level > 1).map((h) => el("a", { class: "agents-toc-item lv" + h.level, href: "#" + h.id, onclick: (e) => {
            e.preventDefault();
            const target = document.getElementById(h.id);
            if (!wide) fold.removeAttribute("open");
            if (target) target.scrollIntoView({ block: "start" });
            toc.querySelectorAll(".active").forEach((a) => a.classList.remove("active"));
            e.currentTarget.classList.add("active");
          } }, h.text)));
        }, (e) => {
          if (left) return;
          K.clear(doc).appendChild(K.state("error", null, (e && e.message) || t("agents.failed"), K.btn(t("common.retry"), { small: true, onclick: load })));
        });
      }
      load();
      return () => { left = true; };
    },
  });
})();
