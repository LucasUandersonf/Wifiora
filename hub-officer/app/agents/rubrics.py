"""Rubricas determinísticas do Score Agent, por tipo de tarefa.

Cada check: (nome, aprovado, peso, bloqueante, detalhe). Um check bloqueante reprovado impede a
aprovação independentemente da nota do juiz LLM — é assim que garantimos "taxa zero de alucinação".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.skills.builtin.jsonld import validate_jsonld


@dataclass
class Check:
    name: str
    passed: bool
    weight: float = 1.0
    blocking: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _market_research(o: dict[str, Any]) -> list[Check]:
    cands = o.get("candidate_entities") or []
    return [
        Check("nicho_definido", bool(o.get("niche")), 1, True),
        Check("slug_hub", bool(o.get("hub_slug")), 1, True),
        Check("entidades_candidatas>=3", len(cands) >= 3, 2, True, f"{len(cands)} candidatas"),
        Check("consultas_alvo>=3", len(o.get("target_queries") or []) >= 3, 1.5),
        Check("dor_de_alucinacao_explicitada", bool(o.get("hallucination_pain")), 1),
        Check("sinais_de_monetizacao", bool(o.get("monetization_signals")), 0.5),
    ]


def _schema_design(o: dict[str, Any]) -> list[Check]:
    tpl = o.get("jsonld_template") or {}
    fields = o.get("fields") or []
    problems = (o.get("validation") or {}).get("problems", [])
    return [
        Check("template_schema_org", tpl.get("@context", "").startswith("http") and "schema.org" in tpl.get("@context", ""), 2, True),
        Check("tipo_definido", bool(tpl.get("@type") or o.get("entity_schema_type")), 1, True),
        Check("campos>=4", len(fields) >= 4, 1.5, False, f"{len(fields)} campos"),
        Check("campos_obrigatorios_marcados", any(f.get("required") for f in fields), 1),
        Check("amostra_jsonld_valida", not problems, 2, True, "; ".join(problems)),
        Check(
            "papeis_no_grafo",
            any(f.get("graph_role") in ("concept", "integrations", "feature") for f in fields),
            1,
            False,
            "campos precisam alimentar o grafo (concept/integrations/feature)",
        ),
        Check(
            "criterios_editoriais_objetivos",
            bool(o.get("review_criteria")) and all(c.get("field") in {f.get("name") for f in fields} for c in o.get("review_criteria") or []),
            1,
            False,
            "critérios precisam apontar para campos do schema",
        ),
    ]


def _data_extraction(o: dict[str, Any]) -> list[Check]:
    ents = o.get("entities") or []
    v = o.get("validation") or {}
    gr = float(v.get("grounding_ratio", 0))
    return [
        Check("entidades>=1", len(ents) >= 1, 2, True, f"{len(ents)} entidades"),
        Check("sem_problemas_criticos", v.get("critical", 1) == 0, 3, True, f"{v.get('critical')} críticos"),
        Check("grounding>=0.8", gr >= 0.8, 3, True, f"grounding={gr}"),
        Check("poucas_anomalias", v.get("warnings", 0) <= max(1, len(ents) // 2), 1),
        Check("todas_com_fonte", all(e.get("sources") for e in ents), 2, True),
    ]


def _frontend_page(o: dict[str, Any]) -> list[Check]:
    r = o.get("render") or {}
    page = o.get("page") or {}
    kb = r.get("html_bytes", 10**9) / 1024
    return [
        Check("jsonld_no_html", bool(r.get("has_jsonld")), 3, True),
        Check("grafo_sem_pontas_soltas", r.get("graph_dangling", ["?"]) == [], 2, True, ", ".join((r.get("graph_dangling") or [])[:3])),
        Check("dados_para_download", bool(r.get("has_downloads")), 1),
        Check("html<=100kb", kb <= 100, 2, True, f"{kb:.1f} KB"),
        Check("zero_scripts_terceiros", r.get("script_tags", 1) == 0, 1.5),
        Check("meta_description", bool(r.get("has_meta_description")), 1),
        Check("secoes_definidas", len(page.get("sections") or []) >= 3, 1),
        Check("faq_para_llms", len(page.get("faq") or []) >= 2, 1),
    ]


def _devops_check(o: dict[str, Any]) -> list[Check]:
    h = o.get("health") or {}
    return [
        Check("banco_ok", (h.get("database") or {}).get("ok", False), 2, True),
        Check("barramento_ok", (h.get("bus") or {}).get("ok", False), 2, True),
        Check("grafo_e_arquivos_ok", (o.get("data_distribution") or {}).get("ok", False), 1.5),
        Check("avaliacao_registrada", bool(o.get("assessment")), 0.5),
    ]


def _unit_economics(o: dict[str, Any]) -> list[Check]:
    m = o.get("metrics") or {}
    return [
        Check("metricas_calculadas", {"cash", "burn_per_day"} <= set(m), 2, True),
        Check("analise_presente", bool((o.get("analysis") or {}).get("assessment")), 1),
        Check("recomendacoes", bool((o.get("analysis") or {}).get("recommendations")), 1),
    ]


def _growth_plan(o: dict[str, Any]) -> list[Check]:
    ops = o.get("opportunities") or []
    return [
        Check("oportunidades>=2", len(ops) >= 2, 2, True, f"{len(ops)}"),
        Check("canal_e_estimativa", all(op.get("channel") and op.get("est_monthly_usd") is not None for op in ops), 1.5),
        Check("confianca_calibrada", all(0 <= float(op.get("confidence", 0.5)) <= 0.9 for op in ops), 1, False, "confiança > 0.9 é otimismo"),
    ]


def _signal_scan(o: dict[str, Any]) -> list[Check]:
    sig = o.get("signals") or []
    urls = [s.get("url", "") for s in sig]
    quiet = not sig and o.get("candidates", 0) == 0
    return [
        Check("varredura_executada", "candidates" in o, 1, True),
        Check("sinais_ou_semana_calma", bool(sig) or quiet, 1.5, False, f"{len(sig)} sinais de {o.get('candidates', 0)} candidatos"),
        Check("todo_sinal_com_url", all(u.startswith(("http://", "https://")) for u in urls), 3, True),
        Check("sem_duplicados", len(urls) == len(set(urls)), 1, True),
        Check("temas_classificados", all(s.get("topics") for s in sig), 1),
        Check("resumo_em_portugues", all(s.get("summary") for s in sig), 1),
    ]


def _wave_analysis(o: dict[str, Any]) -> list[Check]:
    from app.models import WAVE_STAGES

    waves = o.get("waves") or []
    return [
        Check("ondas_identificadas", bool(waves) or "notes" in o, 1.5, True),
        Check("toda_onda_com_evidencia", all(w.get("evidence") for w in waves), 3, True),
        Check("fase_valida", all(w.get("stage") in WAVE_STAGES for w in waves), 1, True),
        Check("relevancia_explicada", all(w.get("relevance_for_us") for w in waves), 1.5),
        Check("confianca_calibrada", all(w.get("confidence", 0) <= 0.95 for w in waves), 1),
        Check("sem_evidencia_inventada", o.get("dropped_evidence", 0) == 0, 1, False, f"{o.get('dropped_evidence', 0)} links descartados"),
    ]


def _positioning_plan(o: dict[str, Any]) -> list[Check]:
    plays = o.get("plays") or []
    return [
        Check("boletim_para_o_fundador", len(o.get("brief") or "") >= 80, 2, True),
        Check("acoes_propostas", bool(plays) or "Ainda não há ondas" in (o.get("brief") or "") or "Sem novidades" in (o.get("brief") or ""), 1.5),
        Check("primeiro_passo_concreto", all(p.get("first_step") for p in plays), 1.5),
        Check("gasto_sinalizado", all(p.get("requires_spend") == (p.get("est_cost_usd", 0) > 0) for p in plays), 1, True),
        Check("acoes_com_prazo", all(p.get("deadline_days") for p in plays), 0.5),
    ]


def _generic(o: dict[str, Any]) -> list[Check]:
    return [Check("saida_nao_vazia", bool(o), 1, True)]


RUBRICS: dict[str, Callable[[dict[str, Any]], list[Check]]] = {
    "market_research": _market_research,
    "schema_design": _schema_design,
    "data_extraction": _data_extraction,
    "frontend_page": _frontend_page,
    "devops_check": _devops_check,
    "unit_economics": _unit_economics,
    "growth_plan": _growth_plan,
    "signal_scan": _signal_scan,
    "wave_analysis": _wave_analysis,
    "positioning_plan": _positioning_plan,
}


def run_rubric(kind: str, output: dict[str, Any]) -> tuple[float, list[Check]]:
    checks = RUBRICS.get(kind, _generic)(output or {})
    total = sum(c.weight for c in checks) or 1.0
    score = sum(c.weight for c in checks if c.passed) / total
    return round(score, 4), checks


__all__ = ["RUBRICS", "Check", "run_rubric", "validate_jsonld"]
