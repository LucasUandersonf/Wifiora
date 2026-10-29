"use strict";
// Radar de Ondas — painel de tendências. JS puro; polling a cada 10 s (varreduras são lentas).

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = (v, d = 0) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const asDate = (iso) => (iso ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z") : null);
const when = (iso) => { const d = asDate(iso); return d ? d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"; };
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

const STAGES = [
  ["sinal", "Sinal fraco", "var(--muted)"],
  ["emergente", "Emergente", "var(--info)"],
  ["crescendo", "Crescendo", "var(--warn)"],
  ["mainstream", "Mainstream", "var(--ok)"],
];
const TOPIC = {
  anuncios_em_ia: "anúncios em IA", compras_agenticas: "compras por agentes", geo_busca_ia: "GEO / busca por IA", crawlers_e_acesso: "robôs e acesso",
  dados_estruturados: "dados estruturados", modelos_e_plataformas: "modelos e plataformas", regulacao: "regulação", mercado_brasil: "mercado Brasil",
};
const EFFORT = { baixo: "esforço baixo", medio: "esforço médio", alto: "esforço alto" };
const STATUS = { proposed: ["proposta", "b-pending"], approved: ["aprovada", "b-approved"], rejected: ["rejeitada", "b-cancelled"], done: ["concluída", "b-completed"] };

const TOKEN_KEY = "geo-office-token";
let token = "";
try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* ok */ }
let data = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Founder-Token": token, ...(opts.headers || {}) } });
  if (res.status === 401) { showLogin("Token inválido."); throw new Error("401"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}
const post = (p, b = {}) => api(p, { method: "POST", body: JSON.stringify(b) });
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 3800); }
function showLogin(err = "") { $("#login").classList.remove("hidden"); $("#app").classList.add("hidden"); $("#login-error").textContent = err; }

