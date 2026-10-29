"use strict";
// Escritório virtual — piso isométrico (SVG) dirigido pelas mesmas APIs/SSE do dashboard.
// Cada agente real do backend ocupa uma mesa; mensagens do barramento viram "pacotes" que
// atravessam o andar, balões de fala e linhas na ata. Sem dependências externas.

// ------------------------------------------------------------------ utilidades
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = (v, d = 0) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const usd = (v, d = 2) => (v == null ? "—" : "US$ " + nf(v, d));
const pct = (v) => (v == null ? "—" : nf(v * 100, 1) + "%");
const hhmm = (iso) => { if (!iso) return ""; const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z"); return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

// ------------------------------------------------------------------ projeção isométrica
const T = 34, A = Math.cos(Math.PI / 6), B = 0.5;
const WU = 32, DU = 14, WALL_H = 3.2;
const OX = DU * A * T + 40, OY = WALL_H * T + 50;
const STAGE_W = Math.ceil((WU + DU) * A * T + 80), STAGE_H = Math.ceil((WU + DU) * B * T + WALL_H * T + 110);
const iso = (x, y, z = 0) => [OX + (x - y) * A * T, OY + (x + y) * B * T - z * T];
const pts = (list) => list.map((p) => iso(...p).map((n) => n.toFixed(1)).join(",")).join(" ");

function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const f = (c) => Math.max(0, Math.min(255, Math.round(c * (1 - k))));
  return "#" + [f(n >> 16), f((n >> 8) & 255), f(n & 255)].map((c) => c.toString(16).padStart(2, "0")).join("");
}
function box(parent, x, y, z, w, d, h, color, extra = {}) {
  const g = el("g", extra, parent);
  el("polygon", { points: pts([[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z + h], [x, y + d, z + h]]), fill: shade(color, 0.14) }, g);
  el("polygon", { points: pts([[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z + h], [x + w, y, z + h]]), fill: shade(color, 0.28) }, g);
  el("polygon", { points: pts([[x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h]]), fill: color }, g);
  return g;
}

// ------------------------------------------------------------------ organização do andar
const SECTOR_COLOR = { executive: "#a78bfa", research: "#38bdf8", tech: "#34d399", finance: "#fbbf24", quality: "#f472b6", radar: "#fb923c", comercial: "#22c55e", general: "#94a3b8" };
const ROOMS = [
  { sector: "executive", x0: 0, y0: 0, x1: 7, y1: 6, label: "DIRETORIA · CVO", floor: "#eeeafd" },
  { sector: "research", x0: 7, y0: 0, x1: 20, y1: 6, label: "PESQUISA & GEO", floor: "#e3f3fc" },
  { sector: "quality", x0: 0, y0: 6, x1: 7, y1: 14, label: "CONTROLE DE QUALIDADE", floor: "#fbe9f3" },
  { sector: "tech", x0: 7, y0: 6, x1: 13.5, y1: 14, label: "ENGENHARIA", floor: "#e1f7ee" },
  { sector: "finance", x0: 13.5, y0: 6, x1: 20, y1: 14, label: "FINANÇAS", floor: "#fcf3dc" },
  { sector: "radar", x0: 20, y0: 0, x1: 26, y1: 14, label: "RADAR DE ONDAS", floor: "#fdeedd" },
  { sector: "comercial", x0: 26, y0: 0, x1: 32, y1: 14, label: "COMERCIAL", floor: "#e6f4ea" },
];
// Persona exibida para cada agent_id real do backend.
const PEOPLE = {
  cvo: { name: "Atlas", role: "CVO", seat: [3.4, 2.1], skin: "#e0ac69", hair: "#2d2a32" },
  "quality.score": { name: "Juno", role: "Score", seat: [3.4, 8.9], skin: "#f1c27d", hair: "#7c2d12" },
  "scout.research": { name: "Íris", role: "Scout", seat: [9.2, 2.1], skin: "#c68642", hair: "#1f2937" },
  "research.market": { name: "Mercator", role: "Mercado", seat: [12.3, 2.1], skin: "#ffdbac", hair: "#6b4f2a" },
  "research.schema": { name: "Ontos", role: "Schema", seat: [15.4, 2.1], skin: "#8d5524", hair: "#111827" },
  "research.extraction": { name: "Vera", role: "Extração", seat: [18.4, 2.1], skin: "#f1c27d", hair: "#a16207" },
  "scout.tech": { name: "Turing", role: "Scout", seat: [8.9, 8.4], skin: "#e0ac69", hair: "#374151" },
  "tech.frontend": { name: "Ada", role: "Frontend", seat: [11.7, 8.4], skin: "#ffdbac", hair: "#4c1d95" },
  "tech.devops": { name: "Linus", role: "DevOps", seat: [10.2, 11.4], skin: "#f1c27d", hair: "#b45309" },
  "scout.finance": { name: "Pacioli", role: "Scout", seat: [15.4, 8.4], skin: "#c68642", hair: "#1f2937" },
  "finance.unit_economics": { name: "Gauss", role: "Unit Econ.", seat: [18.4, 8.4], skin: "#ffdbac", hair: "#9ca3af" },
  "finance.growth": { name: "Nash", role: "Growth", seat: [16.9, 11.4], skin: "#8d5524", hair: "#111827" },
  "scout.radar": { name: "Hermes", role: "Scout", seat: [21.6, 2.1], skin: "#f1c27d", hair: "#1f2937" },
  "radar.signals": { name: "Argos", role: "Sinais", seat: [24.6, 2.1], skin: "#c68642", hair: "#6b4f2a" },
  "radar.waves": { name: "Sibila", role: "Ondas", seat: [21.6, 7.6], skin: "#ffdbac", hair: "#7c2d12" },
  "radar.strategy": { name: "Odisseu", role: "Estratégia", seat: [24.6, 7.6], skin: "#8d5524", hair: "#111827" },
  "sales.prospector": { name: "Diana", role: "Prospecção", seat: [27.8, 2.1], skin: "#c68642", hair: "#7c2d12" },
  "sales.closer": { name: "Mercúrio", role: "Vendas", seat: [30.6, 2.1], skin: "#f1c27d", hair: "#111827" },
  "sales.success": { name: "Héstia", role: "Sucesso", seat: [29.2, 7.6], skin: "#ffdbac", hair: "#a16207" },
};
const PORTAL = { x: 5.9, y: 7.0 }; // de onde chegam ordens do fundador e do scheduler
const EXTERNAL = new Set(["founder", "scheduler", "system", "test", "dbg", "system:budget_guard"]);

