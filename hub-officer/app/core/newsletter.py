"""Redação do boletim executivo da Insighta (newsletter editorial, sem venda).

    Clio (curadoria)     → lê os feeds oficiais configurados (ANS, Imprensa Nacional, operadoras…) e escolhe o que importa
    Calíope (redação)    → escreve manchete, gráfico (só com número de fonte) e notas de bancada — playbook em inglês
    Dédalo (diagramação) → monta o HTML em tabelas (abre no Outlook de desktop e no celular) e a versão web
    Envio                → só para assinantes que confirmaram (opt-in duplo), só depois do "aprovar" do fundador,
                           na janela da semana (terça 8h), em lotes com limite diário; bounces e reclamações saem da base

Base de leitores: só quem se inscreveu (formulário + confirmação). Lista comprada ou extraída (ex.: LinkedIn) é proibida
pelos termos do LinkedIn e dos provedores de envio (Brevo, SES, SendGrid) e não se sustenta na LGPD para marketing.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import cache
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import func, select

from app.core import mailer, sales
from app.db import session_scope
from app.models import AgentState, ContentPiece, Edition, EmailLog, Subscriber
from app.web.render import TEMPLATES

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)

CURATOR, WRITER, DESIGNER = "news.curator", "content.writer", "news.design"
PERSONAS = {
    CURATOR: ("Clio", "Curadoria", "Monitorar ANS, Diário Oficial e operadoras e escolher o que muda o caixa das clínicas."),
    DESIGNER: ("Dédalo", "Diagramação", "Montar o boletim em HTML que abre bem no Outlook e no celular."),
}
PLAYBOOK = Path(__file__).resolve().parent.parent / "playbooks" / "content" / "newsletter_editorial.md"
CONSENT_TEXT = ("Quero receber o {name} por e-mail, uma vez por semana. Posso cancelar a qualquer momento pelo link em cada edição. "
                "Meus dados (e-mail, nome, cargo e empresa) são usados só para este envio, conforme a LGPD.")
MAX_ITEMS = 12
UA = "BoletimRCM/0.1 (+curadoria editorial)"


@cache
def playbook() -> str:
    return PLAYBOOK.read_text(encoding="utf-8").strip()


def enabled(office: Office) -> bool:
    return office.settings.business == "insighta"


def base_url(office: Office) -> str:
    return sales.base_url(office)


async def register_personas() -> None:
    async with session_scope() as s:
        for aid, (name, role, mission) in PERSONAS.items():
            if await s.get(AgentState, aid) is None:
                s.add(AgentState(agent_id=aid, title=f"{name} — {role}", sector="redacao", role="specialist", skills=[], status="idle", current_activity=mission))


def week_key(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now(UTC)).astimezone(sales.SP).isocalendar()
    return f"{y}-W{w:02d}"


# ------------------------------------------------------------------ assinantes (opt-in duplo)
async def subscribe(office: Office, *, email: str, name: str = "", role: str = "", organization: str = "", source: str = "site", ip: str = "") -> Subscriber:
    """Cadastro pelo formulário: fica 'pendente' até clicar no link de confirmação (prova de consentimento guardada)."""
    email = email.strip().lower()
    st = office.settings
    async with session_scope() as s:
        sub = (await s.execute(select(Subscriber).where(Subscriber.email == email))).scalar_one_or_none()
        if sub is None:
            sub = Subscriber(email=email, token=secrets.token_urlsafe(24), name=name[:160], role=role[:120], organization=organization[:200], source=source[:24])
            s.add(sub)
        elif sub.status in ("ativo",):
            return sub
        sub.status = "pendente"
        sub.consent_text = CONSENT_TEXT.format(name=st.newsletter_name)
        sub.consent_ip = ip[:64]
    link = f"{base_url(office)}/boletim/confirmar/{sub.token}"
    await mailer.send(st, to=email, subject=f"Confirme sua inscrição no {st.newsletter_name}", kind="boletim_confirmacao", transactional=True,
                      from_addr=st.newsletter_from, body=(f"Olá{(' ' + name.split()[0]) if name else ''},\n\nPara começar a receber o {st.newsletter_name}, confirme seu e-mail:\n{link}\n\n"
                                                          "Se não foi você, ignore esta mensagem — sem a confirmação nada será enviado."))
    return sub


async def confirm(token: str) -> Subscriber | None:
    async with session_scope() as s:
        sub = (await s.execute(select(Subscriber).where(Subscriber.token == token))).scalar_one_or_none()
        if sub and sub.status == "pendente":
            sub.status, sub.confirmed_at = "ativo", datetime.now(UTC)
        return sub


async def unsubscribe(token: str) -> Subscriber | None:
    async with session_scope() as s:
        sub = (await s.execute(select(Subscriber).where(Subscriber.token == token))).scalar_one_or_none()
        if sub and sub.status != "descadastrado":
            sub.status = "descadastrado"
    if sub:
        await mailer.suppress(sub.email, "saiu do boletim")
    return sub


async def provider_event(events: list[dict[str, Any]]) -> int:
    """Higiene da base: eventos do provedor (formato Brevo/SES simplificado: {event, email})."""
    n = 0
    for ev in events:
        email, kind = str(ev.get("email") or "").lower(), str(ev.get("event") or "").lower()
        if not email:
            continue
        async with session_scope() as s:
            sub = (await s.execute(select(Subscriber).where(Subscriber.email == email))).scalar_one_or_none()
            if sub is None:
                continue
            if kind in ("hard_bounce", "hardbounce", "invalid_email", "blocked", "bounce"):
                sub.status = "bounce"
            elif kind in ("spam", "complaint"):
                sub.status = "reclamacao"
            elif kind in ("unsubscribed", "unsubscribe"):
                sub.status = "descadastrado"
            elif kind in ("soft_bounce", "softbounce", "deferred"):
                sub.soft_bounces += 1
                if sub.soft_bounces >= 3:
                    sub.status = "bounce"
            else:
                continue
            status = sub.status
        if status in ("bounce", "reclamacao", "descadastrado"):
            await mailer.suppress(email, f"boletim: {kind}")
        n += 1
    return n


# ------------------------------------------------------------------ Clio: curadoria
def parse_feed(xml_text: str, source: str) -> list[dict[str, Any]]:
    """RSS 2.0 e Atom. Devolve título, link, data e resumo (texto puro)."""
    try:
        root = ET.fromstring(xml_text[:2_000_000])
    except ET.ParseError:
        return []
    out = []
    strip = lambda t: re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()  # noqa: E731
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.split("}")[-1] == name), None)  # noqa: E731
        title = strip(getattr(get("title"), "text", ""))
        link_el = get("link")
        link = (link_el.get("href") if link_el is not None and link_el.get("href") else getattr(link_el, "text", "")) or ""
        date_raw = getattr(get("pubDate"), "text", None) or getattr(get("updated"), "text", None) or getattr(get("published"), "text", None)
        when = None
        if date_raw:
            try:
                when = parsedate_to_datetime(date_raw)
            except (TypeError, ValueError):
                try:
                    when = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
                except ValueError:
                    when = None
        summary = strip(getattr(get("description"), "text", None) or getattr(get("summary"), "text", None) or "")[:600]
        if title and link.startswith("http"):
            out.append({"title": title[:300], "link": link.strip()[:500], "source": source, "date": when.isoformat() if when else None, "summary": summary})
    return out


async def collect(office: Office, transport: httpx.AsyncBaseTransport | None = None, days: int = 10) -> list[dict[str, Any]]:
    st = office.settings
    urls = [u.strip() for u in st.newsletter_sources.split("|") if u.strip()]
    if not urls or not (st.allow_web_fetch or transport is not None):
        return []
    async with session_scope() as s:
        used = {i.get("link") for e in (await s.execute(select(Edition))).scalars() for i in e.items or []}
    since = datetime.now(UTC) - timedelta(days=days)
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": UA}, transport=transport) as c:
        for u in urls:
            try:
                r = await c.get(u)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.info("fonte do boletim indisponível %s: %s", u, e)
                continue
            for it in parse_feed(r.text, sales.site_domain(u)):
                d = datetime.fromisoformat(it["date"]) if it["date"] else None
                if it["link"] in used or (d and d.astimezone(UTC) < since):
                    continue
                items.append(it)
    return items[:60]


async def curate(office: Office, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    await sales._status(office, CURATOR, "working", f"lendo {len(items)} notícia(s)")
    listing = [{"i": n, "title": it["title"], "source": it["source"], "summary": it["summary"][:300]} for n, it in enumerate(items)]
    out = await office.llm.complete_json(
        kind="newsletter.curate", system=f"You are Clio, the curator of an executive healthcare revenue-cycle bulletin.\n\n{playbook()}",
        prompt=(f"Candidate items: {json.dumps(listing, ensure_ascii=False)}\nPick up to {MAX_ITEMS} items relevant for clinic and hospital revenue cycle, ranked by impact. "
                'Return JSON: {"picked": [{"i": 0, "why": "one line in Portuguese"}]}'),
        tier="worker", agent_id=CURATOR, context={"items": listing},
    )
    picked = []
    for p in out.get("picked") or []:
        if isinstance(p, dict) and isinstance(p.get("i"), int) and 0 <= p["i"] < len(items) and items[p["i"]] not in picked:
            picked.append({**items[p["i"]], "why": str(p.get("why") or "")[:200]})
    await sales._status(office, CURATOR, "idle", f"{len(picked)} pauta(s) escolhida(s)")
    return picked[:MAX_ITEMS]


# ------------------------------------------------------------------ Calíope: redação
def validate(content: dict[str, Any], items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Corta o que não tem fonte da curadoria; o gráfico só fica com fonte e números válidos."""
    links = {i["link"] for i in items}
    notes: list[str] = []
    head = content.get("headline") or {}
    if head and head.get("source_url") not in links and not head.get("guide"):
        notes.append("manchete sem fonte da curadoria — removida")
        head = {}
    chart = content.get("chart") or None
    if chart:
        rows = [r for r in chart.get("rows") or [] if isinstance(r, dict) and isinstance(r.get("value"), (int, float)) and r.get("label")]
        if chart.get("source_url") not in links or len(rows) < 2:
            notes.append("gráfico sem fonte verificável — removido")
            chart = None
        else:
            chart = {**chart, "rows": rows[:10]}
            notes.append("conferir os números do gráfico na fonte antes de aprovar")
    kept = []
    for n in content.get("notes") or []:
        if not isinstance(n, dict) or not n.get("title") or not n.get("body"):
            continue
        if n.get("source_url") and n["source_url"] not in links:
            n = {**n, "source_url": None}
            notes.append(f"nota “{n['title'][:40]}”: link fora da curadoria — removido")
        kept.append(n)
    for blob in [head.get("body", "")] + [n["body"] for n in kept]:
        for m in re.finditer(r"\d+(?:[.,]\d+)?\s*%|R\$\s*\d[\d.,]*|n[ºo°]\s*\d+", blob or ""):
            notes.append(f"conferir na fonte: “{m.group(0)}”")
    return {"headline": head, "chart": chart, "notes": kept[:4]}, notes[:20]


