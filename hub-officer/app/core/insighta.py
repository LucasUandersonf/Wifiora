"""Modo Insighta: o escritório vira a área comercial e de marketing do SaaS Insighta (inteligência para clínicas).

    Diana (prospecção)  → acha clínicas no Google Maps pela Places API oficial e o e-mail comercial no site da clínica
    Mercúrio (vendas)   → e-mail curto sobre a dor da clínica (glosa, faltas, caixa) com link para a calculadora/teste grátis
    Oferta              → preços, vagas Founders e dias de teste vêm AO VIVO da API da Insighta (`/public/founders`)
    Conversão           → todo link leva UTM (origem, campanha, clínica) para medir clique → cadastro

Google Maps: só a API oficial (nada de raspar a página do Maps). Pelos termos do Google Maps Platform, guardamos sem
prazo apenas o `place_id`; nome, e-mail e site da empresa vêm do PRÓPRIO site da clínica. WhatsApp frio não: a política
do WhatsApp exige consentimento. O canal é e-mail B2B com descadastro (e ligação humana, se o fundador quiser).
"""

from __future__ import annotations

import json
import re
import logging
import random
import secrets
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import httpx
from sqlalchemy import func, select

from app.core import mailer
from app.core import sales, sales_skills
from app.db import session_scope
from app.models import CostEntry, Prospect

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
# A máscara define a faixa de preço da chamada: websiteUri é o que precisamos (o resto vem do site da clínica).
PLACES_FIELDS = "places.id,places.displayName,places.websiteUri,places.formattedAddress,places.businessStatus"
PAINS = {
    "odontológica": "orçamentos aprovados que não viram tratamento e faltas na agenda",
    "fisioterapia": "sessões que faltam no meio do pacote e glosas de convênio",
    "imagem": "glosas de convênio e exames realizados que não são faturados",
    "laboratório": "glosas de convênio e exames realizados que não são faturados",
    "estética": "pacotes vendidos que o paciente abandona e faltas na agenda",
    "psicologia": "faltas e cancelamentos em cima da hora",
}
DEFAULT_PAIN = "glosas de convênio, faltas na agenda e dinheiro que fatura mas não chega ao caixa"
PRICE_Q = re.compile(r"pre[cç]o|valor|caro|desconto|quanto custa|or[cç]amento|plano", re.I)
_offer_cache: tuple[float, dict[str, Any]] = (0.0, {})


def enabled(office: Office) -> bool:
    return office.settings.business == "insighta"


def pain_for(segment: str) -> str:
    seg = segment.lower()
    return next((v for k, v in PAINS.items() if k in seg), DEFAULT_PAIN)


# ------------------------------------------------------------------ links com UTM
def utm(url: str, *, campaign: str, content: str = "", medium: str = "email", source: str = "escritorio") -> str:
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query))
    q.update({"utm_source": source, "utm_medium": medium, "utm_campaign": campaign})
    if content:
        q["utm_content"] = content[:80]
    return urlunparse(parts._replace(query=urlencode(q)))


def landing_url(office: Office) -> str:
    st = office.settings
    return (st.insighta_landing_url or st.insighta_app_url).rstrip("/")


def calculator_link(office: Office, p: Prospect, touch: int) -> str:
    base = office.settings.insighta_landing_url
    url = f"{base.rstrip('/')}/#calculadora" if base else f"{office.settings.insighta_app_url.rstrip('/')}/signup"
    # o fragmento precisa ficar no fim, depois da query
    path, _, frag = url.partition("#")
    return utm(path, campaign=f"prospeccao-{_slug(p.segment)}", content=f"{p.token[:10]}-t{touch}") + (f"#{frag}" if frag else "")


def signup_link(office: Office, p: Prospect, content: str = "resposta") -> str:
    return utm(f"{office.settings.insighta_app_url.rstrip('/')}/signup", campaign=f"prospeccao-{_slug(p.segment)}", content=f"{p.token[:10]}-{content}")


def _slug(text: str) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "clinicas"