const KIND_LABEL = {
  "cycle.start": "Novo ciclo", "objective.assign": "Briefing", "task.assign": "Delega", "review.request": "Pede revisão",
  "task.approved": "Aprovado", "task.revise": "Devolve", "task.escalated": "Escalona", "task.failed": "Falha",
  "sector.report": "Relatório", "founder.decision": "Decisão", "radar.start": "Varredura", "council.speech": "Conselho", "sales.update": "Comercial",
};
const KIND_COLOR = {
  "task.approved": "#34d399", "task.revise": "#fbbf24", "task.escalated": "#f87171", "task.failed": "#f87171",
  "review.request": "#f472b6", "sector.report": "#a78bfa", "objective.assign": "#a78bfa", "cycle.start": "#a78bfa", "founder.decision": "#a78bfa", "council.speech": "#38bdf8", "sales.update": "#22c55e",
};
const TASK_LABEL = { pending: "na fila", assigned: "atribuída", in_progress: "executando", in_review: "em revisão", revision: "refazendo", approved: "aprova", escalated: "escalada", failed: "falhou", cancelled: "cancelada" };

// ------------------------------------------------------------------ estado
const TOKEN_KEY = "geo-office-token";
let token = "";
try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* storage indisponível */ }
const S = { agents: new Map(), pos: new Map(), overview: null, active: null, follow: false, selected: "cvo", flash: new Map(), sceneKey: "", es: null, connected: false };
const cam = { z: 1, tx: 0, ty: 0 };

function person(id) {
  const p = PEOPLE[id];
  if (p) return p;
  return { name: id.split(".").pop(), role: id.split(".")[0], skin: "#e0ac69", hair: "#374151" };
}
function colorOf(id) {
  const a = S.agents.get(id);
  return SECTOR_COLOR[a?.sector] || (id === "cvo" ? SECTOR_COLOR.executive : SECTOR_COLOR.general);
}
function initials(id) { return person(id).name.slice(0, 2); }

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Founder-Token": token, ...(opts.headers || {}) } });
  if (res.status === 401) { showLogin("Token inválido."); throw new Error("401"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}
const post = (p, body = {}) => api(p, { method: "POST", body: JSON.stringify(body) });
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 3800);
}
function showLogin(err = "") { $("#login").classList.remove("hidden"); $("#app").classList.add("hidden"); $("#login-error").textContent = err; }

