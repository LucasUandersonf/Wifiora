"""Geração e validação de JSON-LD (Schema.org) — o coração do Hub Semântico.

Tipos produzidos: Dataset, ItemList, Product (+ SoftwareApplication), Offer, Organization (nossa e
dos fornecedores), Brand, Review (editorial, por critérios objetivos), BreadcrumbList, FAQPage, WebPage.

Regra editorial: a Review nunca traz nota/estrelas (reviewRating/AggregateRating). Ela lista apenas
critérios objetivos atendidos e não atendidos, calculados dos dados verificados — sem opinião inventada.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.skills.base import Skill

SCHEMA_CONTEXT = "https://schema.org"

# Propriedades mínimas por tipo (validação estrutural).
REQUIRED_PROPS: dict[str, tuple[str, ...]] = {
    "Dataset": ("name", "description", "dateModified", "creator", "license"),
    "SoftwareApplication": ("name", "applicationCategory"),
    "Product": ("name",),
    "Offer": ("price", "priceCurrency"),
    "Organization": ("name",),
    "Brand": ("name",),
    "TechArticle": ("headline", "dateModified"),
    "Review": ("author", "reviewBody"),
    "ItemList": ("itemListElement",),
    "BreadcrumbList": ("itemListElement",),
    "ListItem": ("position",),
    "FAQPage": ("mainEntity",),
    "Question": ("name", "acceptedAnswer"),
    "WebPage": ("name", "url"),
}

# Tipos que também recebem "Product" (para rich results de produto).
PRODUCT_LIKE = {"SoftwareApplication", "Product", "Service"}

_RESERVED_ATTRS = {"site_oficial", "url", "preco_mensal_brl", "price", "cnpj"}


def _iso(dt: datetime | None) -> str:
    return (dt or datetime.now(UTC)).isoformat()


def _types(node: dict[str, Any]) -> list[str]:
    t = node.get("@type")
    return [t] if isinstance(t, str) else list(t or [])


# --------------------------------------------------------------- critérios / review
def evaluate_criteria(criteria: list[dict[str, Any]], attributes: dict[str, Any]) -> list[dict[str, Any]]:
    """Avalia critérios objetivos sobre atributos verificados. Resultado None = dado ausente (não conta)."""
    results = []
    for c in criteria or []:
        field, op, target = c.get("field"), c.get("op", "eq"), c.get("value")
        value = attributes.get(field)
        passed: bool | None
        if value is None:
            passed = None
        elif op == "eq":
            passed = value == target
        elif op == "lte":
            passed = isinstance(value, (int, float)) and not isinstance(value, bool) and value <= float(target)
        elif op == "gte":
            passed = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= float(target)
        elif op == "contains":
            passed = str(target).lower() in str(value).lower()
        elif op == "present":
            passed = bool(value)
        else:
            passed = None
        results.append({"label": c.get("label") or field, "passed": passed})
    return results


def editorial_review(results: list[dict[str, Any]], *, org_id: str, date: datetime | None = None) -> dict[str, Any] | None:
    known = [r for r in results if r["passed"] is not None]
    if not known:
        return None
    pos = [r["label"] for r in known if r["passed"]]
    neg = [r["label"] for r in known if not r["passed"]]

    def notes(items: list[str]) -> dict[str, Any]:
        return {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n} for i, n in enumerate(items)]}

    review: dict[str, Any] = {
        "@type": "Review",
        "name": "Avaliação editorial por critérios verificados",
        "author": {"@id": org_id},
        "publisher": {"@id": org_id},
        "datePublished": _iso(date),
        "reviewBody": (
            f"Atende {len(pos)} de {len(known)} critérios objetivos verificados nas fontes oficiais. "
            "Avaliação baseada exclusivamente em dados públicos citados; não é opinião nem recomendação de compra."
        ),
    }
    if pos:
        review["positiveNotes"] = notes(pos)
    if neg:
        review["negativeNotes"] = notes(neg)
    return review


# ------------------------------------------------------------------ grafo de conhecimento
def _slug(text: str) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "item"


def concept_id(base: str, label: str) -> str:
    return f"{base.rstrip('/')}/conceitos#{_slug(label)}"


def concept_node(base: str, label: str, *, kind: str = "concept") -> dict[str, Any]:
    """Conceito compartilhado entre produtos e hubs (ex.: "Simples Nacional", "Integração com Pix")."""
    node: dict[str, Any] = {
        "@type": "DefinedTerm",
        "@id": concept_id(base, label),
        "name": label,
        "inDefinedTermSet": {"@id": f"{base.rstrip('/')}/conceitos#set"},
    }
    if kind == "integration":
        node["termCode"] = "integracao"
    return node


def term_set_node(base: str, brand: str) -> dict[str, Any]:
    return {"@type": "DefinedTermSet", "@id": f"{base.rstrip('/')}/conceitos#set", "name": f"Conceitos do {brand}", "url": f"{base.rstrip('/')}/conceitos"}


def org_slug(provider: dict[str, Any] | None, fallback_name: str | None = None) -> str | None:
    p = provider or {}
    name = p.get("nome_fantasia") or p.get("razao_social") or fallback_name
    return _slug(name) if name else None


def org_node(base: str, provider: dict[str, Any] | None, *, fallback_name: str | None = None, site: str | None = None) -> dict[str, Any] | None:
    """Empresa fornecedora como nó próprio, com página /empresa/<slug> e sameAs (site oficial, Wikidata)."""
    node = provider_node(provider, fallback_name=fallback_name, site=site)
    slug = org_slug(provider, fallback_name)
    if node is None or slug is None:
        return None
    page = f"{base.rstrip('/')}/empresa/{slug}"
    node["@id"] = page + "#org"
    node["mainEntityOfPage"] = page
    same = [u for u in [site, (f"https://www.wikidata.org/wiki/{provider['wikidata']}" if (provider or {}).get("wikidata") else None)] if u]
    if same:
        node["sameAs"] = same
    return node


def ref(node: dict[str, Any]) -> dict[str, str]:
    return {"@id": node["@id"]}


def graph_stats(doc: dict[str, Any]) -> dict[str, Any]:
    """Conta nós e arestas e acha pontas soltas (referências {"@id"} sem nó definido no documento)."""
    defined: set[str] = set()
    refs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        if "@id" in node and set(node) == {"@id"}:
            refs.append(node["@id"])
            return
        if "@id" in node and "@type" in node:
            defined.add(node["@id"])
        for k, v in node.items():
            if k != "@id":
                walk(v)

    walk(doc)
    dangling = sorted({r for r in refs if r not in defined})
    return {"nodes": len(defined), "edges": len(refs), "dangling": dangling}


# ------------------------------------------------------------------ nós básicos
def provider_node(provider: dict[str, Any] | None, *, fallback_name: str | None = None, site: str | None = None) -> dict[str, Any] | None:
    p = provider or {}
    name = p.get("nome_fantasia") or p.get("razao_social") or fallback_name
    if not name:
        return None
    node: dict[str, Any] = {"@type": "Organization", "name": name}
    if p.get("razao_social"):
        node["legalName"] = p["razao_social"]
    if p.get("cnpj"):
        node["taxID"] = p["cnpj"]
        node["identifier"] = {"@type": "PropertyValue", "propertyID": "CNPJ", "value": p["cnpj"]}
    if site:
        node["url"] = site
    if p.get("municipio") or p.get("uf"):
        node["address"] = {"@type": "PostalAddress", "addressLocality": p.get("municipio"), "addressRegion": p.get("uf"), "addressCountry": "BR"}
    return node


def breadcrumb(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)],
    }


def entity_jsonld(
    *,
    name: str,
    schema_type: str,
    attributes: dict[str, Any],
    sources: list[dict[str, Any]],
    template: dict[str, Any] | None = None,
    url: str | None = None,
    date_modified: datetime | None = None,
    provider: dict[str, Any] | None = None,
    category: str | None = None,
    review: dict[str, Any] | None = None,
    with_context: bool = True,
    manufacturer: dict[str, Any] | None = None,
    features: list[str] | None = None,
    keywords: list[dict[str, Any]] | None = None,
    related: list[dict[str, Any]] | None = None,
    similar: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produto. Com `manufacturer`/`keywords`/`related`/`similar` (referências {"@id"}), vira nó de um grafo
    conectado; sem eles, sai autocontido (fornecedor aninhado)."""
    types = [schema_type] + (["Product"] if schema_type in PRODUCT_LIKE and schema_type != "Product" else [])
    doc: dict[str, Any] = {**({"@context": SCHEMA_CONTEXT} if with_context else {}), **(template or {})}
    doc["@type"] = types if len(types) > 1 else types[0]
    doc["name"] = name
    if "SoftwareApplication" in types:
        doc.setdefault("applicationCategory", "BusinessApplication")
    if url:
        doc["@id"] = url + "#product"
        doc["url"] = url
        doc["mainEntityOfPage"] = url
    if category:
        doc["category"] = category
    site = attributes.get("site_oficial") or attributes.get("url")
    if site:
        doc["sameAs"] = [site]
    org = provider_node(provider, site=site)
    if org:
        doc["brand"] = {"@type": "Brand", "name": org["name"]}
        doc["manufacturer"] = manufacturer or org
        if "SoftwareApplication" in types:
            doc["provider"] = manufacturer or org
    if features:
        doc["featureList"] = features
    if keywords:
        doc["keywords"] = keywords
    if related:
        doc["isRelatedTo"] = related
    if similar:
        doc["isSimilarTo"] = similar
    price = attributes.get("preco_mensal_brl", attributes.get("price"))
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        price_src = next((s.get("url") for s in sources if s.get("url")), None)
        doc["offers"] = {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "BRL",
            "priceSpecification": {"@type": "UnitPriceSpecification", "price": price, "priceCurrency": "BRL", "unitText": "MONTH"},
            **({"url": price_src} if price_src else {}),
        }
    doc["additionalProperty"] = [
        {"@type": "PropertyValue", "name": k, "value": v} for k, v in attributes.items() if k not in _RESERVED_ATTRS and v is not None
    ]
    if sources:
        doc["citation"] = [{"@type": "CreativeWork", "url": s.get("url")} for s in sources if s.get("url")]
        doc["isBasedOn"] = [s.get("url") for s in sources if s.get("url")]
    if review:
        doc["review"] = review
    doc["dateModified"] = _iso(date_modified)
    return doc


