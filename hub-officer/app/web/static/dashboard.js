"use strict";
// Painel do fundador — JS puro, sem dependências. Polling (5s) + SSE para telemetria ao vivo.

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (v, d = 2) => (v == null ? "—" : "US$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v) => (v == null ? "—" : (v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%");
const num = (v, d = 0) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d }));
const time = (iso) => (iso ? new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleTimeString("pt-BR") : "");
const badge = (s) => `<span class="badge b-${esc(s)}">${esc(String(s).replace(/_/g, " "))}</span>`;

const TOKEN_KEY = "geo-office-token";
let token = "";
try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* storage indisponível */ }
let state = { overview: null };
let es = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Founder-Token": token, ...(opts.headers || {}) } });
  if (res.status === 401) { showLogin("Token inválido."); throw new Error("401"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}
const post = (p, body = {}) => api(p, { method: "POST", body: JSON.stringify(body) });

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

function showLogin(err = "") {
  $("#login").classList.remove("hidden"); $("#app").classList.add("hidden");
  $("#login-error").textContent = err;
}

// ------------------------------------------------------------------ render
// kind "spend": consumo de orçamento (alto = ruim). kind "quality": quanto maior, melhor.
function tile(label, value, sub = "", meter = null, kind = "spend") {
  let m = "";
  if (meter != null) {
    const r = Math.max(0, Math.min(1, meter));
    const cls = kind === "spend" ? (r > 0.9 ? "bad" : r > 0.7 ? "warn" : "") : (r < 0.6 ? "bad" : r < 0.8 ? "warn" : "");
    m = `<div class="meter ${cls}"><i style="width:${(r * 100).toFixed(1)}%"></i></div>`;
  }
  return `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${sub}</div>${m}</div>`;
}

function renderHeader(o) {
  const pill = $("#status-pill");
  pill.className = "status " + (o.paused ? "paused" : "running");
  $("#status-text").textContent = o.paused ? "Pausado" : "Operando";
  $("#btn-pause").textContent = o.paused ? "Retomar" : "Pausar";
  $("#meta").innerHTML = `LLM <b>${esc(o.llm_provider)}</b> · modelos ${esc(Object.values(o.models).filter((v, i, a) => a.indexOf(v) === i).join(", "))} · barramento <b>${esc(o.bus)}</b> · autonomia <b>${esc(o.autonomy_level)}</b> · chamadas de IA hoje <b>${num(o.llm_calls_today)}${o.llm_daily_call_limit ? " / " + num(o.llm_daily_call_limit) : ""}</b>${o.resting_until ? ` · <span class="badge b-warning">descansando até ${time(o.resting_until)}</span>` : ""} · foco: ${esc(o.focus_niche)}`;
  $("#gov-autonomy").value = o.autonomy_level;
  for (const [id, key] of [["#gov-daily", "daily_llm_budget_usd"], ["#gov-monthly", "monthly_budget_usd"], ["#gov-threshold", "score_threshold"]]) {
    if (document.activeElement !== $(id)) $(id).value = o[key];
  }
}

function renderFinance(f, provider) {
  $("#fin-note").textContent = f.lifetime.simulated_cost > 0 ? `· inclui ${usd(f.lifetime.simulated_cost, 4)} de custo simulado (modo ${provider})` : "";
  $("#fin-tiles").innerHTML = [
    tile("LLM hoje", usd(f.today.llm, 4), `orçamento ${usd(f.today.llm_budget)}`, f.today.llm_budget ? f.today.llm / f.today.llm_budget : null),
    tile("Gasto no mês", usd(f.month.total), `orçamento ${usd(f.month.budget)}`, f.month.budget ? f.month.total / f.month.budget : null),
    tile("Caixa", usd(f.cash), `inicial ${usd(f.starting_cash, 0)}`),
    tile("Runway", f.runway_days == null ? "∞" : num(f.runway_days) + " dias", `burn ${usd(f.burn_per_day, 4)}/dia`),
    tile("Receita real", usd(f.revenue.real), `projetada ${usd(f.revenue.projected)}/mês`),
    tile("Margem", pct(f.margin), "sobre receita real"),
    tile("Custo / entidade publicada", usd(f.cost_per_published_entity, 4), `${num(f.published_hubs)} hubs publicados`),
  ].join("");
  renderDailyChart(f.daily);
  $("#tbl-agent-cost").innerHTML = "<tr><th>Agente</th><th class=num>Tokens</th><th class=num>Custo</th></tr>" +
    f.by_agent.sort((a, b) => b.cost - a.cost).map((a) => `<tr><td>${esc(a.agent_id)}</td><td class=num>${num(a.tokens)}</td><td class=num>${usd(a.cost, 4)}</td></tr>`).join("");
}

function renderDailyChart(days) {
  const W = 560, H = 160, pad = 22, max = Math.max(...days.map((d) => d.cost), 0.0001);
  const bw = (W - pad) / days.length;
  const bars = days.map((d, i) => {
    const h = (d.cost / max) * (H - pad - 10);
    const x = pad + i * bw + 2, y = H - pad - h;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 4).toFixed(1)}" height="${Math.max(h, 0.5).toFixed(1)}" rx="2" fill="var(--bar)"><title>${esc(d.date)}: ${usd(d.cost, 4)}</title></rect>` +
      (i % 2 === 0 ? `<text x="${(x + (bw - 4) / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(d.date.slice(5))}</text>` : "");
  }).join("");
  $("#chart-daily").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Custo diário"><text x="0" y="10">${usd(max, 3)}</text><line x1="${pad}" x2="${W}" y1="${H - pad}" y2="${H - pad}" stroke="var(--line)"/>${bars}</svg>`;
}