// ------------------------------------------------------------------ cena
function buildScene() {
  const svg = $("#scene");
  svg.innerHTML = "";
  svg.setAttribute("width", STAGE_W); svg.setAttribute("height", STAGE_H);
  svg.setAttribute("viewBox", `0 0 ${STAGE_W} ${STAGE_H}`);
  $("#stage").style.width = STAGE_W + "px"; $("#stage").style.height = STAGE_H + "px";

  // laje do piso + bordas frontais
  el("polygon", { points: pts([[0, DU, 0], [WU, DU, 0], [WU, DU, -0.4], [0, DU, -0.4]]), fill: "#9aa3b8" }, svg);
  el("polygon", { points: pts([[WU, 0, 0], [WU, DU, 0], [WU, DU, -0.4], [WU, 0, -0.4]]), fill: "#7d869c" }, svg);
  el("polygon", { points: pts([[0, 0, 0], [WU, 0, 0], [WU, DU, 0], [0, DU, 0]]), fill: "#f4f5f9" }, svg);

  // paredes do fundo
  el("polygon", { points: pts([[0, 0, 0], [WU, 0, 0], [WU, 0, WALL_H], [0, 0, WALL_H]]), fill: "#e4e7ef" }, svg);
  el("polygon", { points: pts([[0, 0, 0], [0, DU, 0], [0, DU, WALL_H], [0, 0, WALL_H]]), fill: "#cfd4e0" }, svg);
  el("polygon", { points: pts([[0, 0, WALL_H], [WU, 0, WALL_H], [WU, -0.2, WALL_H], [0, -0.2, WALL_H]]), fill: "#b9c0d0" }, svg);
  el("polygon", { points: pts([[0, 0, WALL_H], [0, DU, WALL_H], [-0.2, DU, WALL_H], [-0.2, 0, WALL_H]]), fill: "#aab2c4" }, svg);

  const backWall = el("g", { transform: `matrix(${A * T},${B * T},0,${T},${OX},${OY})` }, svg);
  for (const x of [7.6, 10.4, 13.2, 16.0]) {
    el("rect", { x, y: -2.7, width: 2.2, height: 1.6, fill: "#bfdbfe", stroke: "#94a3b8", "stroke-width": 0.05 }, backWall);
    el("line", { x1: x + 1.1, x2: x + 1.1, y1: -2.7, y2: -1.1, stroke: "#94a3b8", "stroke-width": 0.05 }, backWall);
  }
  // telão do radar
  el("rect", { x: 20.6, y: -2.7, width: 4.8, height: 1.7, rx: 0.08, fill: "#2a1606", stroke: "#fb923c", "stroke-width": 0.06 }, backWall);
  const rd = el("text", { x: 23, y: -1.95, "font-size": 0.4, "text-anchor": "middle", fill: "#fdba74", "font-weight": 800, "letter-spacing": 0.04 }, backWall); rd.textContent = "RADAR DE ONDAS";
  const rd2 = el("text", { x: 23, y: -1.45, "font-size": 0.2, "text-anchor": "middle", fill: "#fed7aa" }, backWall); rd2.textContent = "anúncios · compras por IA · GEO";
  // quadro do schema (pesquisa) e quadro estratégico (diretoria)
  el("rect", { x: 18.4, y: -2.6, width: 1.3, height: 1.3, fill: "#fff", stroke: "#38bdf8", "stroke-width": 0.06 }, backWall);
  const sch = el("text", { x: 19.05, y: -1.85, "font-size": 0.26, "text-anchor": "middle", fill: "#0369a1", "font-weight": 800 }, backWall); sch.textContent = "@graph";
  el("rect", { x: 1.2, y: -2.6, width: 4.4, height: 1.5, rx: 0.08, fill: "#1e1b3a", stroke: "#a78bfa", "stroke-width": 0.06 }, backWall);
  const brand = el("text", { x: 3.4, y: -1.95, "font-size": 0.42, "text-anchor": "middle", fill: "#c4b5fd", "font-weight": 800, "letter-spacing": 0.03 }, backWall); brand.textContent = "GEO OFFICE";
  const sub = el("text", { x: 3.4, y: -1.5, "font-size": 0.22, "text-anchor": "middle", fill: "#a5b4fc" }, backWall); sub.textContent = "HUB SEMÂNTICO DE DADOS";

  const leftWall = el("g", { transform: `matrix(${A * T},${-B * T},0,${T},${OX},${OY})` }, svg);
  // painel de qualidade na parede esquerda
  el("rect", { x: -12.2, y: -2.7, width: 4.6, height: 1.7, rx: 0.08, fill: "#2a1029", stroke: "#f472b6", "stroke-width": 0.06 }, leftWall);
  const q1 = el("text", { x: -9.9, y: -1.95, "font-size": 0.34, "text-anchor": "middle", fill: "#f9a8d4", "font-weight": 800 }, leftWall); q1.textContent = "SCORE ≥ 0,75";
  const q2 = el("text", { x: -9.9, y: -1.45, "font-size": 0.2, "text-anchor": "middle", fill: "#fbcfe8", id: "wall-score" }, leftWall); q2.textContent = "grounding · schema · alinhamento";
  for (const y of [-5.6, -3.8]) el("rect", { x: y, y: -2.6, width: 1.5, height: 1.5, fill: "#bfdbfe", stroke: "#94a3b8", "stroke-width": 0.05 }, leftWall);

  // tapetes e rótulos dos setores (plano do piso)
  const floor = el("g", { transform: `matrix(${A * T},${B * T},${-A * T},${B * T},${OX},${OY})` }, svg);
  for (const r of ROOMS) {
    const c = SECTOR_COLOR[r.sector];
    el("rect", { x: r.x0 + 0.18, y: r.y0 + 0.18, width: r.x1 - r.x0 - 0.36, height: r.y1 - r.y0 - 0.36, rx: 0.25, fill: r.floor, stroke: c, "stroke-width": 0.05, "stroke-dasharray": "0.25 0.15" }, floor);
    const t = el("text", { x: r.x0 + 0.45, y: r.y1 - 0.45, "font-size": r.label.length > 16 ? 0.4 : 0.5, fill: shade(c, 0.25), "font-weight": 800, "letter-spacing": 0.06, opacity: 0.85 }, floor);
    t.textContent = r.label;
  }
  // portal do fundador
  el("circle", { cx: PORTAL.x, cy: PORTAL.y, r: 0.55, fill: "#ede9fe", stroke: "#7c6cf6", "stroke-width": 0.06 }, floor);
  const pt = el("text", { x: PORTAL.x, y: PORTAL.y + 0.12, "font-size": 0.26, "text-anchor": "middle", fill: "#5b4fd6", "font-weight": 800 }, floor); pt.textContent = "FUNDADOR";

  // objetos ordenados por profundidade
  const items = [];
  const add = (key, draw) => items.push({ key, draw });

  // divisórias baixas de vidro (segmentadas para ordenar corretamente)
  const glass = "#cbd5e1";
  for (let y = 0; y < DU; y += 1) if (!((y >= 3 && y < 5) || (y >= 9 && y < 11))) add(7 + y + 0.5, (g) => box(g, 6.94, y, 0, 0.12, 1, 0.5, glass, { opacity: 0.85 }));
  for (let x = 0; x < WU; x += 1) if (!((x >= 3 && x < 5) || (x >= 10 && x < 12) || (x >= 16 && x < 18))) add(x + 6.5, (g) => box(g, x, 5.94, 0, 1, 0.12, 0.5, glass, { opacity: 0.85 }));
  for (let y = 6; y < DU; y += 1) if (!(y >= 9 && y < 11)) add(13.5 + y + 0.5, (g) => box(g, 13.44, y, 0, 0.12, 1, 0.5, glass, { opacity: 0.85 }));

  for (let y = 0; y < DU; y += 1) if (!((y >= 3 && y < 5) || (y >= 9 && y < 11))) add(20 + y + 0.5, (g) => box(g, 19.94, y, 0, 0.12, 1, 0.5, glass, { opacity: 0.85 }));
  // antena do radar
  add(23 + 11.8, (g) => {
    box(g, 22.6, 11.4, 0, 0.8, 0.8, 0.6, "#9a3412");
    const [cx, cy] = iso(23, 11.8, 1.5);
    el("ellipse", { cx, cy, rx: 26, ry: 14, fill: "#fed7aa", stroke: "#c2410c", "stroke-width": 2 }, g);
    el("line", { x1: cx, y1: cy, x2: cx + 10, y2: cy - 16, stroke: "#c2410c", "stroke-width": 2 }, g);
    el("circle", { cx: cx + 10, cy: cy - 16, r: 3, fill: "#fb923c", class: "led" }, g);
  });
  // mesa de reunião da diretoria
  add(3.4 + 4.6, (g) => { box(g, 1.4, 4.1, 0, 4.0, 1.0, 0.5, "#d6c9f7"); for (const x of [1.9, 3.1, 4.3]) box(g, x, 5.25, 0, 0.5, 0.45, 0.32, "#6d5bd0"); });
  // mesa de dados na pesquisa
  add(13.5 + 4.6, (g) => { box(g, 10.5, 4.0, 0, 6.0, 1.0, 0.5, "#cfe9f7"); for (let i = 0; i < 5; i++) box(g, 11 + i * 1.1, 4.25, 0.5, 0.6, 0.45, 0.04, "#ffffff"); });
  // racks de servidor
  for (const [x, y] of [[12.3, 11.0], [12.3, 12.2]]) add(x + y + 0.9, (g) => {
    box(g, x, y, 0, 0.9, 1.0, 2.0, "#1f2937");
    for (let i = 0; i < 6; i++) { const [lx, ly] = iso(x + 0.9, y + 0.2 + (i % 3) * 0.3, 0.4 + Math.floor(i / 3) * 0.9); el("circle", { cx: lx, cy: ly, r: 2.2, fill: i % 2 ? "#34d399" : "#60a5fa", class: "led" }, g); }
  });
  // cofre das finanças
  add(19.1 + 12.4, (g) => { box(g, 18.5, 11.8, 0, 1.2, 1.1, 1.2, "#374151"); const [cx, cy] = iso(19.7, 12.35, 0.6); el("circle", { cx, cy, r: 7, fill: "#9ca3af", stroke: "#111827", "stroke-width": 2 }, g); });
  // púlpito do Score Agent
  add(3.4 + 11.6, (g) => { box(g, 2.2, 11.2, 0, 2.4, 0.8, 0.9, "#f9c5df"); const [tx, ty] = iso(3.4, 12.0, 0.45); const t = el("text", { x: tx, y: ty, "font-size": 9, "text-anchor": "middle", fill: "#9d174d", "font-weight": 800 }, g); t.textContent = "QA GATE"; });
  // plantas
  for (const [x, y] of [[0.6, 0.6], [6.3, 0.6], [19.4, 0.6], [7.5, 13.3], [19.4, 6.6], [0.6, 13.3], [25.4, 13.3], [20.6, 13.3]]) add(x + y + 0.4, (g) => {
    box(g, x - 0.25, y - 0.25, 0, 0.5, 0.5, 0.45, "#a16207");
    const [px, py] = iso(x, y, 0.95);
    for (const [dx, dy, r] of [[0, 0, 13], [-8, 5, 10], [8, 5, 10], [0, -9, 9]]) el("circle", { cx: px + dx, cy: py + dy, r, fill: dy < 0 ? "#22c55e" : "#16a34a" }, g);
  });

  // mesas + agentes
  const ids = [...S.agents.keys()];
  let bench = 0;
  S.pos.clear();
  for (const id of ids) {
    let seat = PEOPLE[id]?.seat;
    if (!seat) { seat = [1.3 + (bench % 4) * 1.4, 6.9 + Math.floor(bench / 4) * 1.6]; bench++; }
    const [ax, ay] = seat;
    S.pos.set(id, seat);
    add(ax + ay, (g) => drawAgent(g, id, ax, ay));
    add(ax + ay + 0.68, (g) => drawDesk(g, id, ax, ay));
  }
  items.sort((a, b) => a.key - b.key);
  const world = el("g", {}, svg);
  for (const it of items) it.draw(world);
  el("g", { id: "fx" }, svg); // pacotes e trilhas por cima de tudo

  buildTags();
}

