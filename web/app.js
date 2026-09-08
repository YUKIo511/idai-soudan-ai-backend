// 偉人相談AI — スマホファースト SPA（ビルド不要）
// Knowledge Base はフロントに持たない。すべてバックエンド API 経由。

const app = document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `エラー (${res.status})`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// ---------------- ルーター ----------------
function parseHash() {
  const h = location.hash.replace(/^#/, "") || "/";
  const m = h.match(/^\/c\/([\w-]+)$/) || h.match(/^\/chat\/([\w-]+)$/);
  if (h.startsWith("/chat/")) return { name: "chat", slug: m[1] };
  if (h.startsWith("/c/")) return { name: "detail", slug: m[1] };
  return { name: "list" };
}
window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", render);

function render() {
  const r = parseHash();
  if (r.name === "list") return viewList();
  if (r.name === "detail") return viewDetail(r.slug);
  if (r.name === "chat") return viewChat(r.slug);
}

// ---------------- 一覧 ----------------
let _cache = null;      // {characters:[...]}
let _filter = { q: "", cat: null };

async function viewList() {
  app.innerHTML = `<div class="page container">
    <div class="hero">
      <span class="badge">歴史上の偉人に相談する</span>
      <h1>偉人に、相談する。</h1>
      <p>その人の人生・思想・失敗・言葉をもとに、AIが「その人ならどう考えるか」を返します。</p>
    </div>
    <div class="search">
      <input id="q" type="search" inputmode="search" placeholder="名前・職業でさがす" value="${esc(_filter.q)}">
    </div>
    <div class="chips" id="chips"></div>
    <div id="list" class="grid"></div>
  </div>`;

  const listEl = document.getElementById("list");
  if (!_cache) {
    listEl.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
    try { _cache = await api("/characters"); }
    catch (e) { listEl.innerHTML = `<div class="error">${esc(e.message)}</div>`; return; }
  }
  const cats = [...new Set(_cache.characters.flatMap((c) => c.categories || []))].sort();
  const chips = document.getElementById("chips");
  chips.innerHTML = [`<button class="chip" data-cat="" aria-pressed="${!_filter.cat}">すべて</button>`]
    .concat(cats.map((c) => `<button class="chip" data-cat="${esc(c)}" aria-pressed="${_filter.cat === c}">${esc(c)}</button>`))
    .join("");
  chips.onclick = (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    _filter.cat = b.dataset.cat || null; drawList();
  };
  document.getElementById("q").oninput = (e) => { _filter.q = e.target.value; drawList(); };
  drawList();
}

function drawList() {
  const listEl = document.getElementById("list");
  const q = _filter.q.trim().toLowerCase();
  const items = _cache.characters.filter((c) => {
    if (_filter.cat && !(c.categories || []).includes(_filter.cat)) return false;
    if (!q) return true;
    return [c.name, c.name_en, c.occupation, c.one_line, ...(c.categories || [])]
      .filter(Boolean).some((s) => s.toLowerCase().includes(q));
  });
  if (!items.length) { listEl.innerHTML = `<div class="state">該当する偉人がいません</div>`; return; }
  listEl.innerHTML = items.map((c) => `
    <a class="card" href="#/c/${encodeURIComponent(c.slug)}">
      <div class="avatar">${c.portrait ? `<img src="${esc(c.portrait)}" alt="">` : esc(c.icon)}</div>
      <div>
        <h3>${esc(c.name)}</h3>
        <p class="role">${esc(c.occupation || c.era || "")}</p>
        <p class="desc">${esc(c.one_line)}</p>
        ${(c.categories || []).slice(0, 1).map((t) => `<span class="cat">${esc(t)}</span>`).join("")}
      </div>
    </a>`).join("");
}

// ---------------- 偉人詳細 ----------------
async function viewDetail(slug) {
  app.innerHTML = `<div class="page container"><div class="state">読み込み中…</div></div>`;
  let d;
  try { d = await api(`/characters/${encodeURIComponent(slug)}`); }
  catch (e) {
    app.innerHTML = `<div class="page container"><a class="back" href="#/">← 一覧へ</a>
      <div class="error">${esc(e.message)}</div></div>`; return;
  }
  const sec = (title, body) => body ? `<div class="section"><h2>${title}</h2>${body}</div>` : "";
  const tl = (d.timeline || []).map((t) => `<li><span class="y">${esc(t.year || "")}</span>
    ${t.age != null ? ` ・${t.age}歳` : ""}<br>${esc(t.title)}${t.summary ? `<br><span style="color:var(--ink-soft)">${esc(t.summary)}</span>` : ""}</li>`).join("");
  const ach = (d.achievements || []).map((a) => `<p><b>${esc(a.title)}</b>${a.year ? `（${esc(a.year)}）` : ""}<br>
    <span style="color:var(--ink-soft)">${esc(a.summary)}</span></p>`).join("");
  const phil = (d.philosophy || []).map((p) => `<p><b>${esc(p.title || p.domain)}</b><br>
    <span style="color:var(--ink-soft)">${esc(p.view)}</span></p>`).join("");
  const quotes = (d.quotes || []).map((qq) => `<div class="quote">「${esc(qq.text)}」
    ${qq.context ? `<small>${esc(qq.context)}</small>` : ""}
    <small>帰属: ${esc(qq.attribution_status)}${qq.source_ids?.length ? ` ／ 出典: ${esc(qq.source_ids.join(", "))}` : ""}</small></div>`).join("");

  app.innerHTML = `<div class="page container">
    <a class="back" href="#/">← 一覧へ</a>
    <div class="detail-head">
      <div class="avatar">${d.portrait ? `<img src="${esc(d.portrait)}" alt="">` : esc(d.icon)}</div>
      <div><h1>${esc(d.name)}</h1><p class="role">${esc([d.occupation, d.era].filter(Boolean).join(" ・ "))}</p></div>
    </div>
    ${sec("人物紹介", d.intro ? `<p>${esc(d.intro)}</p>` : "")}
    ${sec("生涯", tl ? `<ul class="tl">${tl}</ul>` : "")}
    ${sec("主な実績", ach)}
    ${sec("思想", phil)}
    ${sec("代表的な名言", quotes)}
    ${d.categories?.length ? sec("カテゴリー", `<div class="tag-list">${d.categories.map((t) => `<span>${esc(t)}</span>`).join("")}</div>`) : ""}
    <div class="cta">
      <button class="btn" onclick="location.hash='#/chat/${encodeURIComponent(slug)}'">この偉人に相談する</button>
    </div>
  </div>`;
}

// ---------------- チャット ----------------
const _threads = {};  // slug -> [{role, content, cites?}]

async function viewChat(slug) {
  let head;
  try { head = await api(`/characters/${encodeURIComponent(slug)}`); }
  catch (e) {
    app.innerHTML = `<div class="page container"><a class="back" href="#/">← 一覧へ</a>
      <div class="error">${esc(e.message)}</div></div>`; return;
  }
  if (!_threads[slug]) _threads[slug] = [];

  app.innerHTML = `<div class="chat">
    <div class="chat-head">
      <a class="back" href="#/c/${encodeURIComponent(slug)}">←</a>
      <div class="avatar">${head.portrait ? `<img src="${esc(head.portrait)}" alt="">` : esc(head.icon)}</div>
      <div><div class="name">${esc(head.name)}</div><div class="sub">${esc(head.occupation || head.era || "")}</div></div>
    </div>
    <div class="chat-log" id="log"></div>
    <form class="composer" id="composer">
      <textarea id="input" rows="1" placeholder="相談を入力…" enterkeyhint="send"
        autocapitalize="sentences" autocomplete="off"></textarea>
      <button type="submit" id="send" aria-label="送信">➤</button>
    </form>
  </div>`;

  const log = document.getElementById("log");
  const input = document.getElementById("input");
  const form = document.getElementById("composer");
  const sendBtn = document.getElementById("send");

  const paint = () => {
    log.innerHTML = _threads[slug].map((m) => {
      if (m.role === "user") return `<div class="msg user">${esc(m.content)}</div>`;
      const cites = m.cites?.length ? `<details class="cites"><summary>参照した資料 ${m.cites.length} 件</summary>
        <ul>${m.cites.map((c) => `<li><span class="rel">[${esc(jpRel(c.reliability))}${c.attribution_status ? "／" + esc(c.attribution_status) : ""}]</span>
          ${esc(c.title)} <span style="opacity:.7">(${esc(c.ref)})</span></li>`).join("")}</ul></details>` : "";
      const cls = m.pending ? "msg bot thinking" : "msg bot";
      const body = m.content ? esc(m.content) : `<span class="dots">考え中</span>`;
      return `<div class="${cls}">${body}</div>${cites}`;
    }).join("");
    log.scrollTop = log.scrollHeight;
  };
  if (_threads[slug].length) paint();

  // 入力欄の自動リサイズ
  const grow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 120) + "px"; };
  input.addEventListener("input", grow);
  // Enter で送信 / Shift+Enter で改行（ソフトキーボードの「送信」も Enter を発火）
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // 送信
  let busy = false;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    _threads[slug].push({ role: "user", content: text });
    input.value = ""; grow();
    const bot = { role: "assistant", content: "", pending: true, cites: [] };
    _threads[slug].push(bot);
    paint();

    const fallback = async () => {
      const j = await api("/consult", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: slug, message: text }),
      });
      bot.content = j.answer; bot.cites = j.knowledge || [];
    };
    try {
      await streamConsult(slug, text, {
        onKnowledge: (cites) => { bot.cites = cites; paint(); },
        onDelta: (t) => { bot.content += t; bot.pending = false; paint(); },
      });
      if (!bot.content) await fallback();          // ストリームが空
    } catch (err) {
      try { await fallback(); }                    // ストリーム不可の端末 → 非ストリームへ
      catch (e2) {
        bot.content = "うまく応答できませんでした。少し時間をおいて、もう一度お試しください。\n（" + (e2.message || err.message) + "）";
      }
    } finally {
      bot.pending = false; busy = false; sendBtn.disabled = false; paint(); input.focus();
    }
  });

  input.focus();
  bindKeyboard();
}

