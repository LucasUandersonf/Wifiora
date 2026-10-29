"""Comercial automático da agência — o funil inteiro sem operação humana.

    Diana (prospecção)  → acha empresas do perfil-alvo com site e e-mail comercial público
    Mercator            → faz o Diagnóstico de Visibilidade em IA de cada uma
    Mercúrio (vendas)   → envia o diagnóstico, faz até 2 follow-ups, lê e responde e-mails, manda a proposta
    Pagamento (Stripe)  → o webhook confirma e ativa o cliente
    Héstia (sucesso)    → entrega o kit de GEO, a página do cliente e o relatório mensal

Travas (código, não IA): só e-mails corporativos do próprio domínio da empresa, publicados no site; limite diário;
janela de envio em horário comercial; no máximo 3 contatos por empresa; descadastro em todo e-mail e lista de
supressão permanente; nenhuma promessa de resultado; preços e links vêm da configuração, nunca do LLM.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from app.core import diagnosis as dg
from app.core import mailer
from app.db import session_scope
from app.llm.base import BudgetExceeded
from app.models import AgentState, Client, Diagnosis, EmailLog, Prospect, RevenueEntry

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)

PROSPECTOR, CLOSER, SUCCESS = "sales.prospector", "sales.closer", "sales.success"
PERSONAS = {
    PROSPECTOR: ("Diana", "Prospecção", "Encontrar empresas do perfil-alvo com site e contato comercial público."),
    CLOSER: ("Mercúrio", "Vendas", "Enviar diagnósticos, responder e-mails e levar à proposta."),
    SUCCESS: ("Héstia", "Sucesso do cliente", "Entregar o kit de GEO e os relatórios mensais."),
}
BLOCKED_DOMAINS = (
    "mercadolivre", "mercadolibre", "amazon", "shopee", "magazineluiza", "magalu", "americanas", "aliexpress", "facebook",
    "instagram", "linkedin", "youtube", "tiktok", "reclameaqui", "wikipedia", "google", "gov.br", "globo", "uol.com",
    "estadao", "folha", "exame", "reddit", "twitter", "x.com", "pinterest", "tripadvisor", "booking", "decolar", "zoom.com",
    "buscape", "zoom.com.br", "olx", "enjoei", "netshoes", "dafiti", "infomoney", "terra.com", "g1.", "medium.com", "blogspot",
)
CONTACT_PATHS = ("/", "/contato", "/fale-conosco", "/contact", "/atendimento", "/sobre")
UA = "GeoOfficeComercial/0.1 (+contato comercial)"
FOLLOWUP_DAYS = (4, 10)  # dias após o primeiro contato
MAX_TOUCHES = 3
BANNED = re.compile(r"garant|100\s*%|primeiro lugar|resultado (certo|garantido)|sem risco", re.I)
SP = ZoneInfo("America/Sao_Paulo")


# ------------------------------------------------------------------ utilidades
def base_url(office: Office) -> str:
    return office.settings.public_base_url.rstrip("/")


def in_send_window(now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(SP)
    return local.weekday() < 5 and 9 <= local.hour < 18


def site_domain(url: str) -> str:
    return dg.host(url if "://" in url else f"https://{url}")


def blocked(domain: str) -> bool:
    return not domain or any(b in domain for b in BLOCKED_DOMAINS)


def corporate_emails(text: str, domain: str) -> list[str]:
    """Só e-mails do próprio domínio da empresa (ou subdomínio) — nunca pessoais de provedores."""
    found = {e.lower().rstrip(".") for e in mailer.EMAIL_RE.findall(text or "")}
    good = [e for e in found if mailer.domain_of(e) == domain or mailer.domain_of(e).endswith("." + domain)]
    pref = ("contato", "comercial", "vendas", "atendimento", "sac", "marketing", "ola", "oi", "hello", "contact")
    return sorted(good, key=lambda e: (0 if e.split("@")[0] in pref else 1, len(e)))


async def _status(office: Office, agent_id: str, status: str, activity: str = "") -> None:
    async with session_scope() as s:
        row = await s.get(AgentState, agent_id)
        if row:
            row.status, row.current_activity = status, activity[:500]
            if status == "idle":
                row.processed = (row.processed or 0) + 1
    await office.emit("agent_status", agent_id=agent_id, status=status, activity=activity[:200], task_id=None)


async def _say(office: Office, sender: str, recipient: str, summary: str) -> None:
    await office.emit("message", id=None, type="sales.update", sender=sender, recipient=recipient, summary=summary[:300])


async def register_personas() -> None:
    async with session_scope() as s:
        for aid, (name, role, mission) in PERSONAS.items():
            row = await s.get(AgentState, aid)
            if row is None:
                s.add(AgentState(agent_id=aid, title=f"{name} — {role}", sector="comercial", role="specialist", skills=[], status="idle", current_activity=mission))
            else:
                row.title, row.sector = f"{name} — {role}", "comercial"


async def emails_sent_today() -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as s:
        q = select(func.count(EmailLog.id)).where(EmailLog.direction == "out", EmailLog.kind.in_(("primeiro", "followup")), EmailLog.status.in_(("sent", "simulated")), EmailLog.created_at >= start)
        return int((await s.execute(q)).scalar_one())


def health(office: Office) -> dict[str, Any]:
    st = office.settings
    return {
        "smtp": mailer.smtp_ready(st),
        "imap": mailer.imap_ready(st),
        "payment_links": bool(st.payment_link_diagnostico and st.payment_link_mensal),
        "stripe_webhook": bool(st.stripe_webhook_secret),
        "web_search": office.llm.can_search and office.llm.client.provider == "anthropic",
        "web_fetch": st.allow_web_fetch,
        "company_cnpj": bool(st.company_cnpj),
        "public_url": dg.host(st.public_base_url) not in ("localhost", "127.0.0.1"),
    }


def footer(office: Office, p: Prospect) -> str:
    st = office.settings
    who = ("Insighta" if st.business == "insighta" else st.agency_name) + (f" · CNPJ {st.company_cnpj}" if st.company_cnpj else "") + f" · {base_url(office)}"
    why = (f"Você pediu {'este contato' if st.business == 'insighta' else 'este diagnóstico'} em {base_url(office)}." if p.consent else
           f"Você recebeu este e-mail porque {p.email} está publicado no site {p.domain} como contato da empresa.")
    return f"\n\n--\n{who}\n{why}\nNão quer mais receber? {base_url(office)}/descadastrar/{p.token}"


# ------------------------------------------------------------------ Diana: prospecção
async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    from app.skills.builtin.web import _allowed_by_robots

    try:
        if not await _allowed_by_robots(client, url):
            return ""
        r = await client.get(url, timeout=15)
        return r.text[:1_000_000] if r.status_code < 400 else ""
    except httpx.HTTPError:
        return ""


async def enrich(site: str) -> dict[str, Any]:
    """Abre a página inicial e as de contato; devolve nome (título) e e-mails corporativos."""
    domain = site_domain(site)
    origin = f"https://{domain}"
    emails: list[str] = []
    title = ""
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as c:
        for path in CONTACT_PATHS:
            html = await _fetch(c, urljoin(origin, path))
            if not html:
                continue
            if not title:
                m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
                title = re.split(r"\s[|\-–—:]\s", m.group(1).strip())[0][:120] if m else ""
            emails += [e for e in corporate_emails(html, domain) if e not in emails]
            if emails:
                break
    return {"domain": domain, "company": title or domain.split(".")[0].capitalize(), "emails": emails}


async def discover(office: Office) -> int:
    """Encontra novas empresas. Precisa de busca na web (Claude); sem ela, só entram pedidos pelo site (inbound)."""
    st = office.settings
    if office.llm.client.provider == "mock":
        return await _discover_demo(office)
    if not health(office)["web_search"] or not st.allow_web_fetch:
        return 0
    seg, city = random.choice(st.sales_segment_list or ["loja online"]), random.choice(st.sales_city_list or ["Brasil"])
    await _status(office, PROSPECTOR, "working", f"procurando: {seg} em {city}")
    res = await office.llm.search(prompt=f"Quais são as principais empresas de {seg} em {city}, Brasil? Liste com o site oficial de cada uma.", agent_id=PROSPECTOR)
    domains: list[str] = []
    for u in res.urls + res.seen_urls:
        d = site_domain(u)
        if not blocked(d) and d not in domains:
            domains.append(d)
    added = 0
    for d in domains:
        if added >= st.sales_new_prospects_per_run:
            break
        async with session_scope() as s:
            if (await s.execute(select(Prospect.id).where(Prospect.domain == d))).first():
                continue
        if await mailer.suppressed(f"x@{d}"):
            continue
        info = await enrich(d)
        async with session_scope() as s:
            s.add(Prospect(
                token=secrets.token_urlsafe(24), company=info["company"], site=f"https://{d}", domain=d,
                email=info["emails"][0] if info["emails"] else "", segment=seg, city=city, source="busca",
                status="novo" if info["emails"] else "sem_contato",
            ))
        added += 1
    await _status(office, PROSPECTOR, "idle", f"{added} empresa(s) nova(s) em {seg}")
    if added:
        await _say(office, PROSPECTOR, "research.market", f"{added} empresa(s) de {seg} ({city}) para diagnosticar")
    return added


async def _discover_demo(office: Office) -> int:
    async with session_scope() as s:
        if (await s.execute(select(func.count(Prospect.id)).where(Prospect.source == "demo"))).scalar_one() >= 3:
            return 0
        for i, (name, seg) in enumerate([("Suplementos Demo", "loja online de suplementos"), ("Moda Demo", "loja online de moda"), ("Turismo Demo", "agência de turismo")]):
            d = f"{name.split()[0].lower()}-demo{i}.invalid"
            s.add(Prospect(token=secrets.token_urlsafe(24), company=name, site=f"https://{d}", domain=d, email=f"contato@{d}", segment=seg, city="São Paulo", source="demo"))
    await _say(office, PROSPECTOR, "research.market", "3 empresas de demonstração para diagnosticar")
    return 3


# ------------------------------------------------------------------ Mercator: diagnóstico
async def diagnose(office: Office, limit: int = 3) -> int:
    async with session_scope() as s:
        todo = list((await s.execute(select(Prospect).where(Prospect.status == "novo").order_by(Prospect.consent.desc(), Prospect.created_at).limit(limit))).scalars())
    for p in todo:
        await _status(office, "research.market", "working", f"diagnóstico: {p.company}")
        d = await dg.create(office, brand=p.company, site=p.site, category=p.segment, city=p.city)
        d = await dg.run(office, d.id)
        async with session_scope() as s:
            row = await s.get(Prospect, p.id)
            if row:
                row.diagnosis_id = d.id
                row.status = "diagnosticado" if d.status == "done" else "novo"
        await _status(office, "research.market", "idle", f"diagnóstico de {p.company}: {d.scores.get('overall', '—')}/100")
        if d.status == "done":
            await _say(office, "research.market", CLOSER, f"{p.company}: nota {d.scores['overall']}/100, {len(d.visibility.get('gaps') or [])} lacuna(s)")
    return len(todo)


# ------------------------------------------------------------------ Mercúrio: contato e respostas
async def _compose(office: Office, p: Prospect, d: Diagnosis, touch: int) -> tuple[str, str]:
    st = office.settings
    report = f"{base_url(office)}/relatorio/{d.token}"
    vis = d.visibility or {}
    facts = {
        "empresa": p.company, "segmento": p.segment, "nota": d.scores.get("overall"), "citada_pct": d.scores.get("visibility"),
        "quem_mais_aparece": vis.get("leader"), "lacunas": len(vis.get("gaps") or []), "perguntas": len(d.queries or []),
        "pediu_pelo_site": p.consent, "contato_numero": touch,
    }
    out = await office.llm.complete_json(
        kind="sales.email",
        system=f"Você é Mercúrio, consultor da {st.agency_name}. Escreve e-mails B2B curtos, humanos e honestos em português do Brasil.",
        prompt=(
            f"FATOS (use só estes): {json.dumps(facts, ensure_ascii=False)}\n"
            f"Escreva o e-mail {'de entrega do diagnóstico que a empresa pediu' if p.consent else ('de primeiro contato' if touch == 1 else f'de acompanhamento nº {touch - 1} (curto, sem insistir)')}. "
            "Mostre 1 número do diagnóstico, diga que o relatório completo é gratuito e convide a responder este e-mail. "
            "Proibido: prometer resultado, inventar números, falar mal de concorrente, pressão. Até 120 palavras. "
            'Retorne JSON: {"subject": "...", "body": "..."} (o link do relatório e o rodapé são adicionados depois).'
        ),
        tier="worker", agent_id=CLOSER, context={"prospect": p.company, "facts": facts, "touch": touch},
    )
    subject, body = str(out.get("subject") or "").strip()[:120], str(out.get("body") or "").strip()
    if not subject or not body or BANNED.search(subject + body):
        subject = f"{p.company}: como as IAs falam da sua empresa"
        body = (f"Olá, equipe da {p.company}.\n\nFizemos {facts['perguntas']} perguntas de compra sobre {p.segment} a uma IA. "
                f"A {p.company} apareceu em {facts['citada_pct']}% delas. O relatório completo, gratuito, mostra onde os concorrentes aparecem "
                "e o que fazer para ser citado.\n\nSe quiser conversar, é só responder este e-mail.")
    return subject, f"{body}\n\nRelatório completo: {report}{footer(office, p)}"


async def outreach(office: Office) -> dict[str, int]:
    from app.core import insighta

    saas = insighta.enabled(office)  # Insighta: sem diagnóstico; o e-mail leva à calculadora e ao teste grátis
    gov = await office.gov.snapshot()
    sent = {"primeiro": 0, "followup": 0, "perdido": 0}
    cap = int(gov["sales_daily_email_cap"])
    now = datetime.now(UTC)
    async with session_scope() as s:
        ready = list((await s.execute(select(Prospect).where(Prospect.status.in_(("novo" if saas else "diagnosticado", "contatado"))).order_by(Prospect.consent.desc(), Prospect.updated_at))).scalars())
    for p in ready:
        if not p.email or (not saas and not p.diagnosis_id):
            continue
        last = p.last_contact_at.replace(tzinfo=UTC) if p.last_contact_at and not p.last_contact_at.tzinfo else p.last_contact_at
        if p.status == "contatado":
            if p.touches >= MAX_TOUCHES:
                if last and now - last >= timedelta(days=7):
                    await _set(p.id, status="perdido", notes=p.notes + "\nsem resposta após 3 contatos")
                    sent["perdido"] += 1
                continue
            due = FOLLOWUP_DAYS[p.touches - 1] - (FOLLOWUP_DAYS[p.touches - 2] if p.touches >= 2 else 0)
            if not last or now - last < timedelta(days=due) or p.consent:
                continue
        # pedidos feitos pelo site (consentimento) saem na hora; prospecção só em horário comercial e dentro do limite
        if not p.consent:
            if not gov["sales_auto_send"] or not in_send_window(now) or await emails_sent_today() >= cap:
                continue
        touch = p.touches + 1
        if saas:
            await _status(office, CLOSER, "working", f"escrevendo para {p.company}")
            subject, body = await insighta.compose(office, p, touch)
        else:
            async with session_scope() as s:
                d = await s.get(Diagnosis, p.diagnosis_id)
            if d is None or d.status != "done":
                continue
            await _status(office, CLOSER, "working", f"escrevendo para {p.company}")
            subject, body = await _compose(office, p, d, touch)
        row = await mailer.send(office.settings, to=p.email, subject=subject, body=body, kind="primeiro" if touch == 1 else "followup",
                                prospect_id=p.id, unsubscribe_url=f"{base_url(office)}/descadastrar/{p.token}", transactional=p.consent and touch == 1)
        await _status(office, CLOSER, "idle", f"e-mail {touch} para {p.company}: {row.status}")
        if row.status in ("sent", "simulated"):
            await _set(p.id, status="contatado", touches=touch, last_contact_at=now)
            sent["primeiro" if touch == 1 else "followup"] += 1
            await _say(office, CLOSER, "founder", f"{'Diagnóstico enviado' if touch == 1 else 'Acompanhamento'} para {p.company}")
        elif row.error == "destinatário descadastrado":
            await _set(p.id, status="descadastrado")
    return sent


async def _set(prospect_id: str, **fields: Any) -> None:
    async with session_scope() as s:
        p = await s.get(Prospect, prospect_id)
        if p:
            for k, v in fields.items():
                setattr(p, k, v)


UNSUB = re.compile(r"descadastr|remov(a|er) (meu|o) e-?mail|n[aã]o (me )?(envie|mande)|pare de|unsubscribe|sair da lista", re.I)
AUTO = re.compile(r"resposta autom[aá]tica|aus[eê]ncia|fora do escrit[oó]rio|out of office|auto.?reply|f[eé]rias", re.I)


async def classify(office: Office, text: str) -> str:
    if UNSUB.search(text):
        return "descadastrar"
    if AUTO.search(text):
        return "automatica"
    out = await office.llm.complete_json(
        kind="sales.classify", system="Você classifica respostas a e-mails comerciais.",
        prompt=f"Resposta recebida:\n{text[:2000]}\n\nClassifique em: interessado | duvida | nao | descadastrar | automatica. Retorne JSON: {{\"intent\": \"...\"}}",
        tier="judge", agent_id=CLOSER, context={"text": text},
    )
    intent = str(out.get("intent") or "duvida").lower()
    return intent if intent in ("interessado", "duvida", "nao", "descadastrar", "automatica") else "duvida"


async def handle_reply(office: Office, sender: str, subject: str, body: str) -> str | None:
    async with session_scope() as s:
        p = (await s.execute(select(Prospect).where(Prospect.email == sender))).scalars().first()
        if p is None:
            dom = mailer.domain_of(sender)
            p = (await s.execute(select(Prospect).where(Prospect.domain == dom))).scalars().first() if dom else None
    if p is None:
        return None
    intent = await classify(office, body)
    async with session_scope() as s:
        s.add(EmailLog(prospect_id=p.id, direction="in", kind="entrada", from_addr=sender, to_addr=office.settings.smtp_from or "", subject=subject[:300], body=body, status="received", intent=intent))
    if intent == "descadastrar":
        await mailer.suppress(p.email or sender, "pediu descadastro")
        await _set(p.id, status="descadastrado")
    elif intent == "nao":
        await mailer.suppress(p.email or sender, "não tem interesse")
        await _set(p.id, status="perdido")
    elif intent in ("interessado", "duvida"):
        from app.core import insighta

        if insighta.enabled(office):
            await insighta.answer(office, p, body)
            return intent
        await _answer(office, p, body)
        await office.alert("info", CLOSER, f"{p.company} respondeu ({intent}). Proposta enviada automaticamente.")
    return intent


def proposal_url(office: Office, p: Prospect) -> str:
    return f"{base_url(office)}/proposta/{p.token}"


async def _answer(office: Office, p: Prospect, question: str) -> None:
    st = office.settings
    offer = {
        "diagnostico_completo_brl": st.price_diagnostico_brl, "acompanhamento_mensal_brl": st.price_mensal_brl,
        "inclui_mensal": ["diagnóstico mensal", "kit de GEO para o site", "rascunhos de anúncios no ChatGPT", "relatório mensal"],
        "nao_inclui": ["verba de anúncio", "promessa de posição"], "proposta": proposal_url(office, p),
    }
    await _status(office, CLOSER, "working", f"respondendo {p.company}")
    out = await office.llm.complete_json(
        kind="sales.answer", system=f"Você é Mercúrio, consultor da {st.agency_name}. Responde clientes com clareza e honestidade.",
        prompt=(f"Mensagem do cliente:\n{question[:2000]}\n\nOFERTA (use só isto, sem inventar preço, prazo ou resultado): {json.dumps(offer, ensure_ascii=False)}\n"
                "Responda a dúvida em até 120 palavras e convide a ver a proposta. Retorne JSON: {\"body\": \"...\"}"),
        tier="worker", agent_id=CLOSER, context={"prospect": p.company, "offer": offer},
    )
    body = str(out.get("body") or "").strip()
    if not body or BANNED.search(body):
        body = f"Obrigado pelo retorno! Montamos uma proposta com as opções para a {p.company}."
    body += f"\n\nProposta e pagamento: {proposal_url(office, p)}{footer(office, p)}"
    await mailer.send(st, to=p.email, subject=f"Re: proposta para {p.company}", body=body, kind="resposta", prospect_id=p.id, transactional=True)
    await _set(p.id, status="proposta", last_contact_at=datetime.now(UTC))
    await _status(office, CLOSER, "idle", f"proposta enviada a {p.company}")
    await _say(office, CLOSER, "founder", f"{p.company} está interessada: proposta enviada")


async def replies(office: Office) -> int:
    msgs = await mailer.fetch_replies(office.settings)
    n = 0
    for m in msgs:
        if await handle_reply(office, m["from"], m["subject"], m["body"]):
            n += 1
    return n


# ------------------------------------------------------------------ pagamento e Héstia: entrega
def payment_link(office: Office, p: Prospect, plan: str) -> str | None:
    base = office.settings.payment_link_mensal if plan == "mensal" else office.settings.payment_link_diagnostico
    if not base:
        return None
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}client_reference_id={quote(p.token)}" + (f"&prefilled_email={quote(p.email)}" if p.email else "")


def verify_stripe(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    parts = dict(x.split("=", 1) for x in header.split(",") if "=" in x)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    try:
        fresh = abs(datetime.now(UTC).timestamp() - int(ts)) <= tolerance
    except ValueError:
        return False
    return fresh and hmac.compare_digest(expected, sig)


async def handle_stripe(office: Office, event: dict[str, Any]) -> str:
    kind = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        token = obj.get("client_reference_id")
        async with session_scope() as s:
            p = (await s.execute(select(Prospect).where(Prospect.token == token))).scalar_one_or_none() if token else None
        if p is None:
            return "ignorado: sem prospect"
        amount = float(obj.get("amount_total") or 0) / 100
        plan = "mensal" if obj.get("mode") == "subscription" or abs(amount - office.settings.price_mensal_brl) < 1 else "diagnostico"
        await activate(office, p, plan=plan, amount_brl=amount, ref=str(obj.get("customer") or obj.get("id") or ""))
        return f"cliente ativado ({plan})"
    if kind == "invoice.paid" and obj.get("billing_reason") == "subscription_cycle":
        async with session_scope() as s:
            c = (await s.execute(select(Client).where(Client.payment_ref == str(obj.get("customer") or "")))).scalar_one_or_none()
        if c:
            await _revenue(office, c.id, float(obj.get("amount_paid") or 0) / 100, f"Mensalidade {c.company}")
            return "mensalidade registrada"
    if kind == "customer.subscription.deleted":
        async with session_scope() as s:
            c = (await s.execute(select(Client).where(Client.payment_ref == str(obj.get("customer") or "")))).scalar_one_or_none()
            if c:
                c.status = "cancelado"
                await office.alert("warning", SUCCESS, f"{c.company} cancelou a assinatura.")
                return "cancelado"
    return "ignorado"


async def _revenue(office: Office, client_id: str, amount_brl: float, desc: str) -> None:
    if amount_brl <= 0:
        return
    usd = round(amount_brl / office.settings.brl_per_usd, 2)
    await office.ledger.record_revenue("agencia", usd, f"{desc} (R$ {amount_brl:,.2f})", projected=False)
    await office.emit("revenue", stream="agencia", amount=usd)


async def activate(office: Office, p: Prospect, *, plan: str, amount_brl: float, ref: str = "") -> Client:
    async with session_scope() as s:
        existing = (await s.execute(select(Client).where(Client.prospect_id == p.id))).scalar_one_or_none()
        if existing:
            return existing
        c = Client(token=secrets.token_urlsafe(24), prospect_id=p.id, company=p.company, email=p.email, plan=plan,
                   mrr_brl=amount_brl if plan == "mensal" else 0.0, payment_ref=ref, diagnoses=[p.diagnosis_id] if p.diagnosis_id else [],
                   next_report_at=datetime.now(UTC) + timedelta(days=30) if plan == "mensal" else None)
        s.add(c)
        row = await s.get(Prospect, p.id)
        if row:
            row.status = "cliente"
    await _revenue(office, c.id, amount_brl, f"{'Mensalidade' if plan == 'mensal' else 'Diagnóstico'} {p.company}")
    await office.alert("info", SUCCESS, f"Novo cliente: {p.company} ({plan}, R$ {amount_brl:,.2f}).")
    await deliver_kit(office, c.id)
    return c


async def deliver_kit(office: Office, client_id: str) -> None:
    async with session_scope() as s:
        c = await s.get(Client, client_id)
        p = await s.get(Prospect, c.prospect_id) if c else None
        d = await s.get(Diagnosis, p.diagnosis_id) if p and p.diagnosis_id else None
    if c is None or p is None:
        return
    await _status(office, SUCCESS, "working", f"montando o kit de {c.company}")
    out = await office.llm.complete_json(
        kind="sales.kit", system="Você é Héstia, especialista em GEO. Gera entregáveis prontos para o site do cliente.",
        prompt=(f"Empresa: {p.company} ({p.site}). Segmento: {p.segment}. Perguntas de compra: {(d.queries if d else [])}.\n"
                "Gere: faq [6 {q, a}] respondendo essas perguntas do ponto de vista da empresa; use [CONFIRMAR: ...] onde precisar de "
                "um dado que você não tem (preço, prazo, endereço) — nunca invente; llms_txt (arquivo llms.txt em markdown com seções); "
                "about (parágrafo 'quem somos' factual com [CONFIRMAR] onde faltar dado). Retorne JSON: {faq, llms_txt, about}."),
        tier="worker", agent_id=SUCCESS, context={"company": p.company, "queries": d.queries if d else []},
    )
    org = {"@context": "https://schema.org", "@type": "Organization", "name": p.company, "url": p.site}
    faq = [f for f in out.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")][:8]
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]}
    robots = "\n".join(f"User-agent: {b}\nAllow: /\n" for b in dg.AI_BOTS)
    kit = {"organization_jsonld": org, "faq": faq, "faq_jsonld": faq_ld, "llms_txt": str(out.get("llms_txt") or ""), "about": str(out.get("about") or ""),
           "robots_txt": robots, "ad_drafts": (d.plan.get("ad_drafts") if d else []) or [], "quick_wins": (d.plan.get("quick_wins") if d else []) or []}
    async with session_scope() as s:
        row = await s.get(Client, client_id)
        if row:
            row.kit = kit
            if row.plan == "diagnostico":
                row.status = "concluido"
    st = office.settings
    await mailer.send(st, to=c.email, subject=f"{c.company}: seu kit de visibilidade em IA está pronto", kind="boas_vindas", prospect_id=p.id, transactional=True,
                      body=(f"Olá! Obrigado por contratar a {st.agency_name}.\n\nSua página de cliente, com o diagnóstico, o kit de GEO (dados estruturados, "
                            f"llms.txt, perguntas frequentes) e os rascunhos de anúncios no ChatGPT:\n{base_url(office)}/cliente/{c.token}\n\n"
                            "Os itens marcados com [CONFIRMAR] precisam de um dado da sua empresa antes de publicar."
                            + ("\n\nTodo mês você recebe um novo diagnóstico com a evolução." if c.plan == "mensal" else "")))
    await _status(office, SUCCESS, "idle", f"kit entregue a {c.company}")
    await _say(office, SUCCESS, "founder", f"Kit de GEO entregue a {c.company}")


async def monthly(office: Office) -> int:
    now = datetime.now(UTC)
    async with session_scope() as s:
        due = list((await s.execute(select(Client).where(Client.status == "ativo", Client.plan == "mensal", Client.next_report_at <= now))).scalars())
    for c in due:
        async with session_scope() as s:
            p = await s.get(Prospect, c.prospect_id)
            prev = await s.get(Diagnosis, c.diagnoses[-1]) if c.diagnoses else None
        if p is None:
            continue
        await _status(office, SUCCESS, "working", f"relatório mensal de {c.company}")
        d = await dg.create(office, brand=p.company, site=p.site, category=p.segment, city=p.city, competitors=prev.competitors if prev else None)
        d = await dg.run(office, d.id)
        if d.status != "done":
            continue
        delta = d.scores["overall"] - (prev.scores.get("overall", 0) if prev and prev.scores else 0)
        async with session_scope() as s:
            row = await s.get(Client, c.id)
            if row:
                row.diagnoses = [*row.diagnoses, d.id]
                row.next_report_at = now + timedelta(days=30)
        await mailer.send(office.settings, to=c.email, subject=f"{c.company}: relatório mensal de visibilidade em IA", kind="relatorio", prospect_id=p.id, transactional=True,
                          body=(f"Olá! Seu relatório do mês está pronto. Nota atual: {d.scores['overall']}/100 ({'+' if delta >= 0 else ''}{delta} desde o último).\n\n"
                                f"Relatório: {base_url(office)}/relatorio/{d.token}\nSua página: {base_url(office)}/cliente/{c.token}"))
        await _status(office, SUCCESS, "idle", f"relatório mensal enviado a {c.company}")
    return len(due)


# ------------------------------------------------------------------ inbound (pedido pelo site)
async def inbound(office: Office, *, company: str, site: str, segment: str, city: str, email: str, name: str) -> Prospect:
    domain = site_domain(site) if site else mailer.domain_of(email)
    async with session_scope() as s:
        p = (await s.execute(select(Prospect).where(Prospect.email == email.lower()))).scalars().first()
        if p is None:
            p = Prospect(token=secrets.token_urlsafe(24), company=company[:200], site=(site if "://" in site else f"https://{site}") if site else "", domain=domain,
                         email=email.lower(), contact_name=name[:160], segment=segment[:300], city=city[:120], source="inbound", consent=True)
            s.add(p)
        else:
            p.consent, p.status = True, "novo" if p.status in ("perdido", "sem_contato") else p.status
    await _say(office, "founder", PROSPECTOR, f"Pedido de diagnóstico pelo site: {company}")
    return p


# ------------------------------------------------------------------ ciclo
async def tick(office: Office, *, force: bool = False) -> dict[str, Any]:
    """Uma volta completa do funil. Roda sozinho a cada `sales_interval_seconds` com o comercial ligado."""
    gov = await office.gov.snapshot()
    if not (gov["sales_enabled"] or force):
        return {"skipped": "comercial desligado"}
    from app.core import insighta

    out: dict[str, Any] = {}
    try:
        out["respostas"] = await replies(office)
        if insighta.enabled(office):  # vende o SaaS: Google Maps → e-mail → teste grátis (cobrança e entrega são da Insighta)
            out["novas_empresas"] = await insighta.discover(office)
            out["envios"] = await outreach(office)
        else:
            out["novas_empresas"] = await discover(office)
            out["diagnosticos"] = await diagnose(office)
            out["envios"] = await outreach(office)
            out["relatorios_mensais"] = await monthly(office)
    except BudgetExceeded as e:
        out["parou"] = f"sem orçamento/cota de IA: {e}"
    await office.emit("sales", **{k: v for k, v in out.items() if isinstance(v, (int, str))})
    return out


async def summary(office: Office) -> dict[str, Any]:
    async with session_scope() as s:
        funnel = dict((await s.execute(select(Prospect.status, func.count()).group_by(Prospect.status))).all())
        prospects = list((await s.execute(select(Prospect).order_by(Prospect.updated_at.desc()).limit(50))).scalars())
        clients = list((await s.execute(select(Client).order_by(Client.started_at.desc()))).scalars())
        scores = {d.id: d.scores for d in (await s.execute(select(Diagnosis).where(Diagnosis.id.in_([p.diagnosis_id for p in prospects if p.diagnosis_id])))).scalars()}
        tokens = {d.id: d.token for d in (await s.execute(select(Diagnosis).where(Diagnosis.id.in_([p.diagnosis_id for p in prospects if p.diagnosis_id])))).scalars()}
        emails = list((await s.execute(select(EmailLog).order_by(EmailLog.created_at.desc()).limit(20))).scalars())
    gov = await office.gov.snapshot()
    from app.core import insighta

    return {
        "business": office.settings.business, "insighta": await insighta.summary(office) if insighta.enabled(office) else None,
        "enabled": gov["sales_enabled"], "auto_send": gov["sales_auto_send"], "cap": gov["sales_daily_email_cap"],
        "sent_today": await emails_sent_today(), "send_window": in_send_window(), "health": health(office),
        "funnel": funnel, "mrr_brl": round(sum(c.mrr_brl for c in clients if c.status == "ativo"), 2),
        "prices": {"diagnostico": office.settings.price_diagnostico_brl, "mensal": office.settings.price_mensal_brl},
        "prospects": [{"id": p.id, "company": p.company, "domain": p.domain, "email": p.email, "segment": p.segment, "city": p.city, "source": p.source, "status": p.status,
                       "touches": p.touches, "last_contact_at": p.last_contact_at, "score": (scores.get(p.diagnosis_id) or {}).get("overall"),
                       "report": f"/relatorio/{tokens[p.diagnosis_id]}" if p.diagnosis_id in tokens else None, "proposal": f"/proposta/{p.token}"} for p in prospects],
        "clients": [{"company": c.company, "plan": c.plan, "status": c.status, "mrr_brl": c.mrr_brl, "started_at": c.started_at, "next_report_at": c.next_report_at,
                     "page": f"/cliente/{c.token}", "reports": len(c.diagnoses)} for c in clients],
        "emails": [{"at": e.created_at, "direction": e.direction, "kind": e.kind, "to": e.to_addr, "from": e.from_addr, "subject": e.subject, "status": e.status, "intent": e.intent} for e in emails],
    }