function drawDesk(g, id, ax, ay) {
  const big = id === "cvo";
  const w = big ? 2.2 : 1.7;
  box(g, ax - w / 2, ay + 0.3, 0, w, 0.75, 0.55, big ? "#c4b5fd" : "#e5e7eb");
  box(g, ax - 0.05, ay + 0.42, 0.55, 0.62, 0.42, 0.03, "#9ca3af");
  const lid = box(g, ax - 0.05, ay + 0.38, 0.58, 0.62, 0.05, 0.42, "#334155");
  lid.firstChild.classList.add("screen"); lid.firstChild.dataset.screen = id;
  box(g, ax - 0.75, ay + 0.55, 0.55, 0.32, 0.25, 0.16, "#f8fafc"); // caneca/papéis
}

function drawAgent(g, id, ax, ay) {
  const p = person(id), color = colorOf(id);
  const [x, y] = iso(ax, ay, 0);
  const a = el("g", { class: "agent", "data-agent": id, tabindex: 0, role: "button", "aria-label": `${p.name} — ${p.role}` }, g);
  el("ellipse", { cx: x, cy: y + 2, rx: 17, ry: 8, fill: "#0f172a", opacity: 0.12 }, a);
  el("ellipse", { class: "ring", cx: x, cy: y + 2, rx: 20, ry: 10 }, a);
  el("ellipse", { class: "sel", cx: x, cy: y + 2, rx: 24, ry: 12 }, a);
  box(a, ax - 0.32, ay - 0.45, 0, 0.64, 0.5, 0.42, "#1f2937"); // cadeira
  box(a, ax - 0.32, ay - 0.5, 0.42, 0.64, 0.1, 0.62, "#111827"); // encosto
  const body = el("g", { class: "body-g" }, a);
  el("path", { d: `M${x - 12},${y - 8} q0,-22 12,-24 q12,2 12,24 z`, fill: color }, body);
  el("path", { d: `M${x - 5},${y - 31} l5,6 l5,-6`, fill: "none", stroke: "#fff", "stroke-width": 1.4, opacity: 0.7 }, body);
  el("circle", { cx: x, cy: y - 41, r: 9, fill: p.skin }, body);
  el("path", { d: `M${x - 9.5},${y - 42} q0,-12 9.5,-12 q9.5,0 9.5,12 q-3,-6 -9.5,-6 q-6.5,0 -9.5,6 z`, fill: p.hair }, body);
  el("circle", { cx: x - 3.2, cy: y - 40.5, r: 1.1, fill: "#1f2937" }, body);
  el("circle", { cx: x + 3.2, cy: y - 40.5, r: 1.1, fill: "#1f2937" }, body);
  el("path", { d: `M${x - 3},${y - 36.5} q3,2 6,0`, fill: "none", stroke: "#7c2d12", "stroke-width": 1, "stroke-linecap": "round" }, body);
  a.addEventListener("click", () => select(id));
  a.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(id); } });
}

function anchor(id) {
  if (!S.pos.has(id)) return iso(PORTAL.x, PORTAL.y, 0.6);
  const [ax, ay] = S.pos.get(id);
  const [x, y] = iso(ax, ay, 0);
  return [x, y - 46];
}

// ------------------------------------------------------------------ overlay (tags, balões)
function buildTags() {
  const ov = $("#overlay");
  ov.querySelectorAll(".tag").forEach((n) => n.remove());
  for (const id of S.agents.keys()) {
    const [x, y] = anchor(id);
    const t = document.createElement("div");
    t.className = "tag"; t.dataset.tag = id;
    t.style.left = x + "px"; t.style.top = y - 10 + "px";
    t.innerHTML = `<span class="av" style="background:${colorOf(id)}">${esc(initials(id))}</span><span>${esc(person(id).name)}</span><span class="st idle"></span>`;
    t.addEventListener("click", () => select(id));
    ov.appendChild(t);
  }
  refreshAgentVisuals();
}

function statusFor(id) {
  const f = S.flash.get(id);
  if (f && f.until > Date.now()) return f;
  const a = S.agents.get(id);
  if (a?.status === "working") {
    const role = a.role;
    const label = role === "evaluator" ? "AVALIANDO" : role === "scout" ? "COORDENANDO" : role === "orchestrator" ? "DECIDINDO" : "TRABALHANDO";
    return { label, cls: "working" };
  }
  return { label: "", cls: "idle" };
}