function renderBusiness(b) {
  $("#biz-tiles").innerHTML = [
    tile("Hubs publicados", `${num(b.hubs_published)} / ${num(b.hubs_total)}`, "publicados / total"),
    tile("Entidades", `${num(b.entities_published)}`, `${num(b.entities_validated)} validadas · ${num(b.entities_total)} total`),
    tile("Dados estruturados", `${num(b.structured_data_kb, 1)} KB`, "JSON-LD gerado"),
    tile("Grounding médio", pct(b.avg_grounding), "valores com evidência literal", b.avg_grounding, "quality"),
    tile("Nota média (Score)", b.avg_score == null ? "—" : num(b.avg_score, 2), `${num(b.evaluations)} avaliações`, b.avg_score, "quality"),
    tile("Taxa de aprovação", pct(b.approval_rate), "por avaliação (inclui revisões)", b.approval_rate, "quality"),
    tile("Share of Voice (GEO)", pct(b.share_of_voice), "citações em respostas de LLMs"),
    tile("Oportunidades", num(b.opportunities), `${usd(b.opportunities_weighted_usd, 0)}/mês ponderado`),
  ].join("");
}

function renderObjective(ov) {
  const o = ov.active_objective;
  const counts = Object.entries(ov.tasks).map(([k, v]) => `${badge(k)} ${v}`).join(" ");
  const queues = Object.values(ov.queues).reduce((a, b) => a + b, 0);
  $("#objective").innerHTML = o
    ? `<strong>Objetivo ativo:</strong> ${esc(o.title)} ${badge(o.status)} <span class="muted">fase ${esc(o.current_phase)} · ${esc(o.niche)}</span> <span>${counts}</span> <span class="muted">mensagens na fila: ${queues}</span>`
    : `<span class="muted">Nenhum objetivo ativo — o CVO inicia um novo ciclo no próximo intervalo (ou clique em “Rodar ciclo agora”).</span> <span>${counts}</span>`;
}

function renderAgents(agents) {
  $("#agents").innerHTML = agents.map((a) => `
    <div class="agent ${a.status === "working" ? "working" : ""}" id="agent-${esc(a.agent_id)}">
      <div class="sector">${esc(a.sector)} · ${esc(a.role)}</div>
      <div class="name">${esc(a.title)}</div>
      <div class="act" data-act>${a.status === "working" ? esc(a.current_activity) : "ocioso"}</div>
      <div class="stats"><span>${num(a.processed)} msgs</span><span>${num(a.failures)} falhas</span><span>nota ${a.avg_score == null ? "—" : num(a.avg_score, 2)}</span></div>
      <div class="stats" title="skills">${(a.skills || []).map(esc).join(" · ") || "&nbsp;"}</div>
    </div>`).join("");
}

function renderTasks(tasks) {
  $("#tbl-tasks").innerHTML = "<tr><th>Tarefa</th><th>Setor</th><th>Responsável</th><th>Status</th><th class=num>Nota</th><th class=num>Rev.</th></tr>" +
    tasks.map((t) => `<tr title="${esc(t.error || "")}"><td>${esc(t.title)}</td><td>${esc(t.sector)}</td><td>${esc(t.assignee_id)}</td><td>${badge(t.status)}</td><td class=num>${t.last_score == null ? "—" : num(t.last_score, 2)}</td><td class=num>${num(t.revisions)}</td></tr>`).join("");
}

function logLine(m) {
  const li = document.createElement("li");
  li.innerHTML = `<span class="t">${time(m.created_at || m.at)}</span><span class="route">${esc(m.sender)} → ${esc(m.recipient)}</span> <span class="badge">${esc(m.type)}</span> ${esc(m.summary)}`;
  return li;
}

function renderApprovals(list) {
  $("#approvals").innerHTML = list.length ? list.map((a) => `
    <div class="approval"><div>${badge(a.kind)} <strong>${esc(a.title)}</strong></div>
    <div class="muted small">${esc(a.requested_by)} · ${time(a.created_at)}${a.amount_usd != null ? " · " + usd(a.amount_usd) : ""}</div>
    <div class="row"><button class="primary" data-approve="${esc(a.id)}">Aprovar</button><button class="danger" data-reject="${esc(a.id)}">Rejeitar</button></div></div>`).join("")
    : '<p class="muted">Nada aguardando decisão.</p>';
}

function renderAlerts(list) {
  $("#alerts").innerHTML = list.length ? list.slice(0, 25).map((a) => `
    <li><div>${badge(a.level)} <span class="muted small">${esc(a.source)} · ${time(a.created_at)}</span><br>${esc(a.message)}</div>
    ${a.acknowledged ? "" : `<button data-ack="${esc(a.id)}">ok</button>`}</li>`).join("")
    : '<li class="muted">Sem alertas.</li>';
}

function renderDirectives(list) {
  $("#directives").innerHTML = list.filter((d) => d.active).map((d) => `<li><span>${esc(d.text)}</span><button data-del-directive="${esc(d.id)}">remover</button></li>`).join("") || '<li class="muted">Nenhuma diretriz ativa.</li>';
}

