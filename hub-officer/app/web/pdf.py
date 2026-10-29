"""PDF comercial do Diagnóstico / Rastreador de IA (reportlab, puro Python — sem navegador no servidor)."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.diagnosis import TECH_CHECKS
from app.core.engines import LABELS
from app.models import Diagnosis

ACCENT = colors.HexColor("#0b6bcb")
MUTED = colors.HexColor("#5b6270")
LINE = colors.HexColor("#e3e6ea")
OK = colors.HexColor("#0f7a4f")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Title"], fontSize=20, leading=24, alignment=TA_LEFT, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, leading=16, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1a1d23")),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontSize=9.5, leading=13),
        "muted": ParagraphStyle("muted", parent=base["BodyText"], fontSize=8.5, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=8, leading=10),
        "big": ParagraphStyle("big", parent=base["BodyText"], fontSize=22, leading=26, textColor=ACCENT),
    }


def _esc(v: Any) -> str:
    return str(v if v is not None else "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(data: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def render(d: Diagnosis, *, agency: str) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Visibilidade em IA — {d.brand}", author=agency)
    width = A4[0] - 32 * mm
    vis = d.visibility or {}
    names = [d.brand] + [c["name"] for c in d.competitors or []]
    share = vis.get("share") or {}
    by_engine: dict[str, dict[str, float]] = vis.get("by_engine") or {}
    engines = vis.get("engines") or list(by_engine)
    s: list[Any] = [
        Paragraph(f"{_esc(agency)} · Relatório de Visibilidade em IA · {d.created_at:%d/%m/%Y}", st["muted"]),
        Paragraph(f"{_esc(d.brand)}: como as IAs recomendam você", st["h1"]),
        Paragraph(f"Segmento: {_esc(d.category)}{' · ' + _esc(d.city) if d.city else ''}{' · ' + _esc(d.site) if d.site else ''}", st["muted"]),
        Spacer(1, 6),
    ]
    sc = d.scores or {}
    kpi = [[Paragraph("Nota geral", st["muted"]), Paragraph("Recomendado pelas IAs", st["muted"]), Paragraph("Prontidão técnica", st["muted"])],
           [Paragraph(f"{sc.get('overall', '—')}/100", st["big"]), Paragraph(f"{sc.get('visibility', '—')}%", st["big"]),
            Paragraph(f"{sc['technical']}%" if sc.get("technical") is not None else "—", st["big"])],
           [Paragraph(_esc(sc.get("grade", "")), st["muted"]), Paragraph(f"{len(d.queries or [])} perguntas × {len(engines)} IA(s)", st["muted"]),
            Paragraph("site verificado" if (d.technical or {}).get("checked") else "não verificado", st["muted"])]]
    k = Table(kpi, colWidths=[width / 3] * 3)
    k.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    s.append(k)
    if (d.plan or {}).get("summary"):
        s += [Spacer(1, 6), Paragraph(f"<b>Resumo:</b> {_esc(d.plan['summary'])}", st["p"])]

    # ranking geral e por IA
    s.append(Paragraph("Quem as IAs recomendam no seu segmento", st["h2"]))
    head = ["Marca", "Geral"] + ([LABELS.get(e, e) for e in engines] if len(engines) > 1 else [])
    rows = [head]
    for n in sorted(names, key=lambda x: -share.get(x, 0)):
        rows.append([Paragraph(("<b>%s</b> (você)" % _esc(n)) if n == d.brand else _esc(n), st["cell"]), f"{round(100 * share.get(n, 0))}%"]
                    + ([f"{round(100 * (by_engine.get(e) or {}).get(n, 0))}%" for e in engines] if len(engines) > 1 else []))
    first = width * 0.4
    s.append(_table(rows, [first] + [(width - first) / (len(head) - 1)] * (len(head) - 1)))

    # pergunta por pergunta
    s.append(Paragraph("Pergunta por pergunta", st["h2"]))
    s.append(Paragraph("✓ = a IA citou a marca na resposta (em pelo menos uma das IAs consultadas).".replace("✓", "x"), st["muted"]))
    mat = [["Pergunta"] + [Paragraph(_esc(n), st["cell"]) for n in names]]
    for r in vis.get("rows") or []:
        mat.append([Paragraph(_esc(r["query"]), st["cell"])] + [("x" if n in r["mentioned"] else "–") for n in names])
    qw = width * 0.5
    t = _table(mat, [qw] + [(width - qw) / len(names)] * len(names))
    t.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "CENTER"), ("TEXTCOLOR", (1, 1), (-1, -1), OK)]))
    s.append(t)
    gaps, open_q = vis.get("gaps") or [], vis.get("open") or []
    s.append(Paragraph(f"<b>Lacunas</b> (concorrente aparece, você não): {len(gaps)} · <b>Terreno livre</b> (ninguém citado): {len(open_q)}", st["p"]))

    # técnico
    tech = d.technical or {}
    s.append(Paragraph("Seu site está pronto para as IAs?", st["h2"]))
    if tech.get("checked"):
        s.append(_table([["Item", "Situação"]] + [[label, "ok" if tech["checks"].get(key) else "falta"] for key, label, _ in TECH_CHECKS], [width * 0.75, width * 0.25]))
    else:
        s.append(Paragraph(f"Não verificado: {_esc(tech.get('reason'))}.", st["muted"]))

    # plano
    plan = d.plan or {}
    s.append(Paragraph("Plano de ação", st["h2"]))
    for title, key in (("Ganhos rápidos (aparecer sem pagar)", "quick_wins"), ("Conteúdos que fazem as IAs citarem você", "content_ideas")):
        if plan.get(key):
            s.append(Paragraph(f"<b>{title}</b>", st["p"]))
            s += [Paragraph(f"{i}. {_esc(x)}", st["p"]) for i, x in enumerate(plan[key], 1)]
    if plan.get("ad_drafts"):
        s.append(Paragraph("<b>Anúncios no ChatGPT (rascunhos para as lacunas)</b>", st["p"]))
        for a in plan["ad_drafts"]:
            s.append(KeepTogether([Paragraph(f"Quando perguntarem: “{_esc(a.get('query'))}”", st["muted"]),
                                   Paragraph(f"<b>{_esc(a.get('headline'))}</b> — {_esc(a.get('text'))}", st["p"]), Spacer(1, 3)]))

    s.append(Paragraph("Como medimos", st["h2"]))
    s.append(Paragraph(
        f"Fizemos {len(d.queries or [])} perguntas de compra a {', '.join(LABELS.get(e, e) for e in engines) or 'uma IA'}"
        + (" com busca na web, pelas APIs oficiais. " if d.mode == "web" else " sem busca na web (estimativa do que o modelo “sabe”). ")
        + "% de recomendação = respostas que citam a marca ÷ total de respostas. As respostas variam conforme a pergunta, a ferramenta, o dia "
        "e o usuário: trate os números como retrato, não como garantia.", st["muted"]))
    doc.build(s)
    return buf.getvalue()