async def _guide_fallback() -> dict[str, Any] | None:
    """Semana sem notícia relevante: a manchete vira o guia aprovado mais recente do blog (conteúdo próprio, revisado)."""
    async with session_scope() as s:
        p = (await s.execute(select(ContentPiece).where(ContentPiece.status.in_(("aprovado", "publicado"))).order_by(ContentPiece.updated_at.desc()).limit(1))).scalar_one_or_none()
    if p is None:
        return None
    first = re.split(r"\n\s*\n", p.body_md.strip())[0][:900]
    return {"title": p.title, "dek": p.meta_description, "body": first, "source_url": None, "guide": p.slug}


async def write(office: Office, items: list[dict[str, Any]]) -> tuple[dict[str, Any], str, str, list[str]]:
    st = office.settings
    await sales._status(office, WRITER, "working", f"escrevendo o {st.newsletter_name}")
    brief = [{"title": i["title"], "link": i["link"], "source": i["source"], "date": i["date"], "summary": i["summary"], "why": i.get("why", "")} for i in items]
    out = await office.llm.complete_json(
        kind="newsletter.write", system=f"You are Calíope, the editor of {st.newsletter_name}.\n\n{playbook()}",
        prompt=(f"Curated items (the ONLY allowed sources): {json.dumps(brief, ensure_ascii=False)}\n"
                "Write this week's edition in Brazilian Portuguese. Return JSON: {\"subject\": \"\", \"preheader\": \"\", "
                "\"headline\": {\"title\": \"\", \"dek\": \"\", \"body\": \"paragraphs separated by blank lines\", \"source_url\": \"one of the links\"} or null, "
                "\"chart\": {\"title\": \"\", \"unit\": \"\", \"source\": \"\", \"source_url\": \"\", \"rows\": [{\"label\": \"\", \"value\": 0}]} or null, "
                "\"notes\": [{\"title\": \"\", \"body\": \"\", \"source_url\": \"one of the links or null\"}]}"),
        tier="worker", agent_id=WRITER, context={"items": brief, "name": st.newsletter_name},
    )
    content, notes = validate(out, items)
    if not content["headline"]:
        guide = await _guide_fallback()
        if guide:
            content["headline"] = guide
            notes.append("manchete = guia aprovado do blog (semana sem notícia com fonte)")
    subject = str(out.get("subject") or "").strip()[:120] or (content["headline"].get("title", "")[:120] if content["headline"] else "")
    preheader = str(out.get("preheader") or "").strip()[:150] or (content["headline"].get("dek", "")[:150] if content["headline"] else "")
    await sales._status(office, WRITER, "idle", "edição escrita")
    return content, subject, preheader, notes