function refreshAgentVisuals() {
  for (const id of S.agents.keys()) {
    const st = statusFor(id);
    const working = S.agents.get(id)?.status === "working";
    document.querySelector(`[data-agent="${CSS.escape(id)}"]`)?.classList.toggle("working", working);
    document.querySelector(`[data-agent="${CSS.escape(id)}"]`)?.classList.toggle("selected", id === S.selected);
    const scr = document.querySelector(`[data-screen="${CSS.escape(id)}"]`);
    if (scr) { scr.classList.toggle("on", working); scr.setAttribute("fill", working ? "#38bdf8" : "#2b3748"); }
    const tag = document.querySelector(`[data-tag="${CSS.escape(id)}"] .st`);
    if (tag) { tag.className = "st " + st.cls; tag.textContent = st.label; }
  }
}

function flash(id, label, cls, ms = 7000) { S.flash.set(id, { label, cls, until: Date.now() + ms }); refreshAgentVisuals(); setTimeout(refreshAgentVisuals, ms + 50); }

const bubbles = new Map();
function bubble(id, kind, html, color = null, ms = 5200) {
  const ov = $("#overlay");
  bubbles.get(id)?.remove(); bubbles.delete(id);
  while (bubbles.size >= 4) { const [oldId, old] = bubbles.entries().next().value; old.remove(); bubbles.delete(oldId); }
  const [x, y] = anchor(id);
  const b = document.createElement("div");
  b.className = "bubble";
  b.style.left = Math.max(130, Math.min(STAGE_W - 130, x)) + "px"; b.style.top = y - 22 + "px";
  const who = EXTERNAL.has(id) ? "Fundador" : person(id).name;
  b.innerHTML = `<div class="bh"><span class="av" style="background:${color || colorOf(id)}">${esc(who.slice(0, 1))}</span>${esc(who)}<span class="kind">${esc(kind)}</span></div>${html}`;
  ov.appendChild(b); bubbles.set(id, b);
  setTimeout(() => { b.classList.add("fade"); setTimeout(() => { b.remove(); if (bubbles.get(id) === b) bubbles.delete(id); }, 450); }, ms);
}

// ------------------------------------------------------------------ pacotes de mensagem
function packet(from, to, color) {
  const fx = document.getElementById("fx"); if (!fx) return;
  const [x1, y1] = EXTERNAL.has(from) ? iso(PORTAL.x, PORTAL.y, 0.4) : anchor(from);
  const [x2, y2] = EXTERNAL.has(to) ? iso(PORTAL.x, PORTAL.y, 0.4) : anchor(to);
  const cx = (x1 + x2) / 2, cy = Math.min(y1, y2) - 50 - Math.abs(x2 - x1) * 0.08;
  const trail = el("path", { d: `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`, class: "trail", stroke: color }, fx);
  const dot = el("circle", { r: 5, fill: color, class: "packet", style: `color:${color}` }, fx);
  const t0 = performance.now(), dur = 950;
  const step = (now) => {
    const t = Math.min(1, (now - t0) / dur), e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    const px = (1 - e) ** 2 * x1 + 2 * (1 - e) * e * cx + e * e * x2, py = (1 - e) ** 2 * y1 + 2 * (1 - e) * e * cy + e * e * y2;
    dot.setAttribute("cx", px); dot.setAttribute("cy", py);
    if (t < 1) requestAnimationFrame(step);
    else { dot.remove(); trail.animate([{ opacity: 0.55 }, { opacity: 0 }], { duration: 700 }).onfinish = () => trail.remove(); }
  };
  requestAnimationFrame(step);
}