# ------------------------------------------------------------------ oferta ao vivo
async def offer(office: Office, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Preços e vagas Founders direto da Insighta (cache de 10 min); se a API não responder, usa a configuração."""
    global _offer_cache
    st = office.settings
    if _offer_cache[1] and time.monotonic() - _offer_cache[0] < 600 and transport is None:
        return _offer_cache[1]
    out: dict[str, Any] = {
        "basic_brl": st.insighta_price_basic_brl, "pro_brl": st.insighta_price_pro_brl, "founders_brl": st.insighta_price_founders_brl,
        "trial_days": st.insighta_trial_days, "founders_remaining": None, "founders_total": None, "lock_months": None, "live": False,
    }
    if st.allow_web_fetch or transport is not None:
        try:
            async with httpx.AsyncClient(timeout=10, transport=transport) as c:
                r = await c.get(f"{st.insighta_api_url.rstrip('/')}/public/founders")
            r.raise_for_status()
            d = r.json()
            out.update(
                founders_brl=d["price_cents"] / 100, founders_remaining=int(d["slots_remaining"]), founders_total=int(d["slots_total"]),
                lock_months=d.get("lock_months"), trial_days=d.get("trial_days") or out["trial_days"], live=True,
                basic_brl=(d.get("basic_price_cents") or st.insighta_price_basic_brl * 100) / 100,
                pro_brl=(d.get("pro_price_cents") or st.insighta_price_pro_brl * 100) / 100,
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            log.info("oferta da Insighta indisponível, usando configuração: %s", e)
    _offer_cache = (time.monotonic(), out)
    return out


# ------------------------------------------------------------------ Diana: Google Maps
async def places_calls_today() -> int:
    from app.core.ledger import _day_start

    async with session_scope() as s:
        q = select(func.count(CostEntry.id)).where(CostEntry.category == "maps", CostEntry.created_at >= _day_start())
        return int((await s.execute(q)).scalar_one())


async def places_search(office: Office, text: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict[str, str]]:
    st = office.settings
    body = {"textQuery": text, "languageCode": "pt-BR", "regionCode": "BR", "pageSize": 20}
    headers = {"X-Goog-Api-Key": st.google_maps_api_key or "", "X-Goog-FieldMask": PLACES_FIELDS}
    async with httpx.AsyncClient(timeout=30, transport=transport) as c:
        r = await c.post(PLACES_URL, json=body, headers=headers)
    await office.ledger.record_cost("maps", st.places_cost_per_call_usd, f"google maps: {text}"[:300])
    r.raise_for_status()
    out = []
    for pl in r.json().get("places") or []:
        if pl.get("businessStatus") not in (None, "OPERATIONAL"):
            continue
        out.append({"place_id": pl.get("id") or "", "name": (pl.get("displayName") or {}).get("text") or "", "website": pl.get("websiteUri") or ""})
    return [p for p in out if p["place_id"]]


async def discover(office: Office, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Uma busca no Google Maps (tipo de clínica × cidade) → clínicas novas com site e e-mail comercial."""
    st = office.settings
    if office.llm.client.provider == "mock" and not st.google_maps_api_key:
        return await _discover_demo(office)
    if not st.google_maps_api_key or not (st.allow_web_fetch or transport is not None):
        return 0
    if await places_calls_today() >= st.places_daily_call_cap:
        return 0
    seg, city = random.choice(st.insighta_segment_list or ["clínica"]), random.choice(st.insighta_city_list or ["São Paulo"])
    await sales._status(office, sales.PROSPECTOR, "working", f"Google Maps: {seg} em {city}")
    try:
        places = await places_search(office, f"{seg} em {city}", transport)
    except httpx.HTTPError as e:
        await sales._status(office, sales.PROSPECTOR, "idle", f"Google Maps falhou: {e}"[:200])
        return 0
    async with session_scope() as s:
        known = set((await s.execute(select(Prospect.place_id).where(Prospect.place_id.in_([p["place_id"] for p in places])))).scalars())
    added = 0
    for pl in places:
        if added >= st.sales_new_prospects_per_run:
            break
        if pl["place_id"] in known or not pl["website"]:
            continue
        domain = sales.site_domain(pl["website"])
        if sales.blocked(domain) or await mailer.suppressed(f"x@{domain}"):
            continue
        async with session_scope() as s:
            if (await s.execute(select(Prospect.id).where(Prospect.domain == domain))).first():
                continue  # rede com várias unidades: um contato por domínio
        info = await sales.enrich(domain)
        async with session_scope() as s:
            s.add(Prospect(
                token=secrets.token_urlsafe(24), company=info["company"] if info["company"] != domain.split(".")[0].capitalize() else pl["name"][:200],
                site=f"https://{domain}", domain=domain, email=info["emails"][0] if info["emails"] else "", segment=seg, city=city,
                source="maps", place_id=pl["place_id"], status="novo" if info["emails"] else "sem_contato",
            ))
        added += 1
    await sales._status(office, sales.PROSPECTOR, "idle", f"{added} clínica(s) nova(s): {seg} em {city}")
    if added:
        await sales._say(office, sales.PROSPECTOR, sales.CLOSER, f"{added} clínica(s) de {city} prontas para contato")
    return added


async def _discover_demo(office: Office) -> int:
    async with session_scope() as s:
        if (await s.execute(select(func.count(Prospect.id)).where(Prospect.source == "demo"))).scalar_one() >= 3:
            return 0
        for i, (name, seg) in enumerate([("Odonto Demo", "clínica odontológica"), ("Fisio Demo", "clínica de fisioterapia"), ("Imagem Demo", "clínica de imagem")]):
            d = f"{name.split()[0].lower()}-demo{i}.invalid"
            s.add(Prospect(token=secrets.token_urlsafe(24), company=name, site=f"https://{d}", domain=d, email=f"contato@{d}", segment=seg,
                           city="São Paulo", source="demo", place_id=f"demo-{i}"))
    await sales._say(office, sales.PROSPECTOR, sales.CLOSER, "3 clínicas de demonstração prontas para contato")
    return 3


# ------------------------------------------------------------------ Mercúrio: e-mails
async def compose(office: Office, p: Prospect, touch: int) -> tuple[str, str]:
    o = await offer(office)
    facts = {
        "clinica": p.company, "tipo": p.segment, "cidade": p.city, "dor_tipica": pain_for(p.segment), "teste_gratis_dias": o["trial_days"],
        "vagas_founders_restantes": o["founders_remaining"], "preco_founders_brl": o["founders_brl"], "contato_numero": touch,
    }
    out = await office.llm.complete_json(
        kind="insighta.email",
        system=sales_skills.system("Você é Mercúrio, do comercial da Insighta (inteligência de dados para clínicas). Escreve e-mails B2B curtos, humanos e honestos em português do Brasil.", "first_touch" if touch == 1 else "followup"),
        prompt=(
            f"FATOS (use só estes): {json.dumps(facts, ensure_ascii=False)}\n"
            f"Escreva o e-mail {'de primeiro contato' if touch == 1 else f'de acompanhamento nº {touch - 1} (curto, sem insistir)'} para o gestor da clínica. "
            "Fale da dor típica como pergunta (não como acusação), convide a calcular quanto a clínica perde (link adicionado depois) e cite o teste grátis. "
            "Só mencione as vagas Founders se o número de vagas for informado. Proibido: prometer resultado, inventar números, pressão. Até 110 palavras. "
            'Retorne JSON: {"subject": "...", "body": "..."}'
        ),
        tier="worker", agent_id=sales.CLOSER, context={"prospect": p.company, "facts": facts, "touch": touch},
    )
    subject, body = str(out.get("subject") or "").strip()[:120], str(out.get("body") or "").strip()
    if not subject or not body or sales.BANNED.search(subject + body):
        subject = f"{p.company}: quanto do faturamento chega ao caixa?" if touch == 1 else f"{p.company}: a conta leva 2 minutos"
        body = (f"Olá, equipe da {p.company}.\n\nEm {p.segment.split(' de ')[-1] if ' de ' in p.segment else 'clínicas'}, é comum o caixa perder dinheiro com "
                f"{facts['dor_tipica']} sem ninguém ver o número exato. A Insighta junta agenda, faturamento e convênios e mostra onde está a perda.\n\n"
                f"A calculadora abaixo estima o valor da sua clínica em 2 minutos, e dá para testar com os dados reais por {o['trial_days']} dias, sem cartão."
                + (f"\n\nAinda restam {o['founders_remaining']} vagas do plano Founders (R$ {o['founders_brl']:.0f}/mês com preço travado)." if o["founders_remaining"] else "")
                + "\n\nSe preferir conversar, é só responder este e-mail.")
    return subject, f"{body}\n\nCalcule a perda da sua clínica: {calculator_link(office, p, touch)}{sales.footer(office, p)}"


async def answer(office: Office, p: Prospect, question: str) -> None:
    """Resposta a quem respondeu com interesse/dúvida: tira a dúvida e leva ao teste grátis (o cadastro é self-service)."""
    st = office.settings
    o = await offer(office)
    facts = {
        "planos": {"Basic": f"R$ {o['basic_brl']:.0f}/mês", "Pro": f"R$ {o['pro_brl']:.0f}/mês", "Pro Founders": f"R$ {o['founders_brl']:.0f}/mês, preço travado"},
        "vagas_founders_restantes": o["founders_remaining"], "teste_gratis_dias": o["trial_days"], "teste_sem_cartao": True,
        "o_que_faz": ["painel de faturamento x caixa", "risco de glosa por convênio", "faltas e agenda", "CRM de pacientes", "resumo executivo"],
    }
    await sales._status(office, sales.CLOSER, "working", f"respondendo {p.company}")
    out = await office.llm.complete_json(
        kind="insighta.answer", system=sales_skills.system("Você é Mercúrio, do comercial da Insighta. Responde gestores de clínica com clareza e honestidade.", "negotiate" if PRICE_Q.search(question) else "answer"),
        prompt=(f"Mensagem da clínica:\n{question[:2000]}\n\nOFERTA (use só isto, sem inventar preço, prazo ou resultado): {json.dumps(facts, ensure_ascii=False)}\n"
                "Responda em até 120 palavras e convide a começar o teste grátis (link adicionado depois) ou marcar uma demonstração respondendo. Retorne JSON: {\"body\": \"...\"}"),
        tier="worker", agent_id=sales.CLOSER, context={"prospect": p.company, "offer": facts},
    )
    body = str(out.get("body") or "").strip()
    if not body or sales.BANNED.search(body):
        body = (f"Obrigado pelo retorno! O jeito mais rápido de ver a Insighta com os números da {p.company} é o teste de {o['trial_days']} dias, sem cartão. "
                "Se preferir, responda com dois horários e marcamos uma demonstração de 20 minutos.")
    body += f"\n\nComeçar o teste grátis: {signup_link(office, p)}{sales.footer(office, p)}"
    await mailer.send(st, to=p.email, subject=f"Re: Insighta para a {p.company}", body=body, kind="resposta", prospect_id=p.id, transactional=True)
    from datetime import UTC, datetime

    await sales._set(p.id, status="proposta", last_contact_at=datetime.now(UTC))
    await sales._status(office, sales.CLOSER, "idle", f"link do teste enviado a {p.company}")
    await sales._say(office, sales.CLOSER, "founder", f"{p.company} respondeu com interesse: link do teste grátis enviado")
    await office.alert("info", sales.CLOSER, f"{p.company} ({p.city}) respondeu com interesse — vale uma ligação humana.")


# ------------------------------------------------------------------ painel
async def summary(office: Office) -> dict[str, Any]:
    st = office.settings
    o = await offer(office)
    return {
        "offer": o, "landing": landing_url(office), "app": st.insighta_app_url, "maps_ready": bool(st.google_maps_api_key),
        "maps_calls_today": await places_calls_today(), "maps_cap": st.places_daily_call_cap,
        "segments": st.insighta_segment_list, "cities": st.insighta_city_list,
    }
