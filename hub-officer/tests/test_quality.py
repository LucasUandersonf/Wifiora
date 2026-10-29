from __future__ import annotations

from app.agents.rubrics import run_rubric
from app.skills.builtin.jsonld import entity_jsonld, hub_dataset_jsonld, validate_jsonld
from app.skills.builtin.validation import check_entities, value_grounded


def test_grounding_detects_hallucinated_number():
    quote = "Plano Pro: R$ 189,00/mês com 3 usuários."
    assert value_grounded(189.0, quote)
    assert value_grounded(3, quote)
    assert not value_grounded(199.0, quote)


def test_check_entities_flags_missing_source():
    res = check_entities([{"name": "X", "attributes": {"preco": 10}, "sources": []}])
    assert res["critical"] >= 1 and res["grounding_ratio"] == 0


def test_extraction_rubric_blocks_low_grounding():
    out = {"entities": [{"name": "A", "sources": [{"url": "u"}]}], "validation": {"grounding_ratio": 0.5, "critical": 0, "warnings": 0}}
    _score, checks = run_rubric("data_extraction", out)
    assert any(c.blocking and not c.passed for c in checks)


def test_jsonld_graph_is_valid():
    e = entity_jsonld(name="ERP", schema_type="SoftwareApplication", attributes={"preco_mensal_brl": 10.0}, sources=[{"url": "https://a.b"}], template={"applicationCategory": "BusinessApplication"})
    assert validate_jsonld(e) == []
    g = hub_dataset_jsonld(hub={"slug": "s", "title": "T"}, entities=[e], base_url="https://x", brand="B")
    assert validate_jsonld(g) == []


def test_review_with_rating_is_rejected():
    doc = {"@context": "https://schema.org", "@type": "Product", "name": "X", "review": {"@type": "Review", "author": {"@id": "o"}, "reviewBody": "b", "reviewRating": {"@type": "Rating", "ratingValue": 5}}}
    assert any("reviewRating" in p for p in validate_jsonld(doc))


def test_criteria_are_objective():
    from app.skills.builtin.jsonld import evaluate_criteria

    res = evaluate_criteria(
        [{"label": "NF-e", "field": "emite_nfe", "op": "eq", "value": True}, {"label": "≤300", "field": "preco", "op": "lte", "value": 300}, {"label": "?", "field": "x", "op": "present"}],
        {"emite_nfe": True, "preco": 349.0},
    )
    assert [r["passed"] for r in res] == [True, False, None]


def test_cnpj_check_digits():
    from app.skills.builtin.web import valid_cnpj

    assert valid_cnpj("33000167000101") and not valid_cnpj("33000167000102") and not valid_cnpj("00000000000000")