def hub_dataset_jsonld(
    *,
    hub: dict[str, Any],
    entities: list[dict[str, Any]],
    base_url: str,
    brand: str,
    date_modified: datetime | None = None,
    faq: list[dict[str, str]] | None = None,
    keywords: list[str] | None = None,
    temporal_start: datetime | None = None,
    version: int | None = None,
    extra_nodes: list[dict[str, Any]] | None = None,
    distributions: list[dict[str, Any]] | None = None,
    about: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grafo da página do hub: Organization + WebSite + WebPage + Dataset(ItemList de produtos) + empresas
    + conceitos + Breadcrumb + FAQ. `extra_nodes` fecha as referências (empresas, conceitos)."""
    base = base_url.rstrip("/")
    hub_url = f"{base}/hub/{hub['slug']}"
    org = {"@type": "Organization", "@id": f"{base}/#org", "name": brand, "url": base + "/"}
    dataset: dict[str, Any] = {
        "@type": "Dataset",
        "@id": f"{hub_url}#dataset",
        "name": hub["title"],
        "description": hub.get("description") or hub["title"],
        "url": hub_url,
        "inLanguage": "pt-BR",
        "spatialCoverage": {"@type": "Country", "name": "Brasil"},
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "creator": {"@id": org["@id"]},
        "publisher": {"@id": org["@id"]},
        "dateModified": _iso(date_modified),
        "measurementTechnique": "Extração de fontes oficiais com verificação literal de cada valor (grounding) e controle de qualidade antes da publicação.",
        "variableMeasured": [f for f in hub.get("fields", []) if f],
        "distribution": distributions or [
            {"@type": "DataDownload", "encodingFormat": "application/ld+json", "contentUrl": f"{hub_url}/data.jsonld"},
            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{base}/api/public/hubs/{hub['slug']}"},
        ],
        "includedInDataCatalog": {"@id": f"{base}/data/catalog.jsonld#catalog"},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(entities),
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": e} for i, e in enumerate(entities)],
        },
    }
    if keywords:
        dataset["keywords"] = keywords[:20]
    if temporal_start:
        dataset["temporalCoverage"] = f"{temporal_start.date().isoformat()}/.."
    if version:
        dataset["version"] = str(version)
    if about:
        dataset["about"] = about
    graph: list[dict[str, Any]] = [
        org,
        website_node(base, brand),
        {"@type": "DataCatalog", "@id": f"{base}/data/catalog.jsonld#catalog", "name": f"Dados abertos do {brand}", "url": f"{base}/dados"},
        {"@type": "WebPage", "@id": hub_url, "url": hub_url, "name": hub["title"], "inLanguage": "pt-BR", "isPartOf": {"@id": f"{base}/#website"}, "mainEntity": {"@id": dataset["@id"]}},
        dataset,
        breadcrumb([("Início", base + "/"), ("Hubs", f"{base}/hubs"), (hub["title"], hub_url)]),
    ]
    if faq:
        graph.append(
            {
                "@type": "FAQPage",
                "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq if f.get("q") and f.get("a")],
            }
        )
    graph.extend(extra_nodes or [])
    return {"@context": SCHEMA_CONTEXT, "@graph": graph}


def website_node(base: str, brand: str) -> dict[str, Any]:
    return {"@type": "WebSite", "@id": f"{base.rstrip('/')}/#website", "name": brand, "url": base.rstrip("/") + "/", "inLanguage": "pt-BR", "publisher": {"@id": f"{base.rstrip('/')}/#org"}}


def entity_page_jsonld(
    *,
    entity: dict[str, Any],
    hub: dict[str, Any],
    base_url: str,
    brand: str,
    reviewed_by: str | None = None,
    last_reviewed: datetime | None = None,
    extra_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    hub_url = f"{base}/hub/{hub['slug']}"
    url = entity.get("url") or hub_url
    page: dict[str, Any] = {"@type": "WebPage", "@id": url, "url": url, "name": entity.get("name", ""), "inLanguage": "pt-BR", "mainEntity": {"@id": entity.get("@id")}}
    if reviewed_by and last_reviewed:
        page["reviewedBy"] = {"@type": "Person", "name": reviewed_by}
        page["lastReviewed"] = _iso(last_reviewed)
    node = {k: v for k, v in entity.items() if k != "@context"}
    return {
        "@context": SCHEMA_CONTEXT,
        "@graph": [
            {"@type": "Organization", "@id": f"{base}/#org", "name": brand, "url": base + "/"},
            page,
            node,
            breadcrumb([("Início", base + "/"), ("Hubs", f"{base}/hubs"), (hub["title"], hub_url), (entity.get("name", ""), url)]),
            *(extra_nodes or []),
        ],
    }


# ------------------------------------------------------------------ validação
def validate_jsonld(doc: dict[str, Any], *, check_refs: bool = True) -> list[str]:
    """Percorre o grafo inteiro (inclusive nós aninhados). Lista vazia = válido."""
    problems: list[str] = []
    if doc.get("@context") not in ("https://schema.org", "http://schema.org", "https://schema.org/"):
        problems.append("@context ausente ou diferente de https://schema.org")

    def walk(node: Any, path: str, parent_types: list[str]) -> None:
        if isinstance(node, list):
            for i, n in enumerate(node):
                walk(n, f"{path}[{i}]", parent_types)
            return
        if not isinstance(node, dict):
            return
        types = _types(node)
        is_ref = set(node) <= {"@id"}
        if not types and not is_ref and path != "$" and "@graph" not in node and parent_types == ["@graph"]:
            problems.append(f"{path}: nó sem @type")
        for t in types:
            for prop in REQUIRED_PROPS.get(t, ()):
                if node.get(prop) in (None, "", []):
                    problems.append(f"{path} ({t}): propriedade obrigatória ausente '{prop}'")
            if t == "Review" and "reviewRating" in node:
                problems.append(f"{path}: Review editorial não pode trazer reviewRating (nota inventada)")
        for k, v in node.items():
            if k.startswith("@") and k != "@graph":
                continue
            walk(v, f"{path}.{k}", ["@graph"] if k == "@graph" else types)

    walk(doc, "$", [])
    if check_refs:
        dangling = graph_stats(doc)["dangling"]
        if dangling:
            problems.append(f"pontas soltas no grafo (referência sem nó): {dangling[:5]}")
    return problems


class JsonLdGeneratorSkill(Skill):
    name = "jsonld_generator"
    description = "Gera JSON-LD Schema.org (Product/SoftwareApplication, Offer, Organization, Review editorial) para uma entidade."
    sectors = ("research", "tech")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        doc = entity_jsonld(**kwargs)
        return {"jsonld": doc, "problems": validate_jsonld(doc)}


class JsonLdValidatorSkill(Skill):
    name = "jsonld_validator"
    description = "Valida JSON-LD: contexto, @type e propriedades mínimas em todos os nós do grafo."

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        problems = validate_jsonld(kwargs["doc"])
        return {"valid": not problems, "problems": problems}
