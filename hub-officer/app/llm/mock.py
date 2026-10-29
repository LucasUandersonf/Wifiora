"""LLM determinístico para rodar o escritório offline (dev, CI, demonstração do dashboard).

Gera respostas JSON plausíveis por `kind`. Os dados de entidades são FICTÍCIOS e marcados como
demonstração — nunca publique um hub gerado em modo mock como se fosse real (o modelo `Hub`
recebe `demo_data=True` e as páginas exibem um aviso).

Para exercitar o loop de qualidade, a primeira tentativa de `data_extraction` devolve
intencionalmente uma entidade sem fonte; o Score Agent reprova e a revisão corrige.
"""

from __future__ import annotations

import asyncio
import json

from app.llm.base import LLMClient, LLMRequest, LLMResult

DEMO_VENDORS = [
    ("ERP Demo Alfa", 189.0, 3, True, "Simples Nacional, Lucro Presumido", ["Pix", "Marketplace Demo"]),
    ("ERP Demo Beta", 349.0, 10, True, "Simples Nacional, Lucro Presumido, Lucro Real", ["Pix", "Open Finance"]),
    ("ERP Demo Gama", 99.9, 1, False, "Simples Nacional (MEI)", ["Pix"]),
    ("ERP Demo Delta", 599.0, 25, True, "Lucro Presumido, Lucro Real", ["Open Finance", "Marketplace Demo"]),
]


# Sinais FICTÍCIOS para o modo simulação do Radar (domínios .invalid; nunca tratar como notícia real).
DEMO_SIGNALS = [
    {"url": "https://noticias.exemplo.invalid/assistente-x-testa-anuncios", "title": "[DEMO] Assistente X começa a testar anúncios nas respostas",
     "summary": "Plataforma fictícia anuncia teste de anúncios identificados abaixo das respostas.", "source": "noticias.exemplo.invalid"},
    {"url": "https://noticias.exemplo.invalid/assistente-y-anuncios-patrocinados", "title": "[DEMO] Assistente Y amplia perguntas patrocinadas para anunciantes",
     "summary": "Formato de pergunta sugerida patrocinada chega a mais países.", "source": "noticias.exemplo.invalid"},
    {"url": "https://tech.exemplo.invalid/checkout-dentro-do-chat", "title": "[DEMO] Lojas passam a vender direto dentro do chat de um assistente",
     "summary": "Protocolo fictício permite que o assistente finalize a compra sem sair da conversa.", "source": "tech.exemplo.invalid"},
    {"url": "https://tech.exemplo.invalid/protocolo-comercio-agentico", "title": "[DEMO] Grandes varejistas aderem a protocolo aberto de comércio por agentes",
     "summary": "Feeds de produto estruturados viram requisito para aparecer em compras por agentes.", "source": "tech.exemplo.invalid"},
    {"url": "https://seo.exemplo.invalid/trafego-de-ias-cresce", "title": "[DEMO] Tráfego vindo de assistentes de IA cresce em sites B2B",
     "summary": "Pesquisa fictícia mostra aumento de visitas com origem em assistentes.", "source": "seo.exemplo.invalid"},
    {"url": "https://seo.exemplo.invalid/novo-robo-de-busca", "title": "[DEMO] Novo robô de busca de IA respeita llms.txt e dados estruturados",
     "summary": "Documentação fictícia recomenda dados estruturados para ser citado.", "source": "seo.exemplo.invalid"},
]


def _slug(s: str) -> str:
    return "-".join("".join(c.lower() if c.isalnum() else " " for c in s).split())