// ------------------------------------------------------------------ câmera
const vp = () => $("#viewport");
function applyCam(smooth = false) {
  const st = $("#stage");
  st.classList.toggle("smooth", smooth);
  st.style.transform = `translate(${cam.tx}px,${cam.ty}px) scale(${cam.z})`;
  $("#zoom-label").textContent = Math.round(cam.z * 100) + "%";
}
function fit(smooth = false) {
  const r = vp().getBoundingClientRect();
  cam.z = Math.max(0.3, Math.min(1.6, Math.min(r.width / STAGE_W, (r.height - 40) / STAGE_H)));
  cam.tx = (r.width - STAGE_W * cam.z) / 2; cam.ty = (r.height - STAGE_H * cam.z) / 2 - 18;
  applyCam(smooth);
}
function zoomAt(f, px, py) {
  const nz = Math.max(0.3, Math.min(2.6, cam.z * f));
  cam.tx = px - ((px - cam.tx) * nz) / cam.z; cam.ty = py - ((py - cam.ty) * nz) / cam.z; cam.z = nz;
  applyCam();
}
function centerOn(id, smooth = true) {
  const r = vp().getBoundingClientRect();
  const [x, y] = anchor(id);
  if (cam.z < 1) cam.z = 1.15;
  cam.tx = r.width / 2 - x * cam.z; cam.ty = r.height / 2 - (y + 30) * cam.z;
  applyCam(smooth);
}
function setupCamera() {
  const v = vp();
  let drag = null;
  v.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".controls,.cycle-card,.tag,.agent")) return;
    drag = { x: e.clientX, y: e.clientY, tx: cam.tx, ty: cam.ty }; v.classList.add("dragging"); v.setPointerCapture(e.pointerId);
  });
  v.addEventListener("pointermove", (e) => { if (!drag) return; cam.tx = drag.tx + e.clientX - drag.x; cam.ty = drag.ty + e.clientY - drag.y; applyCam(); });
  const end = () => { drag = null; v.classList.remove("dragging"); };
  v.addEventListener("pointerup", end); v.addEventListener("pointercancel", end);
  v.addEventListener("wheel", (e) => { e.preventDefault(); const r = v.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  $("#zoom-in").onclick = () => { const r = v.getBoundingClientRect(); zoomAt(1.2, r.width / 2, r.height / 2); };
  $("#zoom-out").onclick = () => { const r = v.getBoundingClientRect(); zoomAt(1 / 1.2, r.width / 2, r.height / 2); };
  $("#zoom-fit").onclick = () => { S.follow = false; updateFollowBtn(); fit(true); };
  window.addEventListener("resize", () => (S.follow ? centerOn(S.selected, false) : fit()));
}
function updateFollowBtn() {
  const b = $("#btn-follow");
  b.setAttribute("aria-pressed", String(S.follow));
  b.textContent = (S.follow ? "Seguindo " : "Seguir ") + person(S.selected).name;
}

// ------------------------------------------------------------------ seleção / painel do agente
async function select(id) {
  S.selected = id; updateFollowBtn(); refreshAgentVisuals();
  if (S.follow) centerOn(id);
  const a = S.agents.get(id); if (!a) return;
  const p = person(id), panel = $("#agent-panel");
  panel.classList.remove("hidden");
  const st = statusFor(id);
  panel.innerHTML = `
    <div class="ap-head"><span class="av" style="background:${colorOf(id)}">${esc(initials(id))}</span>
      <div><strong>${esc(p.name)} · ${esc(a.title)}</strong><div class="muted small">${esc(a.agent_id)} · setor ${esc(a.sector)} · ${esc(a.role)}</div></div>
      <span class="badge b-${a.status === "working" ? "working" : "idle"}">${esc(st.label || "ocioso")}</span>
      <button class="btn close" id="ap-follow">Seguir</button><button class="btn" id="ap-close" aria-label="Fechar">✕</button></div>
    <div class="grid">
      <div class="kv"><span class="muted small">Mensagens processadas</span><b>${nf(a.processed)}</b></div>
      <div class="kv"><span class="muted small">Falhas</span><b>${nf(a.failures)}</b></div>
      <div class="kv"><span class="muted small">Nota média (Score)</span><b>${a.avg_score == null ? "—" : nf(a.avg_score, 2)}</b></div>
      <div class="kv"><span class="muted small">Atividade atual</span><b style="font-size:12px">${esc(a.status === "working" ? a.current_activity : "aguardando mensagens")}</b></div>
    </div>
    <div style="margin-top:8px">${(a.skills || []).map((s) => `<span class="pill">${esc(s)}</span>`).join("") || '<span class="muted small">sem skills</span>'}</div>
    <div class="grid" style="margin-top:10px"><div class="kv" id="ap-task"><span class="muted small">Tarefa atual</span><div class="muted">—</div></div>
    <div class="kv"><span class="muted small">Últimas mensagens</span><ol class="minutes" id="ap-msgs" style="max-height:180px"></ol></div></div>`;
  $("#ap-close").onclick = () => panel.classList.add("hidden");
  $("#ap-follow").onclick = () => { S.follow = true; updateFollowBtn(); centerOn(id); };
  try {
    const msgs = await api(`/api/office/messages?agent=${encodeURIComponent(id)}&limit=8`);
    $("#ap-msgs").innerHTML = msgs.map((m) => `<li><span class="av" style="background:${colorOf(m.sender)}">${esc(EXTERNAL.has(m.sender) ? "F" : initials(m.sender))}</span><div><div class="h">${esc(KIND_LABEL[m.type] || m.type)} <span class="muted">${esc(m.sender)} → ${esc(m.recipient)} · ${hhmm(m.created_at)}</span></div>${esc(m.summary)}</div></li>`).join("") || '<li class="muted">Sem mensagens.</li>';
    const mine = (S.active?.tasks || []).filter((t) => t.assignee_id === id);
    const taskId = a.current_task_id || (mine.find((t) => !["approved", "cancelled"].includes(t.status)) || mine[0])?.id;
    if (taskId) {
      const t = await api(`/api/office/tasks/${taskId}`);
      const last = t.evaluations?.at(-1);
      $("#ap-task").innerHTML = `<span class="muted small">Tarefa atual</span><div><strong>${esc(t.title)}</strong> <span class="badge b-${esc(t.status)}">${esc(TASK_LABEL[t.status] || t.status)}</span></div>
        <div class="muted small">revisões ${nf(t.revisions)} · nota ${t.last_score == null ? "—" : nf(t.last_score, 2)}</div>
        ${last ? `<div class="small" style="margin-top:4px">${esc(last.feedback).slice(0, 280)}</div>` : ""}`;
    }
  } catch { /* painel é best-effort */ }
}

// ------------------------------------------------------------------ painéis laterais
function tcell(label, value, sub = "", meter = null, kind = "spend", cls = "") {
  let m = "";
  if (meter != null) {
    const r = Math.max(0, Math.min(1, meter));
    const c = kind === "spend" ? (r > 0.9 ? "bad" : r > 0.7 ? "warn" : "") : (r >= 0.8 ? "good" : r >= 0.6 ? "warn" : "bad");
    m = `<div class="meter ${c}"><i style="width:${(r * 100).toFixed(1)}%"></i></div>`;
  }
  return `<div class="tcell ${cls}"><div class="l">${esc(label)}</div><div class="v">${value}</div><div class="s">${sub}</div>${m}</div>`;
}

function renderTelemetry(ov) {
  const f = ov.finance, b = ov.business, o = ov.office;
  const working = [...S.agents.values()].filter((a) => a.status === "working").length;
  const queued = Object.values(ov.queues || {}).reduce((a, n) => a + n, 0);
  $("#tele").innerHTML = [
    tcell("LLM hoje", usd(f.today.llm, 4), `orçamento ${usd(f.today.llm_budget)}`, f.today.llm_budget ? f.today.llm / f.today.llm_budget : null),
    tcell("Gasto no mês", usd(f.month.total), `orçamento ${usd(f.month.budget, 0)}`, f.month.budget ? f.month.total / f.month.budget : null),
    tcell("Caixa", usd(f.cash), f.runway_days == null ? "runway ∞" : `runway ${nf(f.runway_days)} dias`),
    tcell("Receita real", usd(f.revenue.real), `projetada ${usd(f.revenue.projected, 0)}/mês`),
    tcell("Entidades publicadas", nf(b.entities_published), `${nf(b.entities_validated)} validadas · ${nf(b.hubs_published)} hubs`),
    tcell("Grounding médio", pct(b.avg_grounding), "valores com evidência literal", b.avg_grounding, "quality"),
    tcell("Nota média · Score", b.avg_score == null ? "—" : nf(b.avg_score, 2), `aprovação ${pct(b.approval_rate)}`, b.avg_score, "quality"),
    tcell("Agentes ativos", `${working}/${S.agents.size}`, `${nf(queued)} msg na fila · ${o.pending_approvals} aprovações`),
  ].join("");
  $("#tele-time").textContent = "atualizado " + new Date().toLocaleTimeString("pt-BR");
  $("#ticker").innerHTML = [
    ["Hubs", nf(b.hubs_published)], ["Entidades", nf(b.entities_published)], ["LLM hoje", usd(f.today.llm, 3)], ["Caixa", usd(f.cash, 0)],
  ].map(([k, v]) => `<span class="tick">${esc(k)}<b>${esc(v)}</b></span>`).join("");
  const mode = $("#mode-chip");
  mode.textContent = o.llm_provider === "mock" ? "SIMULAÇÃO" : "IA REAL · " + o.llm_provider.toUpperCase();
  mode.classList.toggle("real", o.llm_provider !== "mock");
  const live = $("#live-chip");
  live.className = "chip live" + (!S.connected ? " off" : o.paused ? " paused" : "");
  live.querySelector("span").textContent = !S.connected ? "Offline" : o.paused ? "Pausado" : "Ao vivo";
  $("#btn-pause").textContent = o.paused ? "Retomar" : "Pausar";
  $("#floor-sub").textContent = `${S.agents.size} agentes · ${working} trabalhando · foco: ${o.focus_niche}`;
}

function renderAgenda(obj, tasks) {
  const card = $("#cycle-card");
  if (!obj) {
    $("#agenda").innerHTML = '<p class="muted">Nenhum ciclo ativo. O CVO abre o próximo no intervalo programado — ou use “Rodar ciclo”.</p>';
    card.innerHTML = `<div class="row-a"><strong>Sem ciclo ativo</strong></div><div class="muted small">O escritório está aguardando o próximo ciclo estratégico.</div>`;
    return;
  }
  const phases = obj.plan?.phases || [];
  const done = tasks.filter((t) => t.status === "approved").length;
  const chips = phases.map((p) => {
    const sectors = p.assignments.map((a) => a.sector);
    const finished = sectors.every((s) => obj.sector_status?.[s]);
    const cls = finished ? "done" : p.phase === obj.current_phase ? "now" : "";
    return `<span class="${cls}">Fase ${p.phase}: ${esc(sectors.join(" + "))}</span>`;
  }).join("");
  $("#agenda").innerHTML = `<div><strong>${esc(obj.title)}</strong> <span class="badge b-${esc(obj.status)}">${esc(obj.status.replace(/_/g, " "))}</span></div>
    <div class="muted small">${esc(obj.niche)}</div><div class="phase">${chips}</div>
    <ul class="tasks">${tasks.map((t) => `<li><span>${esc(person(t.assignee_id).name)} · ${esc(t.title)}</span><span class="badge b-${esc(t.status)}">${esc(TASK_LABEL[t.status] || t.status)}${t.last_score != null ? " " + nf(t.last_score, 2) : ""}</span></li>`).join("") || '<li class="muted">Scouts decompondo o objetivo…</li>'}</ul>`;
  const short = obj.id.slice(0, 6);
  card.innerHTML = `<div class="row-a"><strong>Ciclo #${esc(short)}</strong><span class="muted small">fase ${esc(obj.current_phase)}/${phases.length}</span></div>
    ${tasks.slice(0, 7).map((t) => `<div class="row-a"><span class="who"><i class="dotc" style="background:${colorOf(t.assignee_id)}"></i>${esc(person(t.assignee_id).name)}</span><span class="badge b-${esc(t.status)}">${esc(TASK_LABEL[t.status] || t.status)}</span></div>`).join("")}
    <div class="prog"><i style="width:${tasks.length ? (done / tasks.length) * 100 : 0}%"></i></div>
    <div class="muted small">${done}/${tasks.length} entregas aprovadas pelo Score Agent</div>`;
}

function renderApprovals(list) {
  $("#appr-count").textContent = list.length;
  $("#approvals").innerHTML = list.length ? list.map((a) => `<div class="appr"><div><span class="badge b-pending">${esc(a.kind.replace(/_/g, " "))}</span> <strong>${esc(a.title)}</strong></div>
    <div class="muted small">${esc(a.requested_by)} · ${hhmm(a.created_at)}${a.amount_usd != null ? " · " + usd(a.amount_usd) : ""}</div>
    <div class="row"><button class="btn primary" data-approve="${esc(a.id)}">Aprovar</button><button class="btn danger" data-reject="${esc(a.id)}">Rejeitar</button></div></div>`).join("")
    : '<p class="muted">Nada aguardando sua decisão.</p>';
}

const MINUTE_TYPES = new Set(["sales.update", "council.speech", "cycle.start", "objective.assign", "sector.report", "task.approved", "task.revise", "task.escalated", "task.failed", "founder.decision"]);
function minute(who, title, text, at, color = null) {
  const ol = $("#minutes");
  const li = document.createElement("li");
  const name = EXTERNAL.has(who) ? "Fundador" : who === "system" ? "Sistema" : person(who).name;
  li.innerHTML = `<span class="av" style="background:${color || colorOf(who)}">${esc(name.slice(0, 1))}</span><div><div class="h">${esc(name)}<span class="muted">${hhmm(at)}</span> <span class="badge">${esc(title)}</span></div>${esc(text)}</div>`;
  ol.insertBefore(li, ol.firstChild);
  while (ol.children.length > 80) ol.removeChild(ol.lastChild);
}

// ------------------------------------------------------------------ dados
async function refresh() {
  try {
    const [ov, agents, objs, approvals] = await Promise.all([api("/api/office/overview"), api("/api/office/agents"), api("/api/office/objectives?limit=4"), api("/api/office/approvals")]);
    $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
    S.overview = ov;
    S.agents = new Map(agents.map((a) => [a.agent_id, a]));
    const key = agents.map((a) => a.agent_id).join("|");
    if (key !== S.sceneKey) { S.sceneKey = key; buildScene(); if (!S.follow) fit(); updateFollowBtn(); }
    const obj = objs.find((o) => ["planning", "active", "consolidating", "awaiting_approval"].includes(o.status)) || null;
    const tasks = obj ? await api(`/api/office/tasks?objective_id=${obj.id}&limit=60`) : [];
    tasks.sort((a, b) => (a.sector + a.title).localeCompare(b.sector + b.title));
    S.active = obj ? { ...obj, tasks } : null;
    renderTelemetry(ov); renderAgenda(obj, tasks); renderApprovals(approvals); refreshAgentVisuals();
  } catch (e) {
    if (e.message !== "401") { S.connected = false; const l = $("#live-chip"); l.className = "chip live off"; l.querySelector("span").textContent = "Offline"; }
  }
}

async function seedMinutes() {
  const msgs = await api("/api/office/messages?limit=60");
  $("#minutes").innerHTML = "";
  msgs.filter((m) => MINUTE_TYPES.has(m.type)).reverse().forEach((m) => minute(m.sender, KIND_LABEL[m.type] || m.type, m.summary, m.created_at));
}

function onEvent(e) {
  if (e.event === "message") {
    const color = KIND_COLOR[e.type] || colorOf(e.sender);
    packet(e.sender, e.recipient, color);
    if (e.type === "review.request") flash(e.sender, "EM REVISÃO", "working", 4000);
    else bubble(e.sender, KIND_LABEL[e.type] || e.type, `<div>${esc(e.summary)}</div><div class="muted small" style="color:#6b7280;margin-top:3px">→ ${esc(EXTERNAL.has(e.recipient) ? "Fundador" : person(e.recipient).name)}</div>`, EXTERNAL.has(e.sender) ? "#7c6cf6" : null);
    if (e.type === "task.escalated") flash(e.recipient, "ESCALADO", "bad");
    if (MINUTE_TYPES.has(e.type)) minute(e.sender, KIND_LABEL[e.type] || e.type, e.summary, e.at);
    if (S.follow && (e.sender === S.selected || e.recipient === S.selected)) centerOn(S.selected);
    if (["sector.report", "objective.assign", "task.approved", "task.revise", "cycle.start"].includes(e.type)) debounceRefresh();
  } else if (e.event === "agent_status") {
    const a = S.agents.get(e.agent_id);
    if (a) { a.status = e.status; a.current_activity = e.activity; a.current_task_id = e.task_id; refreshAgentVisuals(); }
  } else if (e.event === "evaluation") {
    const ok = e.passed, sc = Number(e.score);
    bubble("quality.score", ok ? "Aprova" : "Reprova", `<div><strong>${esc(person(e.assignee).name)}</strong> · ${esc(String(e.kind).replace(/_/g, " "))}</div>
      <div class="bar"><i style="width:${(sc * 100).toFixed(0)}%;background:${ok ? "#10b981" : "#f59e0b"}"></i></div><div style="margin-top:3px">Nota ${nf(sc, 2)} ${ok ? "— dentro do padrão" : "— volta para revisão"}</div>`, ok ? "#10b981" : "#f59e0b");
    flash(e.assignee, ok ? "APROVA" : "REVISAR", ok ? "ok" : "rev");
    minute("quality.score", ok ? "Aprovado" : "Reprovado", `${person(e.assignee).name}: ${String(e.kind).replace(/_/g, " ")} — nota ${nf(sc, 2)}`, e.at);
  } else if (e.event === "alert") {
    if (e.level !== "info") toast(`${e.source}: ${e.message}`);
    minute(e.source in PEOPLE ? e.source : "system", e.level === "info" ? "Nota" : "Alerta", e.message, e.at, e.level === "critical" ? "#f87171" : e.level === "warning" ? "#fbbf24" : "#94a3b8");
  } else if (e.event === "council") {
    if (e.status === "started") toast(`Reunião do Conselho: ${e.topic}`);
    else if (e.status === "done") toast(`Conselho encerrado — lucro ${e.outlook}. Ata no painel.`);
    else if (e.status === "failed") toast("A reunião do Conselho não terminou (veja o painel).");
  } else if (e.event === "hub_published") {
    toast(`Hub publicado com ${e.entities} entidades.`);
    minute("cvo", "Publicação", `Hub publicado com ${e.entities} entidades verificadas.`, e.at);
  } else if (["objective", "office_paused", "office_resumed", "settings_changed", "approval_requested", "founder_decision"].includes(e.event)) {
    debounceRefresh();
  }
}
let refreshTimer = null;
function debounceRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 400); }