function jpRel(r) {
  return ({ primary: "一次資料", secondary_reliable: "信頼できる二次資料", common_knowledge: "周知",
    uncertain: "出典不確か", legend: "伝説・逸話" }[r]) || r;
}

// SSE (fetch + ReadableStream) — POST で相談し、event/data を解釈
async function streamConsult(slug, message, { onKnowledge, onDelta }) {
  const res = await fetch("/consult/stream", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character: slug, message }),
  });
  if (!res.ok || !res.body) {
    let msg = `エラー (${res.status})`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop();
    for (const block of blocks) {
      let ev = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += (data ? "\n" : "") + line.slice(5).replace(/^ /, "");
      }
      if (!data) continue;
      let parsed; try { parsed = JSON.parse(data); } catch { parsed = data; }
      if (ev === "knowledge") onKnowledge(parsed);
      else if (ev === "delta") onDelta(parsed.text ?? "");
      else if (ev === "error") throw new Error(parsed.message || "サーバーエラー");
      else if (ev === "done") return;
    }
  }
}

// キーボード表示時に入力欄を持ち上げる（iOS Safari / Android Chrome）
let _kbBound = false;
function bindKeyboard() {
  const vv = window.visualViewport;
  if (!vv || _kbBound) return;
  _kbBound = true;
  const onResize = () => {
    const gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    document.documentElement.style.setProperty("--kb", gap + "px");
    const log = document.getElementById("log");
    if (log) log.scrollTop = log.scrollHeight;
  };
  vv.addEventListener("resize", onResize);
  vv.addEventListener("scroll", onResize);
  onResize();
}

// PWA
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