class MockLLM(LLMClient):
    provider = "mock"

    def __init__(self, latency_seconds: float = 0.0) -> None:
        self.latency = latency_seconds

    async def complete(self, req: LLMRequest) -> LLMResult:
        if self.latency:
            await asyncio.sleep(self.latency)
        handler = getattr(self, "_" + req.kind.replace(".", "_"), self._generic)
        data = handler(req)
        text = json.dumps(data, ensure_ascii=False)
        return LLMResult(
            text=text,
            provider=self.provider,
            model=f"mock:{req.model}",
            input_tokens=max(1, (len(req.system) + len(req.prompt)) // 4),
            output_tokens=max(1, len(text) // 4),
            stop_reason="end_turn",
        )

    # ------------------------------------------------------------------ CVO
    def _cvo_plan(self, req: LLMRequest) -> dict:
        niche = req.context.get("niche") or "Corporate Finance & ERPs (B2B SaaS)"
        return {
            "title": f"Lançar hub verificado: {niche}",
            "niche": niche,
            "rationale": "Nicho com alta dor de alucinação (regras fiscais brasileiras) e alto ticket B2B; "
            "dados estruturados limpos maximizam a chance de citação por motores generativos.",
            "kpis": {"entities_target": 4, "min_grounding_ratio": 0.8, "max_cost_usd": 2.0},
            "phases": [
                {
                    "phase": 1,
                    "assignments": [
                        {"sector": "research", "brief": "Mapear o nicho, desenhar o schema e extrair dados verificados dos principais fornecedores."},
                        {"sector": "finance", "brief": "Calcular unit economics do ciclo e mapear canais de monetização do nicho."},
                    ],
                },
                {
                    "phase": 2,
                    "assignments": [
                        {"sector": "tech", "brief": "Gerar a página SSR do hub com JSON-LD e validar a saúde da infraestrutura."},
                    ],
                },
            ],
        }

    def _cvo_consolidate(self, req: LLMRequest) -> dict:
        return {
            "summary": "Ciclo concluído: hub estruturado, dados validados e página pronta para indexação.",
            "decision": "publish",
            "highlights": ["Schema Dataset + ItemList aninhado", "Grounding >= 80% nas entidades aprovadas"],
            "risks": ["Dados de demonstração — substituir por extração real antes de divulgar"],
            "next_focus": "Rodar auditoria de citação generativa (Share of Voice) após indexação.",
        }

    # --------------------------------------------------------------- Scouts
    def _scout_decompose(self, req: LLMRequest) -> dict:
        specialists: dict[str, str] = req.context.get("specialists", {})  # agent_id -> kind
        sequential = req.context.get("sector") in ("research", "radar")
        tasks = []
        for i, (agent_id, kind) in enumerate(specialists.items()):
            tasks.append(
                {
                    "title": f"{kind.replace('_', ' ').title()}",
                    "kind": kind,
                    "assignee": agent_id,
                    "brief": f"Executar {kind} alinhado ao objetivo do setor.",
                    "priority": 10 - i,
                    "depends_on": [i - 1] if sequential and i > 0 else [],
                }
            )
        return {"tasks": tasks, "notes": "Decomposição padrão (mock)."}

    def _scout_report(self, req: LLMRequest) -> dict:
        return {"summary": f"Setor {req.context.get('sector')} concluiu as entregas.", "confidence": 0.85}

    # ---------------------------------------------------------- Specialists
    def _market_research(self, req: LLMRequest) -> dict:
        niche = req.context.get("niche") or "Corporate Finance & ERPs (B2B SaaS)"
        return {
            "niche": niche,
            "hub_title": "Comparativo de ERPs para PMEs no Brasil (dados verificados)",
            "hub_slug": _slug("erps-pme-brasil"),
            "entity_type": "SoftwareApplication",
            "hallucination_pain": "LLMs erram limites do Simples Nacional, suporte a NF-e/NFS-e e preços por usuário.",
            "target_queries": [
                "qual o melhor ERP para empresa do Simples Nacional",
                "ERP com emissão de NF-e e NFS-e preço",
                "comparativo ERP PME Brasil 2026",
                "ERP que suporta Lucro Real",
            ],
            "candidate_entities": [{"name": v[0], "website": f"https://{_slug(v[0])}.exemplo.invalid"} for v in DEMO_VENDORS],
            "monetization_signals": ["CPL B2B R$150–1.500", "programas de afiliados de ERPs"],
        }

    def _schema_design(self, req: LLMRequest) -> dict:
        return {
            "entity_schema_type": "SoftwareApplication",
            "fields": [
                {"name": "preco_mensal_brl", "type": "number", "schema_property": "offers.price", "required": True, "rank": "asc", "rank_label": "Menor preço mensal"},
                {"name": "usuarios_inclusos", "type": "integer", "schema_property": "additionalProperty", "required": True, "rank": "desc", "rank_label": "Mais usuários inclusos no plano"},
                {"name": "emite_nfe", "type": "boolean", "schema_property": "featureList", "required": True, "graph_role": "feature", "concept_label": "Emissão de NF-e"},
                {"name": "regimes_tributarios", "type": "string", "schema_property": "additionalProperty", "required": True, "graph_role": "concept"},
                {"name": "integracoes", "type": "list", "schema_property": "isRelatedTo", "required": False, "graph_role": "integrations"},
                {"name": "site_oficial", "type": "url", "schema_property": "url", "required": False},
            ],
            "jsonld_template": {
                "@context": "https://schema.org",
                "@type": "SoftwareApplication",
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web",
            },
            "dataset_strategy": "Dataset por hub com dateModified e ItemList de entidades; histórico de versões público.",
            "review_criteria": [
                {"label": "Emite NF-e", "field": "emite_nfe", "op": "eq", "value": True},
                {"label": "Atende empresas do Simples Nacional", "field": "regimes_tributarios", "op": "contains", "value": "Simples Nacional"},
                {"label": "Atende Lucro Real", "field": "regimes_tributarios", "op": "contains", "value": "Lucro Real"},
                {"label": "Plano de entrada até R$ 300/mês", "field": "preco_mensal_brl", "op": "lte", "value": 300},
                {"label": "Inclui 3 ou mais usuários", "field": "usuarios_inclusos", "op": "gte", "value": 3},
            ],
        }

    def _data_extraction(self, req: LLMRequest) -> dict:
        first_attempt = not req.context.get("feedback")
        entities = []
        for idx, (name, price, users, nfe, regimes, integrations) in enumerate(DEMO_VENDORS):
            url = f"https://{_slug(name)}.exemplo.invalid/precos"
            quote = (
                f"{name}: plano a partir de R$ {price:.2f}/mês com {users} usuário(s) incluso(s). "
                f"Emissão de NF-e: {'sim' if nfe else 'não'}. Regimes: {regimes}. Integrações: {', '.join(integrations)}."
            )
            sources = [{"url": url, "quote": quote}]
            if first_attempt and idx == len(DEMO_VENDORS) - 1:
                sources = []  # falha proposital (ver docstring)
            entities.append(
                {
                    "name": name,
                    "attributes": {
                        "preco_mensal_brl": price,
                        "usuarios_inclusos": users,
                        "emite_nfe": nfe,
                        "regimes_tributarios": regimes,
                        "integracoes": integrations,
                        "site_oficial": f"https://{_slug(name)}.exemplo.invalid",
                    },
                    "sources": sources,
                    # Fornecedor fictício: sem CNPJ (nunca inventamos CNPJ, nem em demonstração).
                    "provider": {"razao_social": f"{name} Tecnologia Ltda (fictícia)", "municipio": "São Paulo", "uf": "SP"},
                    "confidence": 0.9,
                }
            )
        return {"entities": entities, "notes": "Dados de DEMONSTRAÇÃO (fornecedores fictícios)."}

    def _frontend_page(self, req: LLMRequest) -> dict:
        return {
            "sections": ["resumo", "tabela_comparativa", "metodologia", "faq", "historico_de_atualizacoes"],
            "table_columns": ["preco_mensal_brl", "usuarios_inclusos", "emite_nfe", "regimes_tributarios"],
            "faq": [
                {"q": "Qual ERP é mais barato para o Simples Nacional?", "a": "Veja a coluna de preço filtrando pelo regime Simples Nacional."},
                {"q": "Como os dados são verificados?", "a": "Cada valor é extraído de fonte oficial citada e revisado pelo controle de qualidade."},
            ],
            "meta_description": "Comparativo verificado de ERPs para PMEs brasileiras: preços, NF-e e regimes tributários com fontes.",
            "performance_budget": {"max_html_kb": 60, "third_party_scripts": 0},
        }

    def _devops_check(self, req: LLMRequest) -> dict:
        return {"assessment": "Infraestrutura saudável.", "actions": []}

    def _unit_economics(self, req: LLMRequest) -> dict:
        m = req.context.get("metrics", {})
        return {
            "assessment": "Custo por entidade publicada dentro da meta; manter tiers de modelo atuais.",
            "recommendations": ["Cachear prompts de sistema estáveis", "Priorizar nichos com CPL acima de R$ 300"],
            "metrics_echo": m,
        }

    def _growth_plan(self, req: LLMRequest) -> dict:
        return {
            "opportunities": [
                {"channel": "cpl", "title": "CTA 'Solicitar demonstração' roteado ao CRM do fornecedor", "est_monthly_usd": 400, "confidence": 0.5},
                {"channel": "premium_profile", "title": "Selo 'Dados Verificados' com atualização prioritária", "est_monthly_usd": 250, "confidence": 0.4},
                {"channel": "api", "title": "API JSON-LD paga para ferramentas de inteligência de mercado", "est_monthly_usd": 150, "confidence": 0.25},
            ]
        }

    # ------------------------------------------------------------- Radar
    def _signal_triage(self, req: LLMRequest) -> dict:
        topics = ["anuncios_em_ia", "anuncios_em_ia", "compras_agenticas", "compras_agenticas", "geo_busca_ia", "crawlers_e_acesso"]
        n = len(req.context.get("candidates", []))
        return {"selected": [
            {"index": i, "topics": [topics[i % len(topics)]], "relevance": 0.6 + 0.05 * (i % 4), "summary_pt": f"(Demonstração) {c.get('summary', '')}"}
            for i, c in enumerate(req.context.get("candidates", [])[:n])
        ]}

    def _wave_analysis(self, req: LLMRequest) -> dict:
        sig = req.context.get("signals", [])
        by_topic: dict[str, list[str]] = {}
        for s in sig:
            for t in s.get("topics") or ["geo_busca_ia"]:
                by_topic.setdefault(t, []).append(s["url"])
        catalog = {
            "anuncios_em_ia": ("anuncios-em-assistentes-de-ia", "Anúncios dentro de assistentes de IA", "emergente", 0.8, 0.75, "3-6 meses"),
            "compras_agenticas": ("compras-feitas-por-agentes", "Compras feitas por agentes de IA", "emergente", 0.85, 0.7, "6-12 meses"),
            "geo_busca_ia": ("ia-como-porta-de-entrada-da-busca", "IA como porta de entrada da busca B2B", "crescendo", 0.9, 0.8, "agora"),
            "crawlers_e_acesso": ("robos-de-ia-e-dados-estruturados", "Robôs de IA valorizando dados estruturados", "crescendo", 0.6, 0.5, "agora"),
        }
        waves = []
        for topic, urls in by_topic.items():
            if topic in catalog:
                slug, name, stage, imp, urg, win = catalog[topic]
                waves.append({"slug": slug, "name": name, "thesis": f"(Demonstração) {name} ganham força segundo sinais fictícios.", "stage": stage,
                              "impact": imp, "urgency": urg, "confidence": 0.5, "window": win,
                              "relevance_for_us": "Exemplo de simulação: indica onde o hub deveria se posicionar.", "evidence": urls})
        return {"waves": waves}

    def _positioning_plan(self, req: LLMRequest) -> dict:
        waves = req.context.get("waves", [])
        plays = []
        for w in waves[:3]:
            plays.append({"wave_slug": w["slug"], "title": f"(Demo) Preparar o hub para: {w['name']}",
                          "action": "Ação de exemplo gerada em modo simulação.", "why": "Demonstração do fluxo do radar.",
                          "first_step": "Revisar a onda no painel e decidir se vale testar.", "effort": "baixo", "est_cost_usd": 0, "deadline_days": 14})
        return {"plays": plays, "brief": (
            "(Boletim de demonstração, com sinais fictícios.) Esta semana o radar viu sinais de anúncios chegando aos assistentes de IA, "
            "de compras feitas direto no chat e de mais tráfego vindo de IAs para sites B2B. A onda mais quente para nós é a IA virando "
            "a porta de entrada da busca. Sugerimos acompanhar e testar ações baratas antes de qualquer gasto."
        )}

    # -------------------------------------------------------------- Judge
    # ------------------------------------------------------------- Conselho
    _COUNCIL = {
        "research.market": ("Há demanda: ERPs para PMEs têm muitos compradores e preço confuso; o nicho segue bom.", "diretriz", "Priorizar fichas dos 10 ERPs mais buscados por PMEs"),
        "finance.growth": ("Sem receita ainda. O caminho mais rápido é vender pedidos de demonstração e um serviço de agência GEO.", "fundador", "Oferecer diagnóstico GEO pago para 5 fornecedores do hub"),
        "finance.unit_economics": ("Com IA gratuita o custo fixo é baixo; o equilíbrio depende de 2 a 3 clientes pagantes.", "diretriz", "Manter custo mensal abaixo de US$ 30 até a primeira receita"),
        "radar.strategy": ("Anúncios e compras dentro das IAs ainda são incertos; dados verificados ganham valor nesse cenário.", "diretriz", "Publicar o hub de ERPs antes de abrir um segundo nicho"),
        "quality.score": ("Cuidado: as projeções de receita são hipóteses; nenhum lead real ainda. Não prometer recomendação a pagantes.", "diretriz", "Toda proposta comercial deve dizer que posição não é vendida"),
    }

    def _council_position(self, req: LLMRequest) -> dict:
        pos, typ, idea = self._COUNCIL.get(req.context.get("agent", ""), ("Sem posição.", "diretriz", "Revisar"))
        return {"position": f"(Demonstração) {pos}", "evidence": ["receita_real_total = 0"], "ideas": [{"title": idea, "type": typ, "detail": idea, "cost_usd": 0, "expected_impact": "médio"}], "risks": ["dados de demonstração"], "confidence": 0.5}

    def _council_reply(self, req: LLMRequest) -> dict:
        me = req.context.get("agent", "")
        others = [m for m in req.context.get("members", []) if m != me]
        to = others[0] if others else me
        agree = me != "quality.score"
        return {"replies": [{"to": to, "agree": agree, "point": "Concordo com a prioridade em receita rápida." if agree else "Os números de receita ainda não têm base."}], "revised_position": "Manter o foco e buscar os primeiros pagantes.", "keep_ideas": []}

    def _council_synthesis(self, req: LLMRequest) -> dict:
        return {
            "profit_outlook": "incerto",
            "why": "(Demonstração) Custos baixos com IA gratuita, mas ainda sem receita real: o lucro depende de o fundador fechar os primeiros clientes.",
            "scenarios": [
                {"name": "pessimista", "revenue_usd_month_12": 0, "cost_usd_month": 25, "breakeven_month": None, "assumptions": ["nenhum fornecedor paga por leads", "hipótese"]},
                {"name": "base", "revenue_usd_month_12": 300, "cost_usd_month": 30, "breakeven_month": 6, "assumptions": ["3 fornecedores pagando US$ 100/mês (hipótese)"]},
                {"name": "otimista", "revenue_usd_month_12": 1500, "cost_usd_month": 60, "breakeven_month": 3, "assumptions": ["serviço de agência GEO + API (hipótese)"]},
            ],
            "decisions": [
                {"type": "diretriz", "text": "Priorizar fichas dos 10 ERPs mais buscados por PMEs", "why": "maior chance de citação"},
                {"type": "diretriz", "text": "Toda proposta comercial deve dizer que posição em ranking não é vendida", "why": "proteger a confiança"},
            ],
            "proposals_for_founder": [{"title": "Registrar domínio e publicar o portal", "cost_usd": 15, "why": "sem domínio não há tráfego nem robôs", "type": "gasto"}],
            "founder_tasks": ["Contatar 5 fornecedores do hub oferecendo diagnóstico GEO", "Definir preço do perfil verificado"],
            "dissent": [{"agent": "Juno", "point": "projeções de receita sem base em dados reais"}],
            "next_topic": "Preço e pacote do serviço de agência GEO",
        }

    # ------------------------------------------------------------- Diagnóstico de visibilidade
    def _diagnosis_queries(self, req: LLMRequest) -> dict:
        cat = req.context.get("category") or "o segmento"
        city = req.context.get("city") or "no Brasil"
        base = ["Qual a melhor {c} {r}?", "{c} mais barata {r} vale a pena?", "Onde comprar {c} com entrega rápida {r}?",
                "Quais as opções de {c} com melhor custo-benefício?", "Alternativas confiáveis de {c} {r}", "{c}: qual tem melhor atendimento?",
                "Comparativo de {c} para iniciantes", "Qual {c} é mais recomendada por clientes {r}?"]
        n = int(req.context.get("n") or len(base))
        extra = ["para pequenas empresas", "com frete grátis", "em promoção", "com melhor avaliação", "para presente", "confiável"]
        qs = [q.format(c=cat, r=city) for q in base]
        i = 0
        while len(qs) < n:
            qs.append(f"{base[i % len(base)].format(c=cat, r=city).rstrip('?')} {extra[(i // len(base)) % len(extra)]}?")
            i += 1
        return {"queries": qs[: max(n, 1)] if req.context.get("n") else qs}

    def _diagnosis_answer(self, req: LLMRequest) -> dict:
        import hashlib

        names = [req.context.get("brand", "")] + list(req.context.get("competitors") or [])
        h = int(hashlib.sha256(req.prompt.encode()).hexdigest(), 16)
        # determinístico: cada pergunta cita um subconjunto; a marca analisada aparece menos (cenário típico)
        cited = [n for i, n in enumerate(names) if n and (h >> (i * 3)) % (5 if i == 0 else 2) == 0]
        text = "(Demonstração) Algumas opções citadas com frequência: " + (", ".join(cited) if cited else "não há uma marca de referência clara") + "."
        return {"answer": text}

    def _diagnosis_plan(self, req: LLMRequest) -> dict:
        brand = req.context.get("brand", "a marca")
        gaps = req.context.get("gaps") or []
        return {
            "summary": f"(Demonstração) {brand} aparece pouco nas respostas das IAs; concorrentes ocupam as perguntas de comparação. "
                       "Há perguntas sem nenhuma marca citada — terreno livre para ocupar. O site precisa de dados estruturados.",
            "quick_wins": ["Liberar GPTBot, OAI-SearchBot e ClaudeBot no robots.txt", "Marcar a empresa com Organization/LocalBusiness em JSON-LD",
                           "Publicar uma página de preços e condições clara e datada", "Criar um llms.txt com links para as páginas principais",
                           "Responder às 5 perguntas de compra em uma página de perguntas frequentes"],
            "content_ideas": ["Tabela comparativa honesta com concorrentes, com fonte e data", "Guia 'como escolher' com critérios objetivos"],
            "ad_drafts": [{"query": q, "headline": f"{brand}: compare antes de comprar"[:40], "text": "Preços, prazos e condições claros. Veja as opções e escolha com segurança.", "why": "concorrentes aparecem e a marca não"} for q in gaps[:3]],
        }

    # ------------------------------------------------------------- Comercial
    def _sales_email(self, req: LLMRequest) -> dict:
        f = req.context.get("facts", {})
        if req.context.get("touch", 1) > 1:
            return {"subject": f"Re: {f.get('empresa')} nas respostas das IAs", "body": f"(Demonstração) Só para não se perder: o relatório da {f.get('empresa')} continua disponível, sem custo."}
        return {"subject": f"{f.get('empresa')}: apareceu em {f.get('citada_pct')}% das respostas de IA",
                "body": f"(Demonstração) Olá, equipe da {f.get('empresa')}. Fizemos {f.get('perguntas')} perguntas de compra sobre {f.get('segmento')} a uma IA "
                        f"e a empresa apareceu em {f.get('citada_pct')}% delas. Quem mais aparece: {f.get('quem_mais_aparece')}. "
                        "O relatório completo é gratuito. Se quiser conversar, é só responder."}

    def _sales_classify(self, req: LLMRequest) -> dict:
        t = (req.context.get("text") or "").lower()
        return {"intent": "nao" if "não tenho interesse" in t or "nao tenho interesse" in t else "interessado" if "interess" in t or "quanto custa" in t else "duvida"}

    def _sales_answer(self, req: LLMRequest) -> dict:
        o = req.context.get("offer", {})
        return {"body": f"(Demonstração) Obrigado pelo retorno! O diagnóstico completo custa R$ {o.get('diagnostico_completo_brl')} e o acompanhamento mensal "
                        f"R$ {o.get('acompanhamento_mensal_brl')}, sem a verba de anúncios. Os detalhes estão na proposta."}

    def _sales_kit(self, req: LLMRequest) -> dict:
        c = req.context.get("company", "Empresa")
        qs = req.context.get("queries") or ["Qual a melhor opção?"]
        return {"faq": [{"q": q, "a": f"(Demonstração) A {c} [CONFIRMAR: resposta com dados reais da empresa]."} for q in qs[:6]],
                "llms_txt": f"# {c}\n\n> [CONFIRMAR: descrição curta da empresa]\n\n## Páginas\n- [Produtos](/produtos)\n- [Contato](/contato)\n",
                "about": f"(Demonstração) A {c} atua em [CONFIRMAR: segmento e cidade] desde [CONFIRMAR: ano]."}

    def _evaluation_judge(self, req: LLMRequest) -> dict:
        det = float(req.context.get("deterministic_score", 0.8))
        return {"score": round(min(1.0, det + 0.05), 2), "feedback": "Saída coerente com o objetivo." if det >= 0.75 else "Corrigir os checks reprovados."}

    # ------------------------------------------------------------- Insighta (comercial e conteúdo)
    def _insighta_email(self, req: LLMRequest) -> dict:
        f = req.context.get("facts", {})
        if req.context.get("touch", 1) > 1:
            return {"subject": f"{f.get('clinica')}: a conta leva 2 minutos", "body": f"(Demonstração) Uma pergunta rápida: a {f.get('clinica')} sabe hoje quanto perdeu com {f.get('dor_tipica')} no último mês?"}
        return {"subject": f"{f.get('clinica')}: quanto do faturamento chega ao caixa?",
                "body": f"(Demonstração) Olá, equipe da {f.get('clinica')}. Em clínicas como a de vocês é comum perder dinheiro com {f.get('dor_tipica')} sem ver o número. "
                        f"A calculadora abaixo estima o valor em 2 minutos, e o teste com os dados reais é grátis por {f.get('teste_gratis_dias')} dias."}

    def _insighta_answer(self, req: LLMRequest) -> dict:
        return {"qualified": True, "reason": "demonstração", "body": ""}  # o texto padrão (2 opções + plano) entra pelo código

    def _insighta_article(self, req: LLMRequest) -> dict:
        t = req.context.get("title", "")
        return {"title": t, "meta_description": f"(Demonstração) {t}: o que é, por que importa e o que fazer na sua clínica.",
                "body_markdown": f"(Demonstração) Resposta direta sobre {req.context.get('keyword', '')}.\n\n## Por que isso importa\n\nTexto de exemplo.\n\n## Passo a passo\n\n1. Primeiro passo.\n2. Segundo passo.",
                "faq": [{"q": f"{t}?", "a": "(Demonstração) Resposta curta."}], "sources": ["ANS — padrão TISS"]}

    def _generic(self, req: LLMRequest) -> dict:
        return {"result": "ok", "kind": req.kind}
