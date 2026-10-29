"""Validação anti-alucinação: grounding (todo valor precisa estar na evidência) + detecção de anomalias."""

from __future__ import annotations

import re
import statistics
from typing import Any

from app.skills.base import Skill


def _number_variants(v: float) -> set[str]:
    """Formas textuais plausíveis de um número em páginas brasileiras (189, 189,00, 189.00, 1.890,00...)."""
    out = {str(v)}
    if float(v).is_integer():
        i = int(v)
        out |= {str(i), f"{i:,}".replace(",", "."), f"{i},00", f"{i}.00"}
    out |= {f"{v:.2f}", f"{v:.2f}".replace(".", ","), f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")}
    return out


def value_grounded(value: Any, evidence: str) -> bool:
    ev = evidence.lower()
    if isinstance(value, bool):
        return True  # booleanos são julgados pelo Score Agent/curadoria (não verificáveis por substring)
    if isinstance(value, (int, float)):
        return any(var in evidence for var in _number_variants(float(value)))
    if isinstance(value, list):
        return all(value_grounded(v, evidence) for v in value) if value else True
    if isinstance(value, str):
        if value.startswith("http"):
            return True  # URL de origem — conferida pela presença em `sources`
        tokens = [t for t in re.split(r"[,;/]\s*", value.lower()) if t.strip()]
        return all(t.strip() in ev for t in tokens) if tokens else True
    return True


def check_entities(entities: list[dict[str, Any]], required_fields: list[str] | None = None) -> dict[str, Any]:
    required_fields = required_fields or []
    issues: list[dict[str, Any]] = []
    per_entity: list[dict[str, Any]] = []
    total_vals = grounded_vals = 0

    for e in entities:
        name = e.get("name", "?")
        attrs: dict[str, Any] = e.get("attributes") or {}
        sources = e.get("sources") or []
        evidence = " ".join(str(s.get("quote", "")) + " " + str(s.get("text", "")) for s in sources)
        e_total = e_ok = 0
        if not sources or not any(s.get("url") for s in sources):
            issues.append({"entity": name, "severity": "critical", "issue": "sem fonte citável (url)"})
        for f in required_fields:
            if attrs.get(f) is None:
                issues.append({"entity": name, "severity": "warning", "issue": f"campo obrigatório ausente: {f}"})
        for k, v in attrs.items():
            if v is None:
                continue
            e_total += 1
            if k == "cnpj":
                grounded = bool(sources) and re.sub(r"\D", "", str(v)) in re.sub(r"\D", "", evidence)
            else:
                grounded = bool(sources) and value_grounded(v, evidence)
            if grounded:
                e_ok += 1
            else:
                issues.append({"entity": name, "severity": "critical", "issue": f"valor não encontrado na evidência: {k}={v!r}"})
        total_vals += e_total
        grounded_vals += e_ok
        per_entity.append({"name": name, "grounding_ratio": round(e_ok / e_total, 3) if e_total else 0.0})

    # anomalias numéricas: valores muito distantes da mediana do nicho
    numeric_fields = {k for e in entities for k, v in (e.get("attributes") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for f in numeric_fields:
        vals = [(e.get("name"), float(e["attributes"][f])) for e in entities if isinstance((e.get("attributes") or {}).get(f), (int, float))]
        if len(vals) < 3:
            continue
        med = statistics.median(v for _, v in vals)
        for name, v in vals:
            if med > 0 and (v < med * 0.2 or v > med * 5):
                issues.append({"entity": name, "severity": "warning", "issue": f"anomalia em {f}: {v} vs mediana {med}"})

    return {
        "grounding_ratio": round(grounded_vals / total_vals, 3) if total_vals else 0.0,
        "critical": sum(1 for i in issues if i["severity"] == "critical"),
        "warnings": sum(1 for i in issues if i["severity"] == "warning"),
        "issues": issues,
        "per_entity": per_entity,
    }


class DataValidatorSkill(Skill):
    name = "data_validator"
    description = "Calcula grounding ratio (valores presentes na evidência citada) e detecta anomalias numéricas."
    sectors = ("research", "quality")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        return check_entities(kwargs.get("entities", []), kwargs.get("required_fields"))
