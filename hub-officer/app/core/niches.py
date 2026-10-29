"""Catálogo de nichos: onde a empresa atua, com fonte oficial, forma de ganhar dinheiro e avaliação.

Um nicho é bom para nós quando junta quatro coisas (CRITERIA). O catálogo abaixo é a avaliação
inicial; o fundador muda status e prioridade pelo painel, e o Conselho pode propor mudanças.

Rodízio: o CVO trabalha o nicho em foco; quando ele já tem hub publicado (e o rodízio está ligado),
passa para o próximo nicho ATIVO ainda sem hub, na ordem de prioridade.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import Hub, Niche

CRITERIA = [
    {"key": "volume", "label": "Volume", "question": "Muita gente procurando?"},
    {"key": "pagante", "label": "Alguém paga por cliente", "question": "Banco, faculdade ou corretora paga por lead ou cadastro aprovado?"},
    {"key": "dado_oficial", "label": "Dado oficial para conferir", "question": "Existe fonte oficial? É aqui que as IAs mais erram e onde ganhamos."},
    {"key": "risco", "label": "Risco legal", "question": "O risco legal é controlável? (baixo é melhor)"},
]

YMYL_RULES = (
    "Regras de saúde/finanças (YMYL): só dados verificáveis em fonte oficial, sem conselho individual, "
    "aviso \"não substitui orientação profissional\" e data de verificação em cada valor."
)

CATALOG: list[dict[str, Any]] = [
    {
        "slug": "financas-pessoais", "rank": 1, "name": "Finanças pessoais",
        "examples": "cartões, contas digitais, empréstimo pessoal e consignado, consórcio",
        "official_source": "Banco Central (taxas de juros por instituição, tarifas, CET)",
        "source_urls": ["https://www.bcb.gov.br/estatisticas/txjuros", "https://dadosabertos.bcb.gov.br"],
        "revenue": "Afiliado por conta ou cartão aprovado e leads",
        "assessment": "Melhor encaixe: muito volume, quem anuncia gasta muito e o dado oficial é público.",
        "scores": {"volume": "alto", "pagante": "alto", "dado_oficial": "alto", "risco": "médio"},
        "ymyl": True, "star": True,
    },
    {
        "slug": "planos-de-saude", "rank": 2, "name": "Planos de saúde e odontológicos",
        "examples": "preço por faixa etária, rede credenciada, reajuste, reclamações",
        "official_source": "ANS (dados abertos, índice de reclamações, IDSS)",
        "source_urls": ["https://dadosabertos.ans.gov.br", "https://www.gov.br/ans"],
        "revenue": "Leads para corretoras",
        "assessment": "Leads valiosos e dado oficial forte.",
        "scores": {"volume": "alto", "pagante": "alto", "dado_oficial": "alto", "risco": "médio"},
        "ymyl": True, "star": True,
    },
    {
        "slug": "educacao", "rank": 3, "name": "Educação",
        "examples": "faculdade EAD, pós-graduação, cursos técnicos",
        "official_source": "MEC/e-MEC (credenciamento) e INEP (notas ENADE, CPC, IGC)",
        "source_urls": ["https://emec.mec.gov.br", "https://www.gov.br/inep"],
        "revenue": "Leads de captação de alunos e afiliados",
        "assessment": "Muito volume, e faculdades pagam por aluno.",
        "scores": {"volume": "alto", "pagante": "alto", "dado_oficial": "alto", "risco": "baixo"},
        "ymyl": False, "star": True,
    },
    {
        "slug": "saude-mental", "rank": 4, "name": "Saúde mental",
        "examples": "plataformas de terapia online (B2C) e programas para empresas (NR-1, riscos psicossociais)",
        "official_source": "Registro do psicólogo no CRP/CFP e CNPJ da plataforma",
        "source_urls": ["https://cadastro.cfp.org.br"],
        "revenue": "Leads B2B (RH) e afiliados",
        "assessment": "Bom, com onda B2B: a NR-1 passou a exigir gestão de riscos psicossociais (confirmar prazos).",
        "scores": {"volume": "médio", "pagante": "médio", "dado_oficial": "médio", "risco": "médio"},
        "ymyl": True, "star": False,
    },
    {
        "slug": "emagrecimento-suplementos", "rank": 5, "name": "Emagrecimento e suplementos",
        "examples": "suplementos e produtos para emagrecer — só verificação de registro, composição e preço",
        "official_source": "ANVISA (consulta de registros e notificações)",
        "source_urls": ["https://consultas.anvisa.gov.br"],
        "revenue": "Afiliados só de produtos regularizados",
        "assessment": "Volume enorme, mas cheio de golpe e muito regulado. Só como verificador, nunca prometendo resultado.",
        "scores": {"volume": "alto", "pagante": "médio", "dado_oficial": "alto", "risco": "alto"},
        "ymyl": True, "star": False,
        "rules": "Nunca prometer resultado, perda de peso ou efeito; não recomendar medicamento; produto sem registro/notificação na ANVISA não entra.",
    },
    {
        "slug": "cursos-online", "rank": 6, "name": "Cursos online e infoprodutos",
        "examples": "preço, garantia, carga horária e política de reembolso",
        "official_source": "Página oficial do curso e da plataforma",
        "source_urls": ["https://hotmart.com", "https://www.eduzz.com", "https://kiwify.com.br"],
        "revenue": "Afiliados (Hotmart, Eduzz, Kiwify), comissões de 30–70% segundo agregadores",
        "assessment": "Rende, mas é saturado e mais difícil de verificar.",
        "scores": {"volume": "alto", "pagante": "alto", "dado_oficial": "baixo", "risco": "médio"},
        "ymyl": False, "star": False,
        "rules": "Só dados objetivos da página oficial (preço, garantia, carga horária, reembolso); nada de promessa de renda.",
    },
    {
        "slug": "tecnologia-b2b", "rank": 7, "name": "Tecnologia B2B",
        "examples": "ERPs para PMEs, softwares médicos, logística (TMS/WMS)",
        "official_source": "Sites oficiais dos fornecedores e Receita Federal (CNPJ)",
        "source_urls": ["https://brasilapi.com.br"],
        "revenue": "Leads de demonstração",
        "assessment": "Venda cara mas rara e lenta. Era o nicho antigo, agora fica em segundo plano.",
        "scores": {"volume": "baixo", "pagante": "alto", "dado_oficial": "médio", "risco": "baixo"},
        "ymyl": False, "star": False,
    },
    {
        "slug": "entretenimento", "rank": 8, "name": "Entretenimento",
        "examples": "streaming e assinaturas digitais (preço, catálogo, telas)",
        "official_source": "Sites oficiais dos serviços",
        "source_urls": [],
        "revenue": "Afiliados de comissão baixa",
        "assessment": "Muito volume, pouco dinheiro por clique.",
        "scores": {"volume": "alto", "pagante": "baixo", "dado_oficial": "baixo", "risco": "baixo"},
        "ymyl": False, "star": False,
    },
    {
        "slug": "apostas", "rank": 99, "name": "Apostas (bets)",
        "examples": "—", "official_source": "—", "source_urls": [], "revenue": "—",
        "assessment": "Fora: publicidade restrita e risco de reputação.",
        "scores": {"volume": "alto", "pagante": "alto", "dado_oficial": "baixo", "risco": "alto"},
        "ymyl": True, "star": False, "status": "bloqueado", "locked": True,
    },
]

STATUSES = ("ativo", "pausado", "bloqueado")


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


async def seed() -> int:
    """Cria no banco os nichos do catálogo que ainda não existem (não sobrescreve edições do fundador)."""
    added = 0
    async with session_scope() as s:
        have = set((await s.execute(select(Niche.slug))).scalars())
        for n in CATALOG:
            if n["slug"] in have:
                continue
            s.add(Niche(
                slug=n["slug"], rank=n["rank"], name=n["name"], examples=n["examples"], official_source=n["official_source"],
                source_urls=n["source_urls"], revenue=n["revenue"], assessment=n["assessment"], scores=n["scores"],
                ymyl=n["ymyl"], star=n["star"], rules=n.get("rules", ""), status=n.get("status", "ativo"), locked=n.get("locked", False),
            ))
            added += 1
    return added


async def all_niches() -> list[Niche]:
    async with session_scope() as s:
        return list((await s.execute(select(Niche).order_by(Niche.rank, Niche.name))).scalars())


def match(text: str | None, niches: list[Niche]) -> Niche | None:
    """Acha o nicho do catálogo por slug, nome ou começo do texto ("Finanças pessoais: cartões..." → finanças)."""
    if not text:
        return None
    t = slugify(text)
    for n in niches:
        if t == n.slug or t == slugify(n.name) or t.startswith(slugify(n.name)) or t.startswith(n.slug):
            return n
    return None


def label(n: Niche) -> str:
    return f"{n.name}: {n.examples}" if n.examples and n.examples != "—" else n.name


async def coverage() -> dict[str, dict[str, int]]:
    """Hubs por nicho: {slug: {total, published}}."""
    async with session_scope() as s:
        rows = (await s.execute(select(Hub.niche_slug, Hub.status))).all()
    out: dict[str, dict[str, int]] = {}
    for slug, status in rows:
        if not slug:
            continue
        c = out.setdefault(slug, {"total": 0, "published": 0})
        c["total"] += 1
        c["published"] += int(status == "published")
    return out


async def resolve_focus(focus: str, *, rotation: bool) -> Niche | None:
    """Nicho do próximo ciclo. Foco do fundador primeiro; com rodízio, pula nichos que já têm hub publicado."""
    niches = [n for n in await all_niches() if n.status == "ativo"]
    if not niches:
        return None
    cov = await coverage()
    chosen = match(focus, niches)
    if chosen and (not rotation or not cov.get(chosen.slug, {}).get("published")):
        return chosen
    if rotation:
        fresh = [n for n in niches if not cov.get(n.slug, {}).get("published")]
        if fresh:
            return fresh[0]
    return chosen or niches[0]


async def playbook() -> str:
    """Texto do mapa de nichos para os prompts (pesquisa de mercado, CVO, Conselho)."""
    lines = ["Mapa de nichos (Brasil). Critérios: " + " × ".join(c["label"] for c in CRITERIA) + "."]
    for n in await all_niches():
        if n.status == "bloqueado":
            lines.append(f"FORA DO MAPA: {n.name} — {n.assessment}")
            continue
        sc = ", ".join(f"{c['label'].lower()} {n.scores.get(c['key'], '?')}" for c in CRITERIA)
        lines.append(
            f"{n.rank}. {n.name} [{n.status}] — {n.examples}. Fonte oficial: {n.official_source}. "
            f"Receita: {n.revenue}. Avaliação: {sc}. {n.assessment}"
        )
    lines.append(YMYL_RULES)
    return "\n".join(lines)


async def rules_for(niche_text: str | None) -> str:
    """Regras extras do nicho (YMYL e específicas) para injetar nos prompts dos especialistas."""
    n = match(niche_text, await all_niches())
    if n is None:
        return ""
    parts = [f"Fonte oficial do nicho: {n.official_source} {' '.join(n.source_urls or [])}".strip()]
    if n.ymyl:
        parts.append(YMYL_RULES)
    if n.rules:
        parts.append(f"Regras do nicho: {n.rules}")
    return "\n".join(parts)


def niche_out(n: Niche, cov: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    c = (cov or {}).get(n.slug, {"total": 0, "published": 0})
    return {
        "slug": n.slug, "rank": n.rank, "name": n.name, "examples": n.examples, "official_source": n.official_source,
        "source_urls": n.source_urls, "revenue": n.revenue, "assessment": n.assessment, "scores": n.scores,
        "ymyl": n.ymyl, "star": n.star, "rules": n.rules, "status": n.status, "locked": n.locked,
        "hubs": c["total"], "hubs_published": c["published"],
    }