function renderReports(objs) {
  $("#reports").innerHTML = objs.length ? objs.map((o) => {
    const r = o.final_report || {};
    const list = (xs) => (xs && xs.length ? "<ul>" + xs.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>" : "");
    return `<div class="report"><div>${badge(o.status)} <strong>${esc(o.title)}</strong> <span class="muted small">${time(o.created_at)}</span></div>
      ${r.summary ? `<div>${esc(r.summary)}</div>` : `<div class="muted small">${esc(o.rationale)}</div>`}
      ${list(r.executed)}${r.risks ? '<div class="muted small">Riscos:</div>' + list(r.risks) : ""}
      ${r.next_focus ? `<div class="muted small">Próximo foco: ${esc(r.next_focus)}</div>` : ""}</div>`;
  }).join("") : '<p class="muted">Nenhum ciclo concluído ainda.</p>';
}

function renderHubs(hubs, opps) {
  $("#tbl-hubs").innerHTML = "<tr><th>Hub</th><th>Status</th><th class=num>Entidades</th><th class=num>Grounding</th><th class=num>Citações (SoV)</th><th></th></tr>" +
    hubs.map((h) => `<tr><td>${h.status === "published" ? `<a href="/hub/${encodeURIComponent(h.slug)}" target="_blank" rel="noopener">${esc(h.title)}</a>` : esc(h.title)}${h.demo_data ? ' <span class="badge">demo</span>' : ""}</td><td>${badge(h.status)}</td><td class=num>${num(h.entities)}</td><td class=num>${pct(h.avg_grounding)}</td><td class=num>${pct(h.share_of_voice)}</td><td><button data-audit="${esc(h.slug)}" title="Pergunta às IAs com busca na web se elas citam este hub">Medir</button></td></tr>`).join("");
  $("#tbl-opps").innerHTML = "<tr><th>Canal</th><th>Oportunidade</th><th class=num>Est./mês</th><th class=num>Conf.</th></tr>" +
    opps.slice(0, 10).map((o) => `<tr><td>${esc(o.channel)}</td><td>${esc(o.title)}</td><td class=num>${usd(o.est_monthly_usd, 0)}</td><td class=num>${pct(o.confidence)}</td></tr>`).join("");
}

// ------------------------------------------------------------------ data
async function refresh() {
  try {
    const [ov, agents, tasks, approvals, alerts, directives, objectives, hubs, opps] = await Promise.all([
      api("/api/office/overview"), api("/api/office/agents"), api("/api/office/tasks?limit=60"), api("/api/office/approvals"),
      api("/api/office/alerts"), api("/api/office/directives"), api("/api/office/objectives?limit=8"), api("/api/office/hubs"), api("/api/office/opportunities"),
    ]);
    state.overview = ov;
    $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
    renderHeader(ov.office); renderFinance(ov.finance, ov.office.llm_provider); renderBusiness(ov.business); renderObjective(ov);
    renderAgents(agents); renderTasks(tasks); renderApprovals(approvals); renderAlerts(alerts); renderDirectives(directives);
    renderReports(objectives); renderHubs(hubs, opps);
  } catch (e) {
    if (e.message !== "401") { $("#status-pill").className = "status down"; $("#status-text").textContent = "sem conexão"; }
  }
}

async function loadLog() {
  const msgs = await api("/api/office/messages?limit=80");
  const ol = $("#log"); ol.innerHTML = "";
  msgs.forEach((m) => ol.appendChild(logLine(m)));
}

function connectStream() {
  if (es) es.close();
  es = new EventSource("/api/office/stream?token=" + encodeURIComponent(token));
  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.event === "message") {
      const ol = $("#log"); ol.insertBefore(logLine(e), ol.firstChild);
      while (ol.children.length > 200) ol.removeChild(ol.lastChild);
    } else if (e.event === "agent_status") {
      const card = document.getElementById("agent-" + e.agent_id);
      if (card) { card.classList.toggle("working", e.status === "working"); card.querySelector("[data-act]").textContent = e.status === "working" ? e.activity : "ocioso"; }
    } else if (e.event === "alert" && e.level !== "info") {
      toast(`${e.source}: ${e.message}`);
    } else if (e.event === "sales") {
      refreshSales();
    } else if (e.event === "diagnosis" && e.status !== "started") {
      refreshDiagnoses();
    } else if (e.event === "council" && e.status !== "started") {
      refreshCouncil(); refresh();
    }
  };
}

// ------------------------------------------------------------------ actions
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.id === "btn-cycle") { await post("/api/control/cycle"); toast("Ciclo solicitado ao CVO."); }
    else if (t.id === "btn-pause") { const paused = state.overview?.office.paused; await post(paused ? "/api/control/resume" : "/api/control/pause"); toast(paused ? "Escritório retomado." : "Escritório pausado."); }
    else if (t.dataset.approve) { await post(`/api/control/approvals/${t.dataset.approve}`, { approve: true }); toast("Aprovado."); }
    else if (t.dataset.reject) { await post(`/api/control/approvals/${t.dataset.reject}`, { approve: false }); toast("Rejeitado."); }
    else if (t.dataset.ack) { await post(`/api/control/alerts/${t.dataset.ack}/ack`); }
    else if (t.dataset.audit) { const r = await post(`/api/control/hubs/${t.dataset.audit}/geo-audit`); toast(`Auditoria iniciada com ${r.queries} perguntas; o resultado chega nos alertas.`); }
    else if (t.dataset.delDirective) { await api(`/api/control/directives/${t.dataset.delDirective}`, { method: "DELETE" }); }
    else return;
    refresh();
  } catch (e) { if (e.message !== "401") toast("Erro: " + e.message); }
});