# ------------------------------------------------------------------ Dédalo: diagramação
def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def render_context(office: Office, e: Edition, *, sub: Subscriber | None = None, web: bool = False) -> dict[str, Any]:
    st = office.settings
    from app.core.insighta import landing_url, utm

    c = e.content or {}
    head = dict(c.get("headline") or {})
    if head.get("guide"):
        head["source_url"] = utm(f"{landing_url(office)}/{head['guide']}", campaign=f"boletim-{e.number}", medium="email", source="boletim")
    chart = c.get("chart")
    if chart:
        top = max(r["value"] for r in chart["rows"]) or 1
        chart = {**chart, "rows": [{**r, "pct": max(2, round(100 * r["value"] / top))} for r in chart["rows"]]}
    return {
        "name": st.newsletter_name, "tagline": st.newsletter_tagline, "number": e.number, "date": (e.sent_at or e.approved_at or e.created_at or datetime.now(UTC)).astimezone(sales.SP),
        "subject": e.subject, "preheader": e.preheader, "head": head, "head_paragraphs": _paragraphs(head.get("body", "")), "chart": chart,
        "notes": [{**n, "paragraphs": _paragraphs(n["body"])} for n in c.get("notes") or []],
        "web_url": f"{base_url(office)}/boletim/{e.slug}", "subscribe_url": f"{base_url(office)}/boletim",
        "unsubscribe_url": f"{base_url(office)}/boletim/sair/{sub.token}" if sub else f"{base_url(office)}/boletim/sair/{{token}}",
        "site_url": utm(f"{landing_url(office)}/", campaign=f"boletim-{e.number}", medium="email", source="boletim"),
        "cnpj": st.company_cnpj, "web": web, "email": sub.email if sub else "",
    }


