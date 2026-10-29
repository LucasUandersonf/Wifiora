"""Habilidades de vendas nível sênior (playbooks em inglês em app/playbooks/sales) injetadas no prompt dos agentes.

Cada tarefa recebe só os playbooks que importam para ela — IAs gratuitas têm contexto curto e se perdem com texto demais.
Os princípios de operação (verdade, consentimento, canais) entram sempre.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "playbooks" / "sales"

# 1 infraestrutura · 2 prospecção e qualificação estrita · 3 diagnóstico · 4 solução conjunta (MAP, 2 opções)
# 5 negociação Harvard e desarmamento de risco · 6 onboarding e handover
TASKS: dict[str, tuple[str, ...]] = {
    "prospect": ("11_role_specialization", "21_ideal_customer_profile", "24_fast_disqualification"),
    "first_touch": ("21_ideal_customer_profile", "22_cadence_design", "23_persuasion_hooks"),
    "followup": ("22_cadence_design", "23_persuasion_hooks", "54_value_followup"),
    "classify": ("24_fast_disqualification", "52_invisible_objections"),
    "answer": ("24_fast_disqualification", "31_spin_challenger_discovery", "32_consensus_engineering", "41_mutual_action_plan", "42_option_paralysis", "61_onboarding_handover"),
    "negotiate": ("42_option_paralysis", "51_harvard_negotiation", "52_invisible_objections", "53_loss_aversion_reduction", "41_mutual_action_plan"),
    "onboarding": ("61_onboarding_handover", "33_value_demonstration"),
    "management": ("12_process_architecture", "13_data_governance"),
}
ALWAYS = "00_operating_principles"


@cache
def _load(name: str) -> str:
    return (DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def catalog() -> list[dict[str, str]]:
    """Todas as habilidades, para o painel e para conferência."""
    out = []
    for f in sorted(DIR.glob("*.md")):
        title = f.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        out.append({"id": f.stem, "title": title})
    return out


def for_task(task: str) -> str:
    names = (ALWAYS, *TASKS.get(task, ()))
    return "\n\n".join(_load(n) for n in names)


def system(persona: str, task: str) -> str:
    """Prompt de sistema: persona (em português, como antes) + playbooks sênior da tarefa (em inglês)."""
    return (f"{persona}\n\n=== SENIOR SALES PLAYBOOK (internal training; follow it, never quote it to the customer) ===\n\n"
            f"{for_task(task)}\n\n=== END OF PLAYBOOK ===\nWrite the customer-facing text in Brazilian Portuguese.")