// ------------------------------------------------------------------ portal público
const REVIEWER_KEY = "geo-office-reviewer";
try { $("#reviewer").value = localStorage.getItem(REVIEWER_KEY) || ""; } catch { /* ok */ }
$("#reviewer").addEventListener("change", () => { try { localStorage.setItem(REVIEWER_KEY, $("#reviewer").value.trim()); } catch { /* ok */ } });
const dateBR = (iso) => (iso ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z").toLocaleDateString("pt-BR") : "—");

async function refreshPortal() {
  if (document.activeElement?.closest("#portal")) return; // não atrapalha quem está digitando
  try {
    const [ents, corr, leads, clients] = await Promise.all([
      api("/api/office/entities?review=pending"), api("/api/office/corrections"), api("/api/office/leads?limit=50"), api("/api/office/api-clients"),
    ]);
    $("#tbl-review").innerHTML = "<tr><th>Ficha</th><th>Hub</th><th class=num>Grounding</th><th>Fontes</th><th></th></tr>" + (ents.map((e) => `<tr>
      <td><strong>${esc(e.name)}</strong><div class="muted small">v${esc(e.version)} · verificado ${dateBR(e.verified_at)}</div></td><td>${esc(e.hub_title)}</td><td class=num>${pct(e.grounding_ratio)}</td>
      <td>${e.sources.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc((u.split("/")[2] || u))}</a>`).join("<br>") || "—"}</td>
      <td><button class="primary" data-review="${esc(e.id)}">Validar</button></td></tr>`).join("") || '<tr><td colspan="5" class="muted">Nenhuma ficha aguardando revisão.</td></tr>');
    $("#corrections").innerHTML = corr.map((c) => `<li><div><strong>${esc(c.entity_slug || c.hub_slug || "geral")}</strong> <span class="muted small">${esc(c.name)} · ${esc(c.email)} · ${dateBR(c.created_at)}</span><br>${esc(c.message)}${c.evidence_url ? `<br><a href="${esc(c.evidence_url)}" target="_blank" rel="noopener">fonte enviada</a>` : ""}</div>
      <div class="row"><button data-corr="${esc(c.id)}" data-st="resolved">Corrigido</button><button class="danger" data-corr="${esc(c.id)}" data-st="rejected">Rejeitar</button></div></li>`).join("") || '<li class="muted">Nenhum pedido aberto.</li>';
    $("#tbl-leads").innerHTML = "<tr><th>Data</th><th>Fornecedor</th><th>Contato</th><th>Status</th><th>Valor (USD)</th><th></th></tr>" + (leads.map((l) => `<tr>
      <td>${dateBR(l.created_at)}</td><td>${esc(l.entity_name)}</td><td>${esc(l.name)}<div class="muted small">${esc(l.email)}${l.phone ? " · " + esc(l.phone) : ""}${l.company ? " · " + esc(l.company) : ""}</div></td>
      <td><select data-lead-status="${esc(l.id)}">${["new", "sent", "won", "discarded"].map((st) => `<option value="${st}" ${st === l.status ? "selected" : ""}>${{ new: "novo", sent: "enviado", won: "ganho", discarded: "descartado" }[st]}</option>`).join("")}</select></td>
      <td><input data-lead-value="${esc(l.id)}" type="number" min="0" step="1" value="${l.value_usd ?? ""}" style="max-width:90px"></td>
      <td><button data-lead="${esc(l.id)}">Salvar</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">Nenhum lead ainda.</td></tr>');
    $("#tbl-api").innerHTML = "<tr><th>Cliente</th><th>Chave</th><th class=num>Hoje / cota</th><th class=num>Total</th><th></th></tr>" + (clients.map((c) => `<tr>
      <td>${esc(c.name)}<div class="muted small">${usd(c.monthly_price_usd, 0)}/mês</div></td><td><code>${esc(c.key_prefix)}…</code></td>
      <td class=num>${c.usage_day === new Date().toISOString().slice(0, 10) ? num(c.usage_count) : 0} / ${num(c.daily_quota)}</td><td class=num>${num(c.total_requests)}</td>
      <td>${c.active ? `<button class="danger" data-revoke="${esc(c.id)}">Revogar</button>` : '<span class="muted small">revogada</span>'}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">Nenhum cliente ainda.</td></tr>');
  } catch (e) { /* o resto do painel segue funcionando */ }
}

async function refreshAiData() {
  try {
    const d = await api("/api/office/ai-data");
    const g = d.graph;
    $("#ai-graph").innerHTML = `<div class="kpis">
      <div><strong>${num(g.nodes)}</strong><span>nós</span></div><div><strong>${num(g.edges)}</strong><span>ligações</span></div>
      <div><strong>${num(g.orgs)}</strong><span>empresas</span></div><div><strong>${num(g.concepts)}</strong><span>conceitos e integrações</span></div></div>
      <p>${g.dangling.length ? `<span class="badge b-failed">${g.dangling.length} ponta(s) solta(s)</span> ${g.dangling.slice(0, 3).map(esc).join(", ")}` : '<span class="badge b-approved">grafo fechado</span> toda referência aponta para um nó existente.'}</p>
      <p>${num(d.files.hubs)} hub(s) × ${num(d.files.per_hub)} formatos por hub, mais: ${d.files.site.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.split("/").pop())}</a>`).join(" · ")}</p>`;
    const p = d.pings;
    $("#ping-lag").textContent = p.avg_lag_seconds == null ? "Nenhuma mudança de dado avisada ainda." : `Da detecção da mudança até o aviso: ${num(p.avg_lag_seconds, 1)} s em média.`;
    const REASON = { publish: "publicação", data_change: "dado mudou", review: "revisão", unpublish: "retirada" };
    $("#tbl-pings").innerHTML = "<tr><th>Quando</th><th>Motivo</th><th class=num>URLs</th><th>Portal</th><th>IndexNow</th></tr>" + (p.recent.map((x) => `<tr>
      <td>${dateBR(x.at)} ${time(x.at)}<div class="muted small">${esc(x.hub)}</div></td>
      <td>${esc(REASON[x.reason] || x.reason)}${Object.keys(x.changed || {}).length ? `<div class="muted small">${Object.entries(x.changed).map(([k, v]) => esc(k) + ": " + v.map(esc).join(", ")).join("<br>")}</div>` : ""}</td>
      <td class=num>${num(x.urls)}</td><td>${x.revalidated ? "✓" : "—"}</td><td class="small">${esc(x.indexnow)}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">Nenhum aviso ainda.</td></tr>');
    $("#tbl-bots").innerHTML = "<tr><th>Robô</th><th class=num>Páginas</th><th class=num>Dados</th><th class=num>Grafo</th><th class=num>llms</th><th>Último acesso</th></tr>" + (d.bots.bots.map((b) => `<tr>
      <td><strong>${esc(b.bot)}</strong></td><td class=num>${num(b.page)}</td><td class=num>${num(b.data)}</td><td class=num>${num(b.graph)}</td><td class=num>${num(b.llms)}</td>
      <td>${dateBR(b.last_at)}<div class="muted small">${esc(b.last_path)}</div></td></tr>`).join("") || '<tr><td colspan="6" class="muted">Nenhum robô de IA registrado ainda. Depois do deploy com domínio próprio, os acessos aparecem aqui.</td></tr>');
  } catch (e) { /* segue */ }
}
setInterval(() => { if (token && !$("#app").classList.contains("hidden")) { refreshAiData(); refreshViability(); refreshCouncil(); refreshNiches(); refreshDiagnoses(); refreshSales(); } }, 60000);

// ------------------------------------------------------------------ comercial automático
const P_STATUS = { novo: "novo", sem_contato: "sem e-mail", diagnosticado: "diagnosticado", contatado: "contatado", respondeu: "respondeu", proposta: "proposta enviada", cliente: "cliente", perdido: "perdido", descadastrado: "descadastrado", desqualificado: "desqualificado (sem fit)" };
const HEALTH = { smtp: "E-mail de envio (SMTP)", imap: "Leitura de respostas (IMAP)", payment_links: "Links de pagamento", stripe_webhook: "Confirmação de pagamento (Stripe)", web_search: "Busca na web (prospecção)", web_fetch: "Leitura de sites", company_cnpj: "CNPJ no rodapé", public_url: "Domínio público" };
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
async function refreshSales() {
  if (document.activeElement?.closest("#sales .row")) return;
  try {
    const d = await api("/api/office/sales");
    $("#sales-enabled").checked = d.enabled; $("#sales-auto").checked = d.auto_send; $("#sales-cap").value = d.cap;
    $("#sales-meta").textContent = `${d.enabled ? "ligado" : "desligado"} · e-mails hoje ${d.sent_today}/${d.cap} · ${d.send_window ? "dentro" : "fora"} do horário comercial`;
    $("#sales-health").innerHTML = Object.entries(HEALTH).map(([k, label]) => `<span class="badge ${d.health[k] ? "b-approved" : "b-warning"}" style="margin:2px">${d.health[k] ? "✓" : "✗"} ${esc(label)}</span>`).join(" ") +
      (!d.health.smtp ? '<div class="muted small" style="margin-top:6px">Sem SMTP os e-mails ficam “simulados” (aparecem aqui, mas não saem). Sem busca na web, só entram empresas que pedirem o diagnóstico em /diagnostico-gratis.</div>' : "");
    const f = d.funnel, n = (k) => f[k] || 0;
    $("#sales-kpis").innerHTML = [["Empresas", Object.values(f).reduce((a, b) => a + b, 0)], ["Diagnosticadas", n("diagnosticado") + n("contatado") + n("proposta") + n("cliente") + n("perdido")], ["Contatadas", n("contatado") + n("proposta") + n("cliente") + n("perdido")], ["Com proposta", n("proposta") + n("cliente")], ["Clientes", n("cliente")], ["Receita mensal", brl(d.mrr_brl)]]
      .map(([l, v]) => `<div><strong>${typeof v === "number" ? num(v) : esc(v)}</strong><span>${esc(l)}</span></div>`).join("");
    $("#tbl-prospects").innerHTML = "<tr><th>Empresa</th><th>Status</th><th class=num>Nota</th><th class=num>Contatos</th><th></th></tr>" + (d.prospects.map((p) => `<tr>
      <td><strong>${esc(p.company)}</strong><div class="muted small">${esc(p.email || p.domain)} · ${esc(p.segment)}${p.source === "inbound" ? " · pediu pelo site" : ""}</div></td>
      <td>${esc(P_STATUS[p.status] || p.status)}${p.last_contact_at ? `<div class="muted small">${dateBR(p.last_contact_at)}</div>` : ""}</td>
      <td class=num>${p.score ?? "—"}</td><td class=num>${p.touches}</td>
      <td class="small">${p.report ? `<a href="${esc(p.report)}" target="_blank" rel="noopener">relatório</a> · ` : ""}<a href="${esc(p.proposal)}" target="_blank" rel="noopener">proposta</a></td></tr>`).join("") || '<tr><td colspan="5" class="muted">Nenhuma empresa ainda.</td></tr>');
    $("#tbl-clients").innerHTML = "<tr><th>Cliente</th><th>Plano</th><th class=num>Mensal</th><th>Próximo relatório</th></tr>" + (d.clients.map((c) => `<tr>
      <td><a href="${esc(c.page)}" target="_blank" rel="noopener">${esc(c.company)}</a><div class="muted small">${esc(c.status)} · ${c.reports} relatório(s)</div></td><td>${esc(c.plan)}</td><td class=num>${brl(c.mrr_brl)}</td><td>${dateBR(c.next_report_at)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">Nenhum cliente ainda.</td></tr>');
    $("#tbl-emails").innerHTML = "<tr><th>Quando</th><th>E-mail</th><th>Status</th></tr>" + (d.emails.map((e) => `<tr>
      <td class="small">${dateBR(e.at)} ${time(e.at)}</td><td class="small">${e.direction === "in" ? "← " + esc(e.from) : "→ " + esc(e.to)}<div class="muted">${esc(e.subject)}</div></td>
      <td class="small">${esc(e.status)}${e.intent ? " · " + esc(e.intent) : ""}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">Nenhum e-mail ainda.</td></tr>');
  } catch (e) { /* segue */ }
}
async function saveSales(patch) { try { await api("/api/control/settings", { method: "PATCH", body: JSON.stringify(patch) }); toast("Comercial atualizado."); document.activeElement.blur(); refreshSales(); } catch (e) { toast(e.message); } }
$("#sales-enabled").addEventListener("change", (ev) => saveSales({ sales_enabled: ev.target.checked }));
$("#sales-auto").addEventListener("change", (ev) => saveSales({ sales_auto_send: ev.target.checked }));
$("#sales-cap").addEventListener("change", (ev) => saveSales({ sales_daily_email_cap: Number(ev.target.value) }));
$("#sales-run").addEventListener("click", async () => { toast("Rodando o funil… pode levar alguns minutos."); try { await post("/api/control/sales/run"); } catch (e) { toast(e.message); } refreshSales(); refreshDiagnoses(); });

// ------------------------------------------------------------------ diagnósticos (produto de entrada)
let TRACKER = null;
async function loadTracker() {
  try {
    TRACKER = await api("/api/office/tracker");
    $("#dg-engines").innerHTML = "IAs: " + TRACKER.available.map((e) => `<label style="display:flex;gap:4px;align-items:center"><input type="checkbox" data-engine="${esc(e)}" checked> ${esc(TRACKER.labels[e] || e)}</label>`).join("") +
      (TRACKER.available[0] === "simulado" ? '<span class="muted">Sem chaves de OpenAI, Anthropic ou Perplexity: usa a IA configurada, sem busca (estimativa).</span>' : "") +
      `<span class="muted" id="dg-cost"></span>`;
    const upd = () => { const n = $("#dg-n").value; $("#dg-cost").textContent = ` · custo estimado ≈ ${usd(TRACKER.cost_per_report[n] ?? 0)} por relatório`; };
    $("#dg-n").onchange = upd; upd();
  } catch (e) { /* segue */ }
}
async function refreshDiagnoses() {
  if (!TRACKER) loadTracker();
  try {
    const rows = await api("/api/office/diagnoses");
    $("#tbl-diag").innerHTML = "<tr><th>Marca</th><th>Segmento</th><th class=num>Nota</th><th class=num>Citado</th><th class=num>Técnico</th><th class=num>Lacunas</th><th>Status</th><th>Relatório</th></tr>" + (rows.map((d) => `<tr>
      <td><strong>${esc(d.brand)}</strong><div class="muted small">${esc(d.site || "")}${d.contact ? " · " + esc(d.contact) : ""}</div></td>
      <td class="small">${esc(d.category)}${d.city ? " · " + esc(d.city) : ""}</td>
      <td class=num>${d.scores?.overall ?? "—"}</td><td class=num>${d.scores?.visibility != null ? d.scores.visibility + "%" : "—"}</td>
      <td class=num>${d.scores?.technical != null ? d.scores.technical + "%" : "—"}</td><td class=num>${d.status === "done" ? num(d.gaps) : "—"}</td>
      <td>${badge(d.status === "done" ? "completed" : d.status === "failed" ? "failed" : "in_progress")}${d.mode ? `<div class="muted small">${d.mode === "web" ? "com busca na web" : "estimativa (sem busca)"}</div>` : ""}${d.error ? `<div class="muted small">${esc(d.error)}</div>` : ""}</td>
      <td>${d.status === "done" ? `<a href="${esc(d.report)}" target="_blank" rel="noopener">abrir</a> · <a href="${esc(d.pdf)}" target="_blank" rel="noopener">PDF</a> · <button data-copy="${esc(location.origin + d.report)}">copiar link</button>` : "—"}<div class="muted small">${(d.engines_used || []).map((e) => esc((TRACKER?.labels || {})[e] || e)).join(", ")}${d.query_count ? " · " + d.query_count + " perguntas" : ""}</div></td></tr>`).join("") || '<tr><td colspan="8" class="muted">Nenhum diagnóstico ainda. Gere o primeiro para uma empresa que você quer como cliente.</td></tr>');
  } catch (e) { /* segue */ }
}
$("#form-diag").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const engines = [...document.querySelectorAll("#dg-engines input[data-engine]:checked")].map((i) => i.dataset.engine);
    await post("/api/control/diagnoses", { brand: $("#dg-brand").value, site: $("#dg-site").value, category: $("#dg-cat").value, city: $("#dg-city").value, competitors: $("#dg-comp").value, contact: $("#dg-contact").value, engines, query_count: Number($("#dg-n").value) });
    ["#dg-brand", "#dg-site", "#dg-cat", "#dg-city", "#dg-comp", "#dg-contact"].forEach((id) => { $(id).value = ""; });
    document.activeElement.blur(); toast("Diagnóstico iniciado. Leva alguns minutos."); refreshDiagnoses();
  } catch (e) { toast(e.message); }
});
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-copy]"); if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); toast("Link copiado. Envie ao cliente."); } catch { prompt("Copie o link:", b.dataset.copy); }
});

// ------------------------------------------------------------------ nichos (catálogo)
const LVL = { alto: "▲ alto", "médio": "● médio", baixo: "▼ baixo" };
const lvl = (k, v) => { const good = k === "risco" ? v === "baixo" : v === "alto"; const bad = k === "risco" ? v === "alto" : v === "baixo"; return `<span class="${good ? "ok" : bad ? "no-bad" : ""}">${esc(LVL[v] || v || "—")}</span>`; };
async function refreshNiches() {
  if (document.activeElement?.closest("#niches")) return;
  try {
    const d = await api("/api/office/niches");
    const nextName = d.niches.find((n) => n.slug === d.next)?.name;
    $("#niche-meta").textContent = `foco: ${d.focus} · rodízio ${d.rotation ? "ligado" : "desligado"}${nextName ? " · próximo ciclo: " + nextName : ""}`;
    $("#tbl-niches").innerHTML = `<tr><th class=num>#</th><th>Nicho</th><th>Fonte oficial que nos diferencia</th><th>Como ganha dinheiro</th>${d.criteria.map((c) => `<th title="${esc(c.question)}">${esc(c.label)}</th>`).join("")}<th>Avaliação</th><th>Hubs</th><th>Status</th><th></th></tr>` +
      d.niches.map((n) => `<tr class="${n.status === "bloqueado" ? "row-off" : ""}">
        <td class=num>${n.status === "bloqueado" ? "✗" : `<input type="number" min="1" max="99" value="${n.rank}" data-niche-rank="${esc(n.slug)}" style="width:52px">`}</td>
        <td><strong>${n.star ? "⭐ " : ""}${esc(n.name)}</strong>${n.slug === d.next ? ' <span class="badge b-in_progress">próximo</span>' : ""}${n.ymyl ? ' <span class="badge b-warning" title="Saúde/finanças: regras extras de cuidado">YMYL</span>' : ""}<div class="muted small">${esc(n.examples)}</div></td>
        <td class="small">${esc(n.official_source)}${(n.source_urls || []).map((u) => `<br><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, ""))}</a>`).join("")}</td>
        <td class="small">${esc(n.revenue)}</td>
        ${d.criteria.map((c) => `<td class="small">${lvl(c.key, n.scores[c.key])}</td>`).join("")}
        <td class="small">${esc(n.assessment)}${n.rules ? `<div class="muted">${esc(n.rules)}</div>` : ""}</td>
        <td class="small">${n.hubs_published}/${n.hubs}${n.verdict ? "<br>" + esc(n.verdict) : ""}</td>
        <td>${n.locked ? '<span class="badge b-failed">fora do mapa</span>' : `<select data-niche-status="${esc(n.slug)}">${["ativo", "pausado"].map((st) => `<option ${st === n.status ? "selected" : ""}>${st}</option>`).join("")}</select>`}</td>
        <td>${n.status === "ativo" ? `<button data-niche-focus="${esc(n.slug)}">Focar</button>` : ""}</td></tr>`).join("");
  } catch (e) { /* segue */ }
}
document.addEventListener("change", async (ev) => {
  const t = ev.target;
  try {
    if (t.dataset.nicheStatus) { await api(`/api/control/niches/${t.dataset.nicheStatus}`, { method: "PATCH", body: JSON.stringify({ status: t.value }) }); toast("Status do nicho atualizado."); }
    else if (t.dataset.nicheRank) { await api(`/api/control/niches/${t.dataset.nicheRank}`, { method: "PATCH", body: JSON.stringify({ rank: Number(t.value) }) }); toast("Prioridade atualizada."); }
    else return;
    t.blur(); refreshNiches();
  } catch (e) { toast(e.message); }
});
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-niche-focus]"); if (!b) return;
  try { const r = await post(`/api/control/niches/${b.dataset.nicheFocus}/focus`); toast(`Foco: ${r.focus}. O próximo ciclo trabalha nele.`); refreshNiches(); refresh(); } catch (e) { toast(e.message); }
});

// ------------------------------------------------------------------ Conselho (reuniões entre os bots)
const OUTLOOK = { provavel: ["lucro provável", "b-approved"], incerto: ["lucro incerto", "b-warning"], improvavel: ["lucro improvável", "b-failed"] };
const usdN = (v) => (typeof v === "number" ? usd(v, 0) : "—");
async function refreshCouncil() {
  try {
    const list = await api("/api/office/council?limit=5");
    $("#council-list").innerHTML = list.map((m, idx) => {
      const n = (id) => esc(m.names[id] || id);
      const memo = m.memo || {};
      const [ol, oc] = OUTLOOK[memo.profit_outlook] || ["", ""];
      const head = `<strong>${esc(m.topic)}</strong> <span class="muted small">${dateBR(m.created_at)} ${time(m.created_at)} · ${esc(m.trigger)}${m.cost_usd ? " · " + usd(m.cost_usd, 4) : ""}</span> ${m.status === "running" ? badge("in_progress") : m.status === "failed" ? badge("failed") : `<span class="badge ${oc}">${esc(ol)}</span>`}`;
      if (m.status !== "done") return `<details class="card"${idx === 0 ? " open" : ""}><summary>${head}</summary>${m.error ? `<p class="muted small">${esc(m.error)}</p>` : '<p class="muted small">Reunião em andamento…</p>'}</details>`;
      const talk = (r) => `<li><strong>${n(r.agent)}</strong>: ${esc(r.output.position || r.output.revised_position || "")}${(r.output.replies || []).map((x) => `<div class="muted small">${x.agree ? "concorda com" : "discorda de"} ${n(x.to)}: ${esc(x.point)}</div>`).join("")}</li>`;
      return `<details class="card"${idx === 0 ? " open" : ""}><summary>${head}</summary>
        <p>${esc(memo.why || "")}</p>
        ${memo.scenarios?.length ? `<table class="tbl"><tr><th>Cenário</th><th class=num>Receita/mês em 12 meses</th><th class=num>Custo/mês</th><th>Empata em</th><th>Premissas (hipóteses)</th></tr>${memo.scenarios.map((sc) => `<tr><td>${esc(sc.name)}</td><td class=num>${usdN(sc.revenue_usd_month_12)}</td><td class=num>${usdN(sc.cost_usd_month)}</td><td>${sc.breakeven_month ? "mês " + esc(sc.breakeven_month) : "não empata"}</td><td class="small">${(sc.assumptions || []).map(esc).join("; ")}</td></tr>`).join("")}</table>` : ""}
        <div class="grid2">
          <div><h3>Decidido pelo Conselho</h3><ul class="small">${(memo.decisions || []).map((d) => `<li>${esc(d.text)} <span class="muted">— ${esc(d.why || "")}</span></li>`).join("") || "<li class=muted>nada</li>"}</ul>
            <p class="muted small">Aplicado: ${m.applied?.directives?.length || 0} diretriz(es)${m.applied?.focus ? ", novo foco: " + esc(m.applied.focus) : ""}; ${m.applied?.approvals?.length || 0} pedido(s) na sua fila de aprovação.</p></div>
          <div><h3>Para você (fundador)</h3><ul class="small">${(memo.founder_tasks || []).map((t) => `<li>${esc(t)}</li>`).join("")}${(memo.proposals_for_founder || []).map((p) => `<li>${esc(p.title)} <span class="muted">(${usdN(p.cost_usd)}) — ${esc(p.why || "")}</span></li>`).join("") || ""}</ul></div>
        </div>
        ${memo.dissent?.length ? `<p class="small"><strong>Divergências:</strong> ${memo.dissent.map((d) => `${esc(d.agent)}: ${esc(d.point)}`).join(" · ")}</p>` : ""}
        <details><summary class="small">Ver o debate completo</summary>
          <h3 class="small">Rodada 1 — posições</h3><ul class="small">${m.rounds.filter((r) => r.round === 1).map(talk).join("")}</ul>
          <h3 class="small">Rodada 2 — réplicas</h3><ul class="small">${m.rounds.filter((r) => r.round === 2).map(talk).join("")}</ul></details>
        ${memo.next_topic ? `<p class="muted small">Próximo tema sugerido: ${esc(memo.next_topic)}</p>` : ""}</details>`;
    }).join("") || '<p class="muted">Nenhuma reunião ainda. A primeira acontece na semana da primeira publicação, ou convoque agora.</p>';
  } catch (e) { /* segue */ }
}
$("#form-council").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const topic = $("#council-topic").value.trim() || "A empresa vai dar lucro? O que fazer para faturar e capitalizar?";
  await post("/api/control/council", { topic }); $("#council-topic").value = "";
  toast("Reunião convocada. Acompanhe no escritório virtual."); setTimeout(refreshCouncil, 1500);
});