def render_html(office: Office, e: Edition, sub: Subscriber | None = None) -> str:
    return TEMPLATES.get_template("newsletter_email.html").render(**render_context(office, e, sub=sub))


def render_text(office: Office, e: Edition, sub: Subscriber | None = None) -> str:
    ctx = render_context(office, e, sub=sub)
    lines = [f"{ctx['name']} · Edição {ctx['number']} · {ctx['date']:%d/%m/%Y}", ""]
    if ctx["head"]:
        lines += [ctx["head"].get("title", "").upper(), ctx["head"].get("dek", ""), ""] + ctx["head_paragraphs"] + ([f"Fonte: {ctx['head']['source_url']}"] if ctx["head"].get("source_url") else []) + [""]
    if ctx["chart"]:
        lines += [ctx["chart"]["title"]] + [f"- {r['label']}: {r['value']} {ctx['chart'].get('unit', '')}" for r in ctx["chart"]["rows"]] + [f"Fonte: {ctx['chart'].get('source')} {ctx['chart'].get('source_url')}", ""]
    for n in ctx["notes"]:
        lines += [f"• {n['title']}"] + n["paragraphs"] + ([f"Fonte: {n['source_url']}"] if n.get("source_url") else []) + [""]
    lines += [f"Versão no navegador: {ctx['web_url']}", "Produzido pela equipe de inteligência de dados da Insighta.",
              f"Você recebe porque se inscreveu em {ctx['subscribe_url']}. Sair: {ctx['unsubscribe_url']}"]
    return "\n".join(lines)