function spark(history) {
  if (!history || history.length < 2) return "";
  const W = 220, H = 26, pts = history.map((h, i) => [(i / (history.length - 1)) * (W - 4) + 2, H - 3 - h.impact * h.urgency * (H - 6)]);
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolução de impacto × urgência"><polyline stroke="var(--violet-2)" points="${pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ")}"/><circle cx="${pts.at(-1)[0].toFixed(1)}" cy="${pts.at(-1)[1].toFixed(1)}" r="2.5" fill="var(--violet-2)"/></svg>`;
}
const bar = (cls, label, v) => `<span>${label}</span><div class="bar ${cls}"><i style="width:${(v * 100).toFixed(0)}%"></i></div><span>${nf(v * 100)}%</span>`;

function waveCard(w) {
  const heat = w.impact * w.urgency;
  const cls = heat >= 0.5 ? "hot" : heat >= 0.25 ? "warm" : "cool";
  return `<article class="wave ${cls}">
    <h4>${esc(w.name)} ${w.demo ? '<span class="demo-tag">DEMO</span>' : ""}</h4>
    ${w.thesis ? `<div class="thesis">${esc(w.thesis)}</div>` : ""}
    <div class="bars">${bar("imp", "Impacto", w.impact)}${bar("urg", "Urgência", w.urgency)}${bar("conf", "Confiança", w.confidence)}</div>
    ${spark(w.history)}
    <div class="meta-row">${w.window ? `<span class="badge">janela: ${esc(w.window)}</span>` : ""}<span>${nf(w.evidence_count)} evidências</span><span>· ${when(w.updated_at)}</span></div>
    ${w.relevance ? `<div class="rel">${esc(w.relevance)}</div>` : ""}
    <details><summary>Evidências</summary><ul class="ev">${w.evidence.map((e) => `<li><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer" title="${esc(e.title)}">${esc(e.title || e.url)}</a> <span class="muted">· ${esc(e.source || host(e.url))}</span></li>`).join("")}</ul></details>
    <div class="row"><button class="btn" data-archive="${esc(w.id)}" title="Parar de acompanhar">Arquivar</button></div>
  </article>`;
}

function render() {
  const d = data;
  $("#mode-chip").textContent = d.settings.provider === "mock" ? "SIMULAÇÃO" : "IA REAL · " + d.settings.provider.toUpperCase();
  $("#mode-chip").classList.toggle("real", d.settings.provider !== "mock");
  const rc = $("#run-chip");
  rc.className = "chip live" + (d.running ? "" : d.settings.enabled ? " paused" : " off");
  rc.querySelector("span").textContent = d.running ? "Varrendo agora" : d.settings.enabled ? `Automático a cada ${Math.round(d.settings.interval_seconds / 3600)} h` : "Radar desligado";
  $("#brief-text").textContent = d.brief?.text || "Ainda não há boletim. Clique em “Varrer agora” para a primeira varredura.";
  $("#brief-meta").textContent = d.brief ? `${when(d.brief.at)} · ${nf(d.brief.counts.signals)} sinais novos · ${nf(d.brief.counts.waves)} ondas · ${nf(d.brief.counts.plays)} ações` : "";
  const hot = d.waves.filter((w) => w.impact * w.urgency >= 0.5).length;
  $("#ticker").innerHTML = [["Ondas", d.waves.length], ["Quentes", hot], ["Ações propostas", d.plays.filter((p) => p.status === "proposed").length], ["Sinais", d.signals.length]]
    .map(([k, v]) => `<span class="tick">${esc(k)}<b>${esc(v)}</b></span>`).join("");

  $("#board").innerHTML = STAGES.map(([key, label, color]) => {
    const ws = d.waves.filter((w) => w.stage === key || (key === "mainstream" && w.stage === "saturada"));
    return `<div class="col${ws.length ? "" : " is-empty"}"><div class="col-h"><span><i style="background:${color}"></i>${label}</span><span>${ws.length}</span></div>
      ${ws.map(waveCard).join("") || '<div class="empty">Nenhuma onda nesta fase.</div>'}</div>`;
  }).join("");

  $("#plays").innerHTML = d.plays.map((p) => {
    const [st, cls] = STATUS[p.status] || [p.status, ""];
    return `<article class="play">
      <div class="meta-row"><span class="badge ${cls}">${esc(st)}</span><span>${esc(p.wave)}</span>${p.demo ? '<span class="demo-tag">DEMO</span>' : ""}</div>
      <h4>${esc(p.title)}</h4>
      ${p.action ? `<p>${esc(p.action)}</p>` : ""}${p.why ? `<p class="muted">Por quê: ${esc(p.why)}</p>` : ""}
      ${p.first_step ? `<div class="first"><strong>Primeiro passo:</strong> ${esc(p.first_step)}</div>` : ""}
      <div class="meta-row"><span>${esc(EFFORT[p.effort] || p.effort)}</span><span>· ${p.est_cost_usd > 0 ? "custo estimado US$ " + nf(p.est_cost_usd) : "sem gasto"}</span>${p.deadline_days ? `<span>· prazo ${nf(p.deadline_days)} dias</span>` : ""}</div>
      <div class="row">${p.status === "proposed" ? `<button class="btn primary" data-play="${esc(p.id)}" data-st="approved">Aprovar</button><button class="btn danger" data-play="${esc(p.id)}" data-st="rejected">Rejeitar</button>`
        : p.status === "approved" ? `<button class="btn" data-play="${esc(p.id)}" data-st="done">Marcar como feita</button>` : ""}</div>
    </article>`;
  }).join("") || '<p class="muted">Nenhuma ação proposta ainda.</p>';

  $("#sig-count").textContent = `${d.signals.length} mais recentes`;
  $("#signals").innerHTML = d.signals.map((s) => `<li>
    <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
    <span class="muted small">${esc(s.source || host(s.url))} · ${s.published_at ? "publicado " + when(s.published_at) : "visto " + when(s.created_at)} · via ${esc(s.found_via)} · relevância ${nf(s.relevance * 100)}%</span>
    ${s.summary ? `<span class="s">${esc(s.summary)}</span>` : ""}
    <span>${(s.topics || []).map((t) => `<span class="topic">${esc(TOPIC[t] || t)}</span>`).join("")}</span></li>`).join("") || '<li class="muted">Nenhum sinal ainda.</li>';

  const src = d.sources;
  $("#sources").innerHTML = (src.mode === "demo" ? '<p class="muted small">Modo simulação: sinais fictícios, sem acesso a feeds nem busca.</p>' : "")
    + (src.feed_health.map((f) => `<div class="src"><span class="u" title="${esc(f.feed)}">${esc(host(f.feed))}</span><span class="${f.ok ? "" : "err"}">${f.ok ? `ok · ${nf(f.recent)} recentes` : "falhou"}</span></div>`).join("")
    || (src.mode === "live" ? '<p class="muted small">Nenhum feed configurado ou acessível.</p>' : ""))
    + (src.search_errors.length ? `<p class="err small">Falhas na busca: ${src.search_errors.map(esc).join(" · ")}</p>` : "");
  if (document.activeElement?.closest("#form-radar") == null) {
    $("#cfg-enabled").checked = d.settings.enabled;
    $("#cfg-interval").value = String(d.settings.interval_seconds);
  }
}

async function refresh() {
  try {
    data = await api("/api/office/radar");
    $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
    render();
  } catch (e) { if (e.message !== "401") toast("Sem conexão com o escritório."); }
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.id === "btn-sweep") { await post("/api/control/radar/sweep"); toast("Varredura encomendada ao CVO. Acompanhe no Escritório."); }
    else if (t.dataset.play) { await post(`/api/control/plays/${t.dataset.play}`, { status: t.dataset.st }); toast(t.dataset.st === "approved" ? "Aprovada: virou diretriz para o CVO." : "Ação atualizada."); }
    else if (t.dataset.archive) { await post(`/api/control/waves/${t.dataset.archive}/archive`); toast("Onda arquivada."); }
    else return;
    setTimeout(refresh, 500);
  } catch (e) { if (e.message !== "401") toast("Erro: " + e.message); }
});
$("#form-radar").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/control/settings", { method: "PATCH", body: JSON.stringify({ radar_enabled: $("#cfg-enabled").checked, radar_interval_seconds: Number($("#cfg-interval").value) }) });
  document.activeElement.blur(); toast("Configuração do radar salva."); refresh();
});
$("#login-form").addEventListener("submit", (ev) => {
  ev.preventDefault(); token = $("#token").value.trim();
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ok */ }
  refresh();
});

if (token) refresh(); else showLogin();
setInterval(() => { if (token && !$("#app").classList.contains("hidden")) refresh(); }, 10000);
