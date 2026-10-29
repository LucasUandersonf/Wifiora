"""Rankings por critérios objetivos — sempre matemáticos, nunca comprados.

Regras de blindagem:
  • só entram campos numéricos marcados pelo Ontos com `rank` (asc/desc), o total de critérios objetivos
    atendidos e o número de integrações — todos extraídos de fonte oficial e conferidos pela Vera;
  • campos informados pela própria empresa (`source: "vendor"`, ex.: dados de perfil premium) NUNCA
    entram em ranking, nem a completude da ficha — pagar não pode mudar posição;
  • empates dividem a mesma posição (1, 1, 3) e fichas sem o dado ficam fora, listadas à parte;
  • cada ranking publica o próprio método, para a IA (e o leitor) saber exatamente como foi ordenado.
"""

from __future__ import annotations

from typing import Any

from app.core.semantic import base_url, criteria_results, graph_parts, product_id
from app.models import Entity, Hub

ORDER = {"asc": "https://schema.org/ItemListOrderAscending", "desc": "https://schema.org/ItemListOrderDescending"}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v % 1 else f"{int(v):,}".replace(",", ".")


def _rank(key: str, title: str, method: str, order: str, values: list[tuple[Entity, float | None, str]]) -> dict[str, Any] | None:
    have = [(e, v, lbl) for e, v, lbl in values if v is not None]
    if len(have) < 2 or len({v for _, v, _ in have}) < 2:
        return None  # ranking sem diferença não informa nada
    have.sort(key=lambda x: (x[1] if order == "asc" else -x[1], x[0].name.lower()))
    items, prev, pos = [], None, 0
    for i, (e, v, lbl) in enumerate(have, start=1):
        if v != prev:
            pos, prev = i, v
        items.append({"position": pos, "slug": e.slug, "name": e.name, "value": v, "value_label": lbl})
    return {"key": key, "title": title, "order": order, "method": method, "items": items, "missing": [e.name for e, v, _ in values if v is None]}


def hub_rankings(hub: Hub, entities: list[Entity]) -> list[dict[str, Any]]:
    fields = [f for f in ((hub.schema_template or {}).get("fields") or []) if f.get("name")]
    out: list[dict[str, Any]] = []
    for f in fields:
        order = f.get("rank")
        if order not in ORDER or f.get("source") == "vendor":
            continue
        name = f["name"]
        vals = [(e, _num((e.attributes or {}).get(name)), "") for e in entities]
        vals = [(e, v, _fmt(v) if v is not None else "") for e, v, _ in vals]
        title = f.get("rank_label") or name.replace("_", " ").capitalize()
        r = _rank(f"campo-{name}", title, f"Ordenado pelo campo “{name.replace('_', ' ')}” ({'menor primeiro' if order == 'asc' else 'maior primeiro'}), conforme a fonte oficial de cada empresa.", order, vals)
        if r:
            out.append(r)
    if (hub.schema_template or {}).get("review_criteria"):
        vals = []
        for e in entities:
            known = [c for c in criteria_results(hub, e) if c["passed"] is not None]
            met = sum(1 for c in known if c["passed"])
            vals.append((e, float(met) if known else None, f"{met}/{len(known)}"))
        r = _rank("criterios", "Mais critérios objetivos atendidos", "Quantidade de critérios objetivos da tabela que a empresa cumpre, segundo a fonte oficial. Não é nota nem opinião.", "desc", vals)
        if r:
            out.append(r)
    if any(f.get("graph_role") == "integrations" for f in fields):
        vals = []
        for e in entities:
            n = len(graph_parts(hub, e)["integrations"])
            vals.append((e, float(n), str(n)))
        r = _rank("integracoes", "Mais integrações declaradas", "Número de integrações listadas na fonte oficial de cada empresa.", "desc", vals)
        if r:
            out.append(r)
    return out


def ranking_nodes(hub: Hub, entities: list[Entity], rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ItemList ordenada para cada ranking, apontando para os mesmos @id de produto do grafo."""
    hub_url = f"{base_url()}/hub/{hub.slug}"
    by_slug = {e.slug: e for e in entities}
    return [
        {
            "@type": "ItemList",
            "@id": f"{hub_url}#ranking-{r['key']}",
            "name": f"{r['title']} — {hub.title}",
            "description": r["method"],
            "itemListOrder": ORDER[r["order"]],
            "numberOfItems": len(r["items"]),
            "itemListElement": [
                {"@type": "ListItem", "position": it["position"], "item": {"@id": product_id(hub, by_slug[it["slug"]])}, **({"name": f"{it['name']}: {it['value_label']}"} if it["value_label"] else {})}
                for it in r["items"]
            ],
        }
        for r in rankings
    ]