# ------------------------------------------------------------------ edição da semana
async def build(office: Office, transport: httpx.AsyncBaseTransport | None = None) -> Edition | None:
    week = week_key()
    async with session_scope() as s:
        if (await s.execute(select(Edition.id).where(Edition.week == week, Edition.status != "rejeitado"))).first():
            return None
        number = int((await s.execute(select(func.coalesce(func.max(Edition.number), 0)))).scalar_one()) + 1
    items = await curate(office, await collect(office, transport))
    content, subject, preheader, notes = await write(office, items)
    if not content["headline"] and not content["notes"]:
        await office.alert("warning", CURATOR, "Boletim da semana não saiu: nenhuma notícia com fonte nas fontes configuradas e nenhum guia aprovado no blog.")
        return None
    await sales._status(office, DESIGNER, "working", "diagramando")
    async with session_scope() as s:
        e = Edition(number=number, slug=f"edicao-{number}", week=week, subject=subject or f"{office.settings.newsletter_name} · edição {number}",
                    preheader=preheader, items=items, content=content, review_notes="\n".join(notes))
        s.add(e)
    await sales._status(office, DESIGNER, "idle", f"edição {number} pronta para aprovação")
    await office.alert("info", DESIGNER, f"Edição {number} do {office.settings.newsletter_name} pronta para aprovar" + (f" ({len(notes)} ponto(s) para conferir)" if notes else "") + ".")
    return e


async def decide(edition_id: str, approve: bool, note: str = "") -> Edition | None:
    async with session_scope() as s:
        e = await s.get(Edition, edition_id)
        if e is None or e.status not in ("rascunho", "aprovado"):
            return e
        e.status = "aprovado" if approve else "rejeitado"
        e.approved_at = datetime.now(UTC) if approve else None
        if note:
            e.review_notes = (e.review_notes + f"\nfundador: {note}").strip()
        return e


