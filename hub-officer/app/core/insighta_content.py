"""Time de Conteúdo & GEO da Insighta: pauta → rascunho por IA → aprovação do fundador → página pronta para publicar.

    Calíope (conteúdo)   → escreve páginas que respondem dúvidas exatas de gestores de clínica (playbook em inglês)
    Argos (GEO técnico)  → audita a landing toda semana (indexação liberada, JSON-LD, sitemap, llms.txt…)

Nada vai ao ar sozinho: rascunho só vira página depois do "aprovar" no painel, e a publicação é no site da Insighta.
Números e porcentagens que aparecem no texto ganham alerta de conferência — IA não pode inventar estatística.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import func, select

from app.core import diagnosis as dg
from app.core import sales
from app.db import session_scope
from app.models import AgentState, ContentPiece

if TYPE_CHECKING:
    from app.core.office import Office

WRITER, GEO = "content.writer", "content.geo"
PERSONAS = {
    WRITER: ("Calíope", "Conteúdo", "Escrever páginas que respondem dúvidas reais de gestores de clínica e levam à calculadora/teste."),
    GEO: ("Argos", "GEO técnico", "Auditar a landing da Insighta toda semana e manter o site legível para buscadores e IAs."),
}
PLAYBOOK = Path(__file__).resolve().parent.parent / "playbooks" / "content" / "geo_article.md"
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%|R\$\s*\d[\d.,]*")
PROMISE_RE = re.compile(r"garant|100\s*%|recupere (todo|tudo)|resultado (certo|garantido)", re.I)

# Pauta inicial: dúvidas de quem tem o problema (→ calculadora) e de quem procura solução (→ teste grátis).
# As 3 primeiras já estão previstas no ESTRATEGIA.md da landing.
BACKLOG: list[dict[str, Any]] = [
    {"title": "O que é glosa médica e por que ela acontece", "keyword": "o que é glosa médica", "cluster": "glosa", "intent": "problema", "priority": 100,
     "brief": "Definição; tipos (administrativa, técnica, linear); causas mais comuns; como prevenir. Fontes permitidas: ANS e padrão TISS."},
    {"title": "Como fazer recurso de glosa: passo a passo", "keyword": "como fazer recurso de glosa", "cluster": "glosa", "intent": "problema", "priority": 95,
     "brief": "Fluxo do recurso; documentos; prazos (orientar a conferir o contrato e a regra vigente); erros que fazem perder o recurso. Fonte: padrão TISS/ANS."},
    {"title": "Como reduzir faltas de pacientes na clínica", "keyword": "como reduzir faltas em clínica", "cluster": "agenda", "intent": "problema", "priority": 90,
     "brief": "Custo da falta (exemplo hipotético); confirmação, lista de espera, política de remarcação, indicadores por profissional."},
    {"title": "Glosa administrativa x glosa técnica: diferenças e como evitar cada uma", "keyword": "glosa administrativa e técnica", "cluster": "glosa", "intent": "problema", "priority": 80,
     "brief": "Tabela comparativa; exemplos; quem na equipe previne cada uma."},
    {"title": "Faturado x recebido: como descobrir quanto da receita da clínica não chega ao caixa", "keyword": "faturamento x recebimento clínica", "cluster": "financeiro", "intent": "problema", "priority": 85,
     "brief": "Conceito de conciliação; onde o dinheiro se perde (glosa, repasse, inadimplência, taxas); rotina mensal de conferência."},
    {"title": "Como conferir o repasse dos convênios", "keyword": "conferir repasse convênio", "cluster": "financeiro", "intent": "problema", "priority": 75,
     "brief": "Demonstrativo de pagamento; conferência guia a guia; divergências comuns; o que registrar."},
    {"title": "Indicadores de gestão de clínica que o dono deve olhar todo mês", "keyword": "indicadores de gestão de clínica", "cluster": "gestao", "intent": "solucao", "priority": 70,
     "brief": "Taxa de glosa, taxa de faltas, ticket médio, ocupação da agenda, prazo de recebimento; como calcular cada um."},
    {"title": "Padrão TISS: o que é e o que muda no faturamento da clínica", "keyword": "padrão TISS", "cluster": "faturamento", "intent": "problema", "priority": 65,
     "brief": "O que é o padrão TISS (ANS), componentes, por que erros de guia geram glosa. Orientar a conferir a versão vigente no site da ANS."},
    {"title": "Planilha ou sistema de BI para gestão de clínica: quando a planilha deixa de dar conta", "keyword": "BI para clínica", "cluster": "gestao", "intent": "solucao", "priority": 60,
     "brief": "Sinais de que a planilha não basta; o que um BI/inteligência de dados faz; como avaliar ferramentas sem trocar de sistema."},
    {"title": "Orçamento aprovado que não vira tratamento: como recuperar na odontologia", "keyword": "orçamento odontológico não fechado", "cluster": "agenda", "intent": "problema", "priority": 55,
     "brief": "Por que o paciente não inicia; acompanhamento; indicadores de conversão de orçamento."},
]


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:120]


@cache
def playbook() -> str:
    return PLAYBOOK.read_text(encoding="utf-8").strip()


def enabled(office: Office) -> bool:
    return office.settings.business == "insighta"


async def register_personas() -> None:
    async with session_scope() as s:
        for aid, (name, role, mission) in PERSONAS.items():
            row = await s.get(AgentState, aid)
            if row is None:
                s.add(AgentState(agent_id=aid, title=f"{name} — {role}", sector="conteudo", role="specialist", skills=[], status="idle", current_activity=mission))


async def seed() -> int:
    added = 0
    async with session_scope() as s:
        have = set((await s.execute(select(ContentPiece.slug))).scalars())
        for b in BACKLOG:
            slug = _slug(b["keyword"])
            if slug not in have:
                s.add(ContentPiece(slug=slug, **b))
                added += 1
    return added


def review_flags(body: str) -> list[str]:
    """Alertas para o fundador conferir antes de aprovar (a IA não pode inventar número nem prometer resultado)."""
    flags = [f"conferir número: “{m.group(0).strip()}”" for m in NUMBER_RE.finditer(body)][:10]
    if PROMISE_RE.search(body):
        flags.append("possível promessa de resultado — reescrever")
    return flags


# ------------------------------------------------------------------ Calíope: rascunho
async def draft(office: Office) -> ContentPiece | None:
    async with session_scope() as s:
        p = (await s.execute(select(ContentPiece).where(ContentPiece.status == "pauta").order_by(ContentPiece.priority.desc(), ContentPiece.created_at).limit(1))).scalar_one_or_none()
    if p is None:
        return None
    from app.core.insighta import landing_url

    cta = "a calculadora de perda (link adicionado depois)" if p.intent == "problema" else "o teste grátis de 14 dias (link adicionado depois)"
    await sales._status(office, WRITER, "working", f"escrevendo: {p.title}")
    out = await office.llm.complete_json(
        kind="insighta.article",
        system=f"Você é Calíope, redatora de conteúdo da Insighta (inteligência de dados para clínicas).\n\n=== CONTENT PLAYBOOK (internal) ===\n{playbook()}\n=== END ===",
        prompt=(f"Página: {p.title}\nPalavra-chave: {p.keyword}\nO que cobrir e fontes permitidas: {p.brief}\nChamada para ação única: {cta}.\n"
                "Retorne JSON: {\"title\": \"pergunta/título (H1)\", \"meta_description\": \"até 155 caracteres\", \"body_markdown\": \"texto em Markdown com H2, sem H1\", "
                "\"faq\": [{\"q\": \"...\", \"a\": \"...\"}], \"sources\": [\"nome da fonte oficial citada\"]}"),
        tier="worker", agent_id=WRITER, context={"title": p.title, "keyword": p.keyword},
    )
    body = str(out.get("body_markdown") or "").strip()
    if not body:
        await sales._status(office, WRITER, "idle", f"sem rascunho para {p.title} (IA não respondeu)")
        return None
    faq = [{"q": str(f.get("q", ""))[:300], "a": str(f.get("a", ""))[:1000]} for f in out.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")][:6]
    flags = review_flags(body + " " + " ".join(f["a"] for f in faq))
    async with session_scope() as s:
        row = await s.get(ContentPiece, p.id)
        row.title = str(out.get("title") or p.title)[:300]
        row.meta_description = str(out.get("meta_description") or "")[:300]
        row.body_md, row.faq, row.sources = body, faq, [str(x)[:200] for x in out.get("sources") or []][:8]
        row.review_notes, row.status = "\n".join(flags), "rascunho"
    await sales._status(office, WRITER, "idle", f"rascunho pronto: {p.title}")
    await office.alert("info", WRITER, f"Rascunho para aprovar: “{p.title}”" + (f" ({len(flags)} alerta(s) para conferir)" if flags else "") + f". Destino: {landing_url(office)}/{p.slug}")
    async with session_scope() as s:
        return await s.get(ContentPiece, p.id)


async def decide(piece_id: str, approve: bool, note: str = "") -> ContentPiece | None:
    async with session_scope() as s:
        p = await s.get(ContentPiece, piece_id)
        if p is None or p.status not in ("rascunho", "aprovado"):
            return p
        p.status = "aprovado" if approve else "rejeitado"
        if note:
            p.review_notes = (p.review_notes + f"\nfundador: {note}").strip()
        return p


def export_markdown(office: Office, p: ContentPiece) -> str:
    """Página pronta para o site: front matter + corpo + FAQ + JSON-LD (Article e FAQPage) + chamada com UTM."""
    from app.core.insighta import landing_url, utm

    base = landing_url(office)
    url = f"{base}/{p.slug}"
    cta_url = (utm(f"{base}/", campaign=f"blog-{p.slug}", medium="conteudo", source="blog") + "#calculadora") if p.intent == "problema" \
        else utm(f"{office.settings.insighta_app_url.rstrip('/')}/signup", campaign=f"blog-{p.slug}", medium="conteudo", source="blog")
    cta = "Calcule quanto a sua clínica tem em jogo" if p.intent == "problema" else "Teste o Insighta por 14 dias, sem cartão"
    ld = [
        {"@context": "https://schema.org", "@type": "Article", "headline": p.title, "description": p.meta_description, "inLanguage": "pt-BR", "url": url,
         "dateModified": (p.updated_at or datetime.now(UTC)).date().isoformat(), "publisher": {"@type": "Organization", "name": "Insighta", "url": f"{base}/"}},
    ]
    if p.faq:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in p.faq]})
    faq_md = ("\n\n## Perguntas frequentes\n\n" + "\n\n".join(f"### {f['q']}\n\n{f['a']}" for f in p.faq)) if p.faq else ""
    src = ("\n\n## Fontes\n\n" + "\n".join(f"- {x}" for x in p.sources)) if p.sources else ""
    return (f"---\ntitle: {json.dumps(p.title, ensure_ascii=False)}\ndescription: {json.dumps(p.meta_description, ensure_ascii=False)}\nslug: {p.slug}\n"
            f"canonical: {url}\nkeyword: {json.dumps(p.keyword, ensure_ascii=False)}\nstatus: {p.status}\n---\n\n# {p.title}\n\n{p.body_md}{faq_md}{src}\n\n"
            f"**[{cta} →]({cta_url})**\n\n<script type=\"application/ld+json\">\n{json.dumps(ld, ensure_ascii=False, indent=1)}\n</script>\n")


# ------------------------------------------------------------------ Argos: auditoria da landing
async def audit(office: Office, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    st = office.settings
    site = st.insighta_landing_url
    if not site:
        res: dict[str, Any] = {"checked": False, "reason": "INSIGHTA_LANDING_URL não configurada (a landing precisa de domínio próprio)"}
    else:
        await sales._status(office, GEO, "working", f"auditando {site}")
        res = await dg.technical(site, allow_fetch=st.allow_web_fetch or transport is not None)
        if res.get("checked"):
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True, transport=transport) as c:
                    r = await c.get(site)
                res["checks"]["indexavel"] = "noindex" not in (r.headers.get("x-robots-tag", "") + r.text[:5000].lower())
            except httpx.HTTPError:
                res["checks"]["indexavel"] = None
            res["score"] = dg.tech_score(res)
        await sales._status(office, GEO, "idle", "auditoria da landing feita")
        missing = [k for k, v in (res.get("checks") or {}).items() if v is False]
        if missing:
            await office.alert("warning", GEO, f"Landing da Insighta: falta {', '.join(missing)}.")
    res["at"] = datetime.now(UTC).isoformat()
    office.content_audit = res
    return res


async def tick(office: Office, *, force: bool = False) -> dict[str, Any]:
    gov = await office.gov.snapshot()
    if not (force or (enabled(office) and gov["content_enabled"])):
        return {"skipped": "conteúdo desligado"}
    await seed()
    piece = await draft(office)
    aud = await audit(office)
    return {"rascunho": piece.title if piece else None, "auditoria": aud.get("checked")}


async def summary(office: Office) -> dict[str, Any]:
    async with session_scope() as s:
        rows = list((await s.execute(select(ContentPiece).order_by(ContentPiece.priority.desc(), ContentPiece.created_at))).scalars())
        counts = dict((await s.execute(select(ContentPiece.status, func.count()).group_by(ContentPiece.status))).all())
    gov = await office.gov.snapshot()
    return {
        "enabled": gov["content_enabled"], "counts": counts, "audit": getattr(office, "content_audit", None),
        "pieces": [{"id": p.id, "title": p.title, "slug": p.slug, "keyword": p.keyword, "cluster": p.cluster, "intent": p.intent, "status": p.status,
                    "flags": [x for x in p.review_notes.splitlines() if x], "updated_at": p.updated_at} for p in rows],
    }
