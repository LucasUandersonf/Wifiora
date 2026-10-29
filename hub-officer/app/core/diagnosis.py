"""Diagnóstico de Visibilidade em IA — o produto de entrada da agência.

Para uma marca (e seus concorrentes) num segmento:
  1. Perguntas de compra: o que um cliente pergunta ao ChatGPT antes de comprar nesse segmento.
  2. Visibilidade: cada pergunta é feita a uma IA; contamos quem é citado (marca x concorrentes).
     Com Claude + busca na web as respostas refletem a web atual; sem busca, é o conhecimento interno
     do modelo (estimativa) — o relatório diz qual modo foi usado.
  3. Prontidão técnica do site (código, sem IA): robôs de IA liberados no robots.txt, dados estruturados
     (JSON-LD), llms.txt, sitemap, título e descrição.
  4. Plano: ganhos rápidos (GEO) e rascunhos de anúncios no ChatGPT para as perguntas em que os
     concorrentes aparecem e a marca não.
Notas são determinísticas; o LLM só gera perguntas, respostas medidas e rascunhos do plano.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import unicodedata
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import func, select

from app.db import session_scope
from app.llm.base import BudgetExceeded
from app.models import CostEntry, Diagnosis

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)

AGENT = "research.market"  # o Mercator conduz o diagnóstico
MAX_QUERIES = 50
CONCURRENCY = 4
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot", "Google-Extended"]
USER_AGENT = "GeoOfficeDiagnostico/0.1 (+diagnostico de visibilidade em IA)"
_RUNNING: set[asyncio.Task[Any]] = set()


# ------------------------------------------------------------------ utilidades
def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


def host(url: str | None) -> str:
    return (urlparse(url or "").hostname or "").removeprefix("www.")


def parse_competitors(raw: list[Any] | str | None) -> list[dict[str, str]]:
    """Aceita lista de dicts ou texto ("Nome - site.com" por linha)."""
    items: list[dict[str, str]] = []
    if isinstance(raw, str):
        raw = [ln for ln in raw.splitlines() if ln.strip()]
    for it in raw or []:
        if isinstance(it, dict):
            name, site = str(it.get("name") or "").strip(), str(it.get("site") or "").strip()
        else:
            name, _, site = str(it).partition(" - ")
            name, site = name.strip(), site.strip()
        if name:
            items.append({"name": name[:120], "site": site[:300]})
    return items[:5]


def mentions(text: str, urls: list[str], name: str, site: str | None) -> bool:
    """A marca aparece na resposta? Por nome (sem acento/maiúscula) ou pelo domínio do site."""
    t = norm(text)
    n = norm(name)
    by_name = bool(n) and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", t) is not None
    h = host(site if site and "://" in site else f"https://{site}" if site else "")
    by_site = bool(h) and (h in t or any(h in host(u) for u in urls))
    return by_name or by_site


# ------------------------------------------------------------------ prontidão técnica (sem IA)
def robots_ai_access(robots_txt: str) -> dict[str, bool]:
    """Para cada robô de IA: o robots.txt bloqueia o site inteiro? (True = liberado)."""
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    for line in robots_txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
        elif key in ("disallow", "allow"):
            rules.append(f"{key}:{val}")
    if agents:
        groups.append((agents, rules))

    def blocked(group_rules: list[str]) -> bool:
        return "disallow:/" in group_rules and "allow:/" not in group_rules

    out: dict[str, bool] = {}
    star = next((r for a, r in groups if "*" in a), None)
    for bot in AI_BOTS:
        own = next((r for a, r in groups if bot.lower() in a), None)
        rules_for = own if own is not None else star
        out[bot] = not (rules_for is not None and blocked(rules_for))
    return out


def html_signals(html: str) -> dict[str, Any]:
    types: list[str] = []
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            doc = json.loads(block)
        except ValueError:
            continue
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                types.extend(t if isinstance(t, list) else [t] if t else [])
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I)
    return {
        "jsonld_types": sorted({str(t) for t in types}),
        "title": (title.group(1).strip()[:200] if title else ""),
        "meta_description": (desc.group(1).strip()[:300] if desc else ""),
        "html_kb": round(len(html.encode()) / 1024, 1),
    }


TECH_CHECKS = [
    ("https", "Site em HTTPS", 1),
    ("ia_liberada", "Robôs de IA liberados no robots.txt", 3),
    ("jsonld", "Dados estruturados (JSON-LD) na página inicial", 3),
    ("jsonld_empresa", "Dados da empresa (Organization/LocalBusiness) marcados", 2),
    ("sitemap", "Sitemap publicado", 1),
    ("llms_txt", "Arquivo llms.txt para IAs", 1),
    ("titulo_descricao", "Título e descrição da página preenchidos", 1),
]


async def technical(site: str, *, allow_fetch: bool) -> dict[str, Any]:
    base = site if "://" in site else f"https://{site}"
    if not site:
        return {"checked": False, "reason": "site não informado"}
    if not allow_fetch:
        return {"checked": False, "reason": "coleta web desativada neste ambiente (ALLOW_WEB_FETCH=false)"}
    if host(base).endswith(".invalid"):
        return {"checked": False, "reason": "domínio de demonstração"}
    origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=15) as c:

        async def get(url: str) -> httpx.Response | None:
            try:
                return await c.get(url)
            except httpx.HTTPError:
                return None

        home, robots, sitemap, llms = await asyncio.gather(get(base), get(urljoin(origin, "/robots.txt")), get(urljoin(origin, "/sitemap.xml")), get(urljoin(origin, "/llms.txt")))
    if home is None or home.status_code >= 400:
        return {"checked": False, "reason": f"não foi possível abrir {base}" + (f" (HTTP {home.status_code})" if home is not None else "")}
    sig = html_signals(home.text[:2_000_000])
    access = robots_ai_access(robots.text if robots is not None and robots.status_code < 400 else "")
    types = set(sig["jsonld_types"])
    checks = {
        "https": str(home.url).startswith("https://"),
        "ia_liberada": all(access.values()),
        "jsonld": bool(types),
        "jsonld_empresa": bool(types & {"Organization", "LocalBusiness", "Store", "OnlineStore", "Corporation"}),
        "sitemap": bool(sitemap is not None and sitemap.status_code < 400 and "<" in sitemap.text[:200]),
        "llms_txt": bool(llms is not None and llms.status_code < 400 and llms.text.strip() and "<html" not in llms.text[:200].lower()),
        "titulo_descricao": bool(sig["title"] and sig["meta_description"]),
    }
    return {"checked": True, "final_url": str(home.url), "checks": checks, "ai_access": access, **sig}


def tech_score(tech: dict[str, Any]) -> int | None:
    if not tech.get("checked"):
        return None
    total = sum(w for _, _, w in TECH_CHECKS)
    got = sum(w for k, _, w in TECH_CHECKS if tech["checks"].get(k))
    return round(100 * got / total)


# ------------------------------------------------------------------ visibilidade (IA)
async def _queries(office: Office, d: Diagnosis) -> list[str]:
    n = max(5, min(MAX_QUERIES, d.query_count or 10))
    out = await office.llm.complete_json(
        kind="diagnosis.queries",
        system="Você é um especialista em comportamento de compra no Brasil.",
        prompt=(
            f"Segmento: {d.category}. Cidade/região: {d.city or 'Brasil'}.\n"
            f"Liste {n} perguntas reais que um cliente faria ao ChatGPT ANTES de comprar nesse segmento "
            "(comparação, 'melhor', 'mais barato', 'vale a pena', 'onde comprar', 'alternativa a'). "
            "Português do Brasil, sem citar a marca analisada. Retorne JSON: {queries: [..]}"
        ),
        tier="worker", agent_id=AGENT, task_id=d.id, context={"category": d.category, "city": d.city, "n": n},
    )
    qs = [str(q).strip() for q in out.get("queries") or [] if str(q).strip()]
    return list(dict.fromkeys(qs))[:n]


async def _answers(office: Office, d: Diagnosis, queries: list[str], engine_ids: list[str]) -> list[dict[str, Any]]:
    """Cada pergunta em cada IA (com limite de concorrência). Falha de uma IA não derruba o relatório."""
    from app.core import engines

    sem = asyncio.Semaphore(CONCURRENCY)
    brands = [{"name": d.brand, "site": d.site}, *d.competitors]

    async def one(q: str, eng: str) -> dict[str, Any]:
        async with sem:
            try:
                ans = await engines.ask(office, eng, q, task_id=d.id, context={"brand": d.brand, "competitors": [c["name"] for c in d.competitors], "query": q})
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001
                return {"query": q, "engine": eng, "mentioned": [], "sources": [], "excerpt": "", "error": str(e)[:200]}
        mentioned = [b["name"] for b in brands if mentions(ans.text, ans.urls, b["name"], b.get("site"))]
        return {"query": q, "engine": eng, "mentioned": mentioned, "sources": ans.urls[:5], "excerpt": ans.text[:400]}

    return list(await asyncio.gather(*(one(q, e) for q in queries for e in engine_ids)))


def summarize(answers: list[dict[str, Any]], brand: str, competitors: list[dict[str, str]]) -> dict[str, Any]:
    """% de recomendação = respostas que citam a marca ÷ respostas válidas (pergunta × IA)."""
    ok = [a for a in answers if not a.get("error")]
    names = [brand] + [c["name"] for c in competitors]

    def share_of(rows: list[dict[str, Any]]) -> dict[str, float]:
        n = len(rows) or 1
        return {name: round(sum(1 for r in rows if name in r["mentioned"]) / n, 3) for name in names}

    engines_used = list(dict.fromkeys(a["engine"] for a in answers))
    by_engine = {e: share_of([a for a in ok if a["engine"] == e]) for e in engines_used}
    queries = list(dict.fromkeys(a["query"] for a in answers))
    rows = []
    for q in queries:
        mine = [a for a in ok if a["query"] == q]
        rows.append({"query": q, "mentioned": sorted({m for a in mine for m in a["mentioned"]}, key=names.index),
                     "by_engine": {a["engine"]: a["mentioned"] for a in mine}, "sources": [u for a in mine for u in a["sources"]][:5],
                     "excerpt": next((a["excerpt"] for a in mine if a["excerpt"]), "")})
    share = share_of(ok)
    gaps = [r["query"] for r in rows if brand not in r["mentioned"] and any(c["name"] in r["mentioned"] for c in competitors)]
    open_q = [r["query"] for r in rows if not r["mentioned"]]
    leader = max(names, key=lambda x: share[x]) if ok else None
    return {"share": share, "brand_rate": share.get(brand, 0.0), "leader": leader, "gaps": gaps, "open": open_q, "rows": rows,
            "by_engine": by_engine, "engines": engines_used, "answers": len(ok), "failed": len(answers) - len(ok)}


def default_engines(office: Office) -> list[str]:
    """Prospecção usa a IA mais barata disponível; o rastreador completo escolhe as IAs no painel."""
    from app.core import engines

    avail = engines.available(office)
    return [next(e for e in ("perplexity", "chatgpt", "claude", "simulado") if e in avail)]


# ------------------------------------------------------------------ plano (IA) e notas (código)
async def _plan(office: Office, d: Diagnosis, vis: dict[str, Any], tech: dict[str, Any]) -> dict[str, Any]:
    failed = [label for k, label, _ in TECH_CHECKS if tech.get("checked") and not tech["checks"].get(k)]
    return await office.llm.complete_json(
        kind="diagnosis.plan",
        system="Você é um consultor de visibilidade em IA (GEO) e de anúncios no ChatGPT para empresas brasileiras.",
        prompt=(
            f"Marca: {d.brand} ({d.site or 'sem site'}). Segmento: {d.category}. Região: {d.city or 'Brasil'}.\n"
            f"Taxa de citação da marca: {vis['brand_rate']:.0%}. Quem mais aparece: {vis['leader']}. Participação: {vis['share']}.\n"
            f"Perguntas em que concorrentes aparecem e a marca não (lacunas): {vis['gaps']}\n"
            f"Perguntas sem nenhuma marca citada (terreno livre): {vis['open']}\n"
            f"Itens técnicos reprovados: {failed or 'nenhum ou não verificado'}\n\n"
            "Retorne JSON: {summary (3 frases diretas para o dono da empresa), quick_wins [até 5 ações de GEO concretas, "
            "da mais fácil à mais difícil], content_ideas [até 4 conteúdos/dados que fariam as IAs citarem a marca], "
            "ad_drafts [até 3 {query, headline (até 40 caracteres), text (até 120), why}] para anúncios no ChatGPT nas lacunas. "
            "Regras: nada de promessa de resultado garantido, nada de dado inventado sobre a marca; anúncios são rascunhos.}"
        ),
        tier="worker", agent_id=AGENT, task_id=d.id, context={"brand": d.brand, "gaps": vis["gaps"], "open": vis["open"]},
    )


def overall(vis_rate: float, tech: int | None) -> int:
    vis = round(100 * vis_rate)
    return vis if tech is None else round(0.6 * vis + 0.4 * tech)


def grade(score: int) -> str:
    return "forte" if score >= 70 else "média" if score >= 40 else "fraca"


# ------------------------------------------------------------------ orquestração
async def create(office: Office, *, brand: str, site: str, category: str, city: str = "", competitors: Any = None, contact: str = "",
                 engines: list[str] | None = None, query_count: int | None = None) -> Diagnosis:
    from app.core import engines as eng

    avail = eng.available(office)
    chosen = [e for e in (engines or []) if e in avail] or default_engines(office)
    async with session_scope() as s:
        d = Diagnosis(
            token=secrets.token_urlsafe(24), brand=brand.strip()[:200], site=site.strip()[:500], category=category.strip()[:300],
            city=city.strip()[:120], competitors=parse_competitors(competitors), contact=contact.strip()[:300],
            engines=chosen, query_count=max(5, min(MAX_QUERIES, query_count or 10)),
        )
        s.add(d)
    return d


def start(office: Office, d: Diagnosis) -> None:
    task = asyncio.create_task(run(office, d.id))
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)


async def run(office: Office, diagnosis_id: str) -> Diagnosis:
    async with session_scope() as s:
        d = await s.get(Diagnosis, diagnosis_id)
        assert d is not None
    await office.emit("diagnosis", status="started", id=d.id, brand=d.brand)
    try:
        engine_ids = d.engines or default_engines(office)
        web = any(e != "simulado" for e in engine_ids)
        tech_task = asyncio.create_task(technical(d.site, allow_fetch=office.settings.allow_web_fetch))
        queries = await _queries(office, d)
        answers = await _answers(office, d, queries, engine_ids)
        if answers and all(a.get("error") for a in answers):
            raise RuntimeError("nenhuma IA respondeu: " + answers[0]["error"])
        vis = summarize(answers, d.brand, d.competitors)
        tech = await tech_task
        plan = await _plan(office, d, vis, tech)
        ts = tech_score(tech)
        score = overall(vis["brand_rate"], ts)
        async with session_scope() as s:
            m = await s.get(Diagnosis, d.id)
            assert m is not None
            cost = (await s.execute(select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(CostEntry.task_id == d.id))).scalar_one()
            m.mode, m.queries, m.visibility, m.technical, m.plan = ("web" if web else "parametric"), queries, vis, tech, plan
            m.scores = {"overall": score, "grade": grade(score), "visibility": round(100 * vis["brand_rate"]), "technical": ts}
            m.status, m.finished_at, m.cost_usd = "done", datetime.now(UTC), round(float(cost), 6)
            d = m
        await office.alert("info", AGENT, f"Diagnóstico de {d.brand} pronto: nota {score}/100 ({grade(score)}).")
        await office.emit("diagnosis", status="done", id=d.id, brand=d.brand, score=score)
    except Exception as e:  # noqa: BLE001
        budget = isinstance(e, BudgetExceeded)
        if not budget:
            log.exception("diagnóstico falhou")
        async with session_scope() as s:
            m = await s.get(Diagnosis, diagnosis_id)
            if m:
                m.status, m.finished_at = "failed", datetime.now(UTC)
                m.error = (f"sem orçamento/cota de IA no momento ({e})" if budget else str(e))[:2000]
                d = m
        await office.emit("diagnosis", status="failed", id=diagnosis_id)
    return d


def report_context(d: Diagnosis) -> dict[str, Any]:
    names = [d.brand] + [c["name"] for c in d.competitors]
    vis = d.visibility or {}
    share = vis.get("share") or {}
    return {
        "d": d,
        "ranking": sorted(((n, share.get(n, 0.0)) for n in names), key=lambda x: -x[1]),
        "rows": vis.get("rows") or [],
        "names": names,
        "tech_checks": [(label, (d.technical.get("checks") or {}).get(k)) for k, label, _ in TECH_CHECKS] if d.technical.get("checked") else [],
        "ai_access": d.technical.get("ai_access") or {},
        "engine_labels": __import__("app.core.engines", fromlist=["LABELS"]).LABELS,
    }