def in_send_window(office: Office, now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(sales.SP)
    st = office.settings
    return local.weekday() == st.newsletter_send_weekday and st.newsletter_send_hour <= local.hour < 18 or (
        local.weekday() == (st.newsletter_send_weekday + 1) % 7 and 8 <= local.hour < 18)  # dia seguinte termina os lotes


async def _sent_today() -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as s:
        return int((await s.execute(select(func.count(EmailLog.id)).where(EmailLog.kind.like("boletim:%"), EmailLog.created_at >= start))).scalar_one())


async def send(office: Office, *, force: bool = False) -> dict[str, int]:
    """Envia a edição aprovada aos assinantes ativos, em lotes, sem repetir quem já recebeu."""
    st = office.settings
    async with session_scope() as s:
        e = (await s.execute(select(Edition).where(Edition.status.in_(("aprovado", "enviando"))).order_by(Edition.number).limit(1))).scalar_one_or_none()
    if e is None or not (force or in_send_window(office)):
        return {"enviados": 0}
    kind = f"boletim:{e.number}"
    async with session_scope() as s:
        done = set((await s.execute(select(EmailLog.to_addr).where(EmailLog.kind == kind, EmailLog.status.in_(("sent", "simulated"))))).scalars())
        subs = [x for x in (await s.execute(select(Subscriber).where(Subscriber.status == "ativo").order_by(Subscriber.confirmed_at))).scalars() if x.email not in done]
    budget = max(0, st.newsletter_daily_send_cap - await _sent_today())
    sent = 0
    await sales._status(office, DESIGNER, "working", f"enviando edição {e.number}")
    for sub in subs[:budget]:
        row = await mailer.send(st, to=sub.email, subject=e.subject, body=render_text(office, e, sub), html=render_html(office, e, sub), kind=kind,
                                from_addr=st.newsletter_from, unsubscribe_url=f"{base_url(office)}/boletim/sair/{sub.token}", log_body="")
        sent += row.status in ("sent", "simulated")
    remaining = len(subs) - sent
    async with session_scope() as s:
        row = await s.get(Edition, e.id)
        row.sent_count = (row.sent_count or 0) + sent
        row.status = "enviando" if remaining > 0 else "enviado"
        if remaining <= 0:
            row.sent_at = datetime.now(UTC)
    await sales._status(office, DESIGNER, "idle", f"edição {e.number}: {sent} enviada(s), {max(remaining, 0)} na fila")
    return {"enviados": sent, "fila": max(remaining, 0)}


async def send_test(office: Office, edition_id: str, to: str) -> str:
    async with session_scope() as s:
        e = await s.get(Edition, edition_id)
    if e is None:
        return "edição não encontrada"
    row = await mailer.send(office.settings, to=to, subject=f"[TESTE] {e.subject}", body=render_text(office, e), html=render_html(office, e),
                            kind="boletim_teste", transactional=True, from_addr=office.settings.newsletter_from, log_body="")
    return row.status


async def tick(office: Office, *, force: bool = False) -> dict[str, Any]:
    gov = await office.gov.snapshot()
    if not (force or (enabled(office) and gov["newsletter_enabled"])):
        return {"skipped": "boletim desligado"}
    e = await build(office)
    out = await send(office)
    return {"nova_edicao": e.number if e else None, **out}


async def summary(office: Office) -> dict[str, Any]:
    async with session_scope() as s:
        subs = dict((await s.execute(select(Subscriber.status, func.count()).group_by(Subscriber.status))).all())
        eds = list((await s.execute(select(Edition).order_by(Edition.number.desc()).limit(20))).scalars())
    st = office.settings
    gov = await office.gov.snapshot()
    return {
        "enabled": gov["newsletter_enabled"], "name": st.newsletter_name, "subscribers": subs, "sources": len([u for u in st.newsletter_sources.split("|") if u.strip()]),
        "signup_url": f"{base_url(office)}/boletim", "webhook": bool(st.newsletter_webhook_secret), "cap": st.newsletter_daily_send_cap,
        "window": f"{['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'][st.newsletter_send_weekday]} {st.newsletter_send_hour}h",
        "editions": [{"id": e.id, "number": e.number, "subject": e.subject, "status": e.status, "sent": e.sent_count, "items": len(e.items or []),
                      "flags": [x for x in e.review_notes.splitlines() if x], "web": f"/boletim/{e.slug}", "created_at": e.created_at} for e in eds],
    }
