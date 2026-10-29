"""Coleta web responsável: respeita robots.txt, identifica o User-Agent e limita o tamanho."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.skills.base import Skill, SkillError

USER_AGENT = "GeoOfficeBot/0.1 (+hub semantico; coleta de dados publicos)"
MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 40_000


async def _allowed_by_robots(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = await client.get(robots_url, timeout=8)
    except httpx.HTTPError:
        return True  # sem robots acessível -> permitido
    if r.status_code >= 400:
        return True
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:MAX_TEXT_CHARS]


class WebFetchSkill(Skill):
    name = "web_fetch"
    description = "Baixa uma página pública (respeitando robots.txt) e retorna o texto visível."
    sectors = ("research",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        url: str = kwargs["url"]
        if self.office and not self.office.settings.allow_web_fetch:
            raise SkillError("web_fetch desativado (ALLOW_WEB_FETCH=false)")
        if urlparse(url).scheme not in ("http", "https"):
            raise SkillError(f"URL inválida: {url}")
        if urlparse(url).hostname and urlparse(url).hostname.endswith(".invalid"):
            raise SkillError("domínio de demonstração (.invalid) — sem coleta real")
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            if not await _allowed_by_robots(client, url):
                raise SkillError(f"bloqueado por robots.txt: {url}")
            r = await client.get(url, timeout=20)
            if r.status_code >= 400:
                raise SkillError(f"HTTP {r.status_code} em {url}")
            content = r.content[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
        text = html_to_text(content) if "html" in r.headers.get("content-type", "html") else content[:MAX_TEXT_CHARS]
        return {"url": str(r.url), "status": r.status_code, "text": text, "chars": len(text)}


class MultiFetchSkill(Skill):
    name = "web_fetch_many"
    description = "Baixa várias páginas em paralelo (com limite de concorrência); falhas são reportadas, não lançadas."
    sectors = ("research",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        urls: list[str] = kwargs["urls"]
        sem = asyncio.Semaphore(int(kwargs.get("concurrency", 4)))
        single = WebFetchSkill(self.office)

        async def one(u: str) -> dict[str, Any]:
            async with sem:
                try:
                    return await single.run(url=u)
                except Exception as e:
                    return {"url": u, "error": str(e)}

        results = await asyncio.gather(*(one(u) for u in urls))
        return {"pages": results}


def only_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def valid_cnpj(cnpj: str) -> bool:
    """Confere os dígitos verificadores do CNPJ (barra CNPJ alucinado/digitado errado)."""
    if len(cnpj) != 14 or len(set(cnpj)) == 1 or not cnpj.isdigit():
        return False

    def dv(base: str) -> str:
        weights = list(range(len(base) - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(int(d) * w for d, w in zip(base, weights[-len(base):], strict=True))
        r = total % 11
        return "0" if r < 2 else str(11 - r)

    return cnpj[12] == dv(cnpj[:12]) and cnpj[13] == dv(cnpj[:13])


class CnpjLookupSkill(Skill):
    name = "cnpj_lookup"
    description = "Consulta dados cadastrais públicos de um CNPJ (BrasilAPI)."
    sectors = ("research",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        cnpj = only_digits(kwargs["cnpj"])
        if not valid_cnpj(cnpj):
            raise SkillError("CNPJ inválido (dígitos verificadores)")
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}", timeout=15)
        if r.status_code != 200:
            raise SkillError(f"BrasilAPI HTTP {r.status_code}")
        d = r.json()
        return {
            "cnpj": cnpj,
            "razao_social": d.get("razao_social"),
            "nome_fantasia": d.get("nome_fantasia"),
            "situacao": d.get("descricao_situacao_cadastral"),
            "cnae": d.get("cnae_fiscal_descricao"),
            "uf": d.get("uf"),
            "municipio": d.get("municipio"),
        }


def format_cnpj(cnpj: str) -> str:
    d = only_digits(cnpj)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def parse_wikidata_cnpj(result: dict) -> str | None:
    """Só aceita correspondência única e exata; ambiguidade = sem vínculo (nunca chuta)."""
    items = {b["item"]["value"].rsplit("/", 1)[-1] for b in result.get("results", {}).get("bindings", []) if b.get("item")}
    return items.pop() if len(items) == 1 else None


class WikidataByCnpjSkill(Skill):
    name = "wikidata_by_cnpj"
    description = "Encontra a empresa no Wikidata pelo CNPJ exato (propriedade P6204) para ligar o grafo ao grafo público."
    sectors = ("research",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        cnpj = only_digits(kwargs["cnpj"])
        if not valid_cnpj(cnpj):
            raise SkillError("CNPJ inválido")
        query = (
            'SELECT ?item WHERE { VALUES ?c { "%s" "%s" } ?item wdt:P6204 ?c . } LIMIT 3' % (cnpj, format_cnpj(cnpj))
        )
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}, timeout=20) as c:
            r = await c.get("https://query.wikidata.org/sparql", params={"query": query, "format": "json"})
        if r.status_code != 200:
            raise SkillError(f"Wikidata HTTP {r.status_code}")
        qid = parse_wikidata_cnpj(r.json())
        return {"cnpj": cnpj, "wikidata": qid}