// ------------------------------------------------------------------ viabilidade (veredito do Gauss)
const VERDICT = { aquecendo: ["aquecendo", "b-in_progress"], continuar: ["continuar", "b-approved"], ajustar: ["ajustar", "b-warning"], pivotar: ["pivotar", "b-warning"], encerrar: ["encerrar", "b-failed"] };
const MS = { cumprida: "✓", perdida: "✗", em_andamento: "…" };
async function refreshViability() {
  try {
    const [d, hubs] = await Promise.all([api("/api/office/viability"), api("/api/office/hubs")]);
    const t = d.targets;
    $("#via-targets").textContent = `metas: robôs até o dia ${t.bots_days} · citação e ${t.min_leads}+ lead até o dia ${t.traction_days} · receita ≥ custo até o dia ${t.revenue_days}`;
    const sel = $("#rev-hub"), cur = sel.value;
    sel.innerHTML = '<option value="">site inteiro</option>' + hubs.filter((h) => h.status === "published").map((h) => `<option value="${esc(h.id)}">${esc(h.title)}</option>`).join("");
    sel.value = cur;
    $("#via-hubs").innerHTML = d.hubs.map((h) => {
      const [lbl, cls] = VERDICT[h.verdict] || [h.verdict, ""];
      return `<div class="card"><h3>${esc(h.title)} <span class="badge ${cls}">${esc(lbl)}</span>${h.demo ? ' <span class="muted small">demonstração</span>' : ""}</h3>
        <p class="muted small">Dia ${num(h.days_live)} no ar · semana ${esc(h.week)} · histórico: ${h.history.map(esc).join(" → ")}</p>
        <p>${esc(h.summary)}</p>
        <ul class="ms">${h.milestones.map((m) => `<li class="ms-${esc(m.status)}"><span>${MS[m.status] || ""}</span> <strong>${esc(m.label)}</strong> <span class="muted small">até o dia ${num(m.due_day)} · ${esc(m.detail)}</span></li>`).join("")}</ul>
        ${h.actions.length ? `<p class="small"><strong>Próximos passos:</strong></p><ul class="small">${h.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}</div>`;
    }).join("") || '<p class="muted">Nenhum comparativo publicado ainda. O primeiro veredito sai na semana da publicação.</p>';
  } catch (e) { /* segue */ }
}
$("#via-run").addEventListener("click", async () => { await post("/api/control/viability/run"); toast("Veredito refeito."); refreshViability(); });

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t || !t.closest("#portal")) return;
  try {
    if (t.dataset.review) {
      const reviewer = $("#reviewer").value.trim();
      if (reviewer.length < 2) { toast("Informe seu nome como revisor antes de validar."); $("#reviewer").focus(); return; }
      await post(`/api/control/entities/${t.dataset.review}/review`, { reviewer }); toast("Ficha validada: selo publicado.");
    } else if (t.dataset.corr) { await post(`/api/control/corrections/${t.dataset.corr}`, { status: t.dataset.st }); toast("Pedido atualizado."); }
    else if (t.dataset.lead) {
      const id = t.dataset.lead, v = document.querySelector(`[data-lead-value="${id}"]`).value;
      await post(`/api/control/leads/${id}`, { status: document.querySelector(`[data-lead-status="${id}"]`).value, value_usd: v === "" ? null : Number(v) }); toast("Lead atualizado.");
    } else if (t.dataset.revoke) { await api(`/api/control/api-clients/${t.dataset.revoke}`, { method: "DELETE" }); toast("Chave revogada."); }
    else return;
    t.blur(); refreshPortal(); refresh();
  } catch (e) { if (e.message !== "401") toast("Erro: " + e.message); }
});
$("#form-api").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const r = await post("/api/control/api-clients", { name: $("#api-name").value, email: $("#api-email").value || null, daily_quota: Number($("#api-quota").value), monthly_price_usd: Number($("#api-price").value) });
  const box = $("#api-key-box"); box.classList.remove("hidden");
  box.innerHTML = `<p class="notice">Chave de <strong>${esc($("#api-name").value)}</strong> — copie agora, ela não aparece de novo:<br><code>${esc(r.api_key)}</code></p>`;
  $("#api-name").value = ""; document.activeElement.blur(); refreshPortal();
});
setInterval(() => { if (token && !$("#app").classList.contains("hidden")) refreshPortal(); }, 15000);

$("#form-focus").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const niche = $("#focus-custom").value.trim() || $("#focus-select").value;
  await api("/api/control/settings", { method: "PATCH", body: JSON.stringify({ focus_niche: niche }) });
  toast("Foco atualizado: o próximo ciclo do CVO usará este nicho."); refresh();
});
$("#form-gov").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/control/settings", { method: "PATCH", body: JSON.stringify({
    autonomy_level: Number($("#gov-autonomy").value), daily_llm_budget_usd: Number($("#gov-daily").value),
    monthly_budget_usd: Number($("#gov-monthly").value), score_threshold: Number($("#gov-threshold").value),
  }) });
  toast("Governança salva."); refresh();
});
$("#form-directive").addEventListener("submit", async (ev) => {
  ev.preventDefault(); await post("/api/control/directives", { text: $("#directive-text").value }); $("#directive-text").value = ""; refresh();
});
$("#form-revenue").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await post("/api/control/revenue", { stream: $("#rev-stream").value, amount_usd: Number($("#rev-amount").value), description: $("#rev-desc").value, hub_id: $("#rev-hub").value || null });
  $("#rev-amount").value = ""; $("#rev-desc").value = ""; toast("Receita registrada."); refresh();
});
$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault(); token = $("#token").value.trim();
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ok */ }
  start();
});

async function start() {
  if (!token) return showLogin();
  await refresh();
  if (!$("#app").classList.contains("hidden")) { await loadLog().catch(() => {}); connectStream(); refreshPortal(); refreshAiData(); refreshViability(); refreshCouncil(); refreshNiches(); refreshDiagnoses(); refreshSales(); }
}
setInterval(() => { if (token && !$("#app").classList.contains("hidden")) refresh(); }, 5000);
start();