function connectStream() {
  if (S.es) S.es.close();
  S.es = new EventSource("/api/office/stream?token=" + encodeURIComponent(token));
  S.es.onopen = () => { S.connected = true; if (S.overview) renderTelemetry(S.overview); };
  S.es.onerror = () => { S.connected = false; if (S.overview) renderTelemetry(S.overview); };
  S.es.onmessage = (ev) => { try { onEvent(JSON.parse(ev.data)); } catch { /* evento malformado */ } };
}

// ------------------------------------------------------------------ ações
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.id === "btn-cycle") { await post("/api/control/cycle"); toast("Ciclo solicitado ao CVO."); }
    else if (t.id === "btn-pause") { const p = S.overview?.office.paused; await post(p ? "/api/control/resume" : "/api/control/pause"); toast(p ? "Escritório retomado." : "Escritório pausado — agentes terminam a mensagem atual e param."); }
    else if (t.id === "btn-follow") { S.follow = !S.follow; updateFollowBtn(); S.follow ? centerOn(S.selected) : fit(true); return; }
    else if (t.id === "btn-kill") { $("#kill-dialog").showModal(); return; }
    else if (t.id === "kill-cancel") { $("#kill-dialog").close(); return; }
    else if (t.id === "kill-confirm") { $("#kill-dialog").close(); const r = await post("/api/control/kill"); toast(`Kill switch: ${r.cancelled_objectives.length} ciclo(s) cancelado(s), ${r.purged_messages} mensagem(ns) descartada(s).`); }
    else if (t.dataset.approve) { await post(`/api/control/approvals/${t.dataset.approve}`, { approve: true }); toast("Aprovado."); }
    else if (t.dataset.reject) { await post(`/api/control/approvals/${t.dataset.reject}`, { approve: false }); toast("Rejeitado."); }
    else return;
    debounceRefresh();
  } catch (e) { if (e.message !== "401") toast("Erro: " + e.message); }
});
$("#form-directive").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#directive-text").value.trim(); if (!text) return;
  await post("/api/control/directives", { text });
  $("#directive-text").value = "";
  bubble("cvo", "Diretriz", `<div>Anotado: “${esc(text)}”. Entra no planejamento do próximo ciclo.</div>`);
  toast("Diretriz enviada ao CVO.");
});
$("#login-form").addEventListener("submit", (ev) => {
  ev.preventDefault(); token = $("#token").value.trim();
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ok */ }
  start();
});

async function start() {
  if (!token) return showLogin();
  await refresh();
  if ($("#app").classList.contains("hidden")) return;
  fit();
  await seedMinutes().catch(() => {});
  connectStream();
}
setupCamera();
setInterval(() => { if (token && !$("#app").classList.contains("hidden")) refresh(); }, 4000);
start();
