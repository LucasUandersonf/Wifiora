# Arquitetura — GEO Office (Escritório Virtual Autônomo)

## 1. Visão geral

```
                         ┌───────────────────────────────────────────┐
  Fundador ── Dashboard ─┤ FastAPI  (/dashboard, /api/office, /api/control)
  (override, aprovações) │          (/hub, /llms.txt, /sitemap.xml)  ├── Crawlers de IA
                         └──────────────┬────────────────────────────┘   (GPTBot, ClaudeBot,
                                        │ dispatch / SSE                  PerplexityBot…)
                         ┌──────────────▼────────────────┐
                         │   Barramento (Redis | memória)│  filas por agente + pub/sub
                         └──────────────┬────────────────┘
        ┌──────────────┬────────────────┼──────────────────┬───────────────┐
   ┌────▼────┐   ┌─────▼──────┐   ┌─────▼──────┐   ┌───────▼──────┐  ┌─────▼──────┐
   │   CVO   │   │Data&Market │   │ Tech Scout │   │Financial     │  │ Quality    │
   │(orquest.)│  │  Scout     │   │            │   │  Scout       │  │Scout/Score │
   └─────────┘   └─────┬──────┘   └─────┬──────┘   └──────┬───────┘  └────────────┘
                 Market Research   Next.js/Frontend   Unit Economics
                 Schema & Ontology DevOps & Railway   Growth & Monetization
                 Data Extraction
                         │ skills plugáveis (web_fetch, jsonld, validator, cost_report…)
                         ▼
          LLM Gateway (Anthropic | OpenAI | Gemini | mock) ── Ledger (custos) ── Budget guard
                         ▼
             PostgreSQL: objetivos, tarefas, mensagens, avaliações, finanças, hubs, entidades, versões
```

## 2. Loop de execução

1. **CVO** (`cycle.start`, disparado pelo scheduler ou pelo fundador) lê caixa, KPIs, diretrizes,
   foco de nicho e hubs existentes → cria um `Objective` com fases (`research` + `finance` → `tech`).
2. **Scouts** recebem `objective.assign`, decompõem em `Task`s com dependências (`depends_on`) e
   despacham as prontas (`task.assign`).
3. **Especialistas** executam com skills + LLM e enviam `review.request` ao Score Agent.
4. **Score Agent**: nota = 0,6 × rubrica determinística + 0,4 × juiz LLM. Check bloqueante reprovado
   ⇒ reprovação. Reprovado → `task.revise` com feedback (até `MAX_REVISIONS`); depois → `task.escalated`.
5. Aprovado → Scout chama o **Executor** (`stage`): cria/atualiza Hub, entidades (com histórico de
   versões), schema, página e oportunidades. Quando todas as tarefas do setor terminam → `sector.report`.
6. **CVO** avança fases; ao final consolida (`cvo.consolidate`) e decide: publicar (autonomia ≥ 1 e gate
   de qualidade ok), pedir aprovação ao fundador (autonomia 0) ou descartar.

Toda mensagem passa por `Office.dispatch`: é persistida em `agent_messages` (auditoria), entregue na
fila do destinatário e publicada como telemetria (SSE do dashboard).

## 3. Resiliência

| Mecanismo | Onde |
|---|---|
| Retry com backoff exponencial (3 tentativas) e falha explícita ao Scout | `BaseAgent.on_error` |
| Supervisor que reinicia o loop do agente se ele cair | `Office._supervise` |
| Reconexão do consumidor Redis com backoff | `RedisBus.consume` |
| Filas duráveis (listas Redis) — sobrevivem a restart do worker | `RedisBus` |
| Idempotência: scout ignora objetivo repetido; CVO ignora relatório duplicado | `ScoutAgent`, `ChiefVirtualOfficer` |
| Budget guard: estourou o orçamento diário → pausa + pedido de aprovação + mensagem devolvida à fila | `LLMGateway`, `Office.handle_budget_block` |
| Decidir ≠ executar: LLM nunca escreve no banco; o `Executor` determinístico aplica as entregas aprovadas | `core/executor.py` |
| Anti-alucinação: citação literal precisa existir na página baixada; todo valor precisa aparecer na citação | `DataExtractionAgent`, `skills/builtin/validation.py` |

## 4. Extensão

* **Nova skill**: arquivo em `plugins/` (ver `plugins/example_skill.py`) ou módulo em `EXTRA_SKILL_MODULES`;
  depois adicione o `name` em `skill_names` do agente.
* **Novo especialista**: herde `SpecialistAgent`, defina `agent_id`, `task_kind`, `execute()`; registre em
  `agents/org.py` e crie a rubrica em `agents/rubrics.py`; se gerar estado, adicione `_stage_<kind>` no Executor.
* **Novo setor**: nova entrada em `SECTORS` (o Scout é gerado automaticamente).

## 5. Portal público e camada semântica

```
Escritório (agentes) ──aprova──> Executor ──grava──> PostgreSQL
                                     │
                                     └─ anuncia ──> Portal Next.js  POST /api/revalidate (ISR sob demanda)
                                                 └> IndexNow (Bing e outros), nunca para dados de demonstração

core/semantic.py ── monta o JSON-LD do banco ──> payloads /api/public/pages/... ──> portal Next.js
                                               └> templates Jinja (site simples do backend)
                                               └> /api/v1 (API paga, com chave e cota)
```

* **JSON-LD** gerado na hora da exibição (não congelado): `Organization` (nossa), `WebPage`
  (`reviewedBy`/`lastReviewed` quando há revisão humana), `Dataset` → `ItemList` de
  `SoftwareApplication`+`Product` com `Offer`, `Brand`, `Organization` do fornecedor (CNPJ via
  BrasilAPI), `Review` editorial só com critérios objetivos (`positiveNotes`/`negativeNotes`, **sem nota**),
  `BreadcrumbList` e `FAQPage`. O validador percorre o grafo inteiro e reprova `reviewRating`.
* **Autoridade**: data de verificação por ficha, selo de revisão humana (cai automaticamente se um valor
  mudar), páginas Sobre/Metodologia/Política editorial/Termos/Privacidade e canal de correções.
* **Monetização**: formulário de demonstração com consentimento LGPD (lead ganho vira receita real),
  API paga com chave (hash) e cota diária.

## 5b. Dados para IAs, viabilidade e Conselho

| Módulo | Papel |
|---|---|
| `core/knowledge.py` + `api/datasets.py` | grafo do site (`/knowledge-graph.jsonld`), catálogo, arquivos em lote por hub (JSONL/CSV/JSON/MD), páginas `/empresa`, `/conceitos`, `/dados` |
| `core/indexing.py` | IndexNow Semântico: aviso imediato do que mudou + vizinhos no grafo; registro em `index_pings` |
| `core/bots.py` | contador de robôs de IA (middleware + beacon do portal), por dia/robô/tipo/hub |
| `core/rankings.py` | rankings objetivos (`ItemList` ordenada), blindados contra campos pagos |
| `core/viability.py` | veredito semanal por hub (metas 30/90/180 dias), determinístico |
| `core/council.py` | reunião entre agentes: posições → réplicas → ata do CVO; aplica diretrizes dentro da autonomia, gasto vai para aprovação |
| `llm/free_client.py` | IAs gratuitas por HTTP (Groq, Gemini, OpenRouter, Ollama) com rodízio em 429 e cota diária |

## 6. Topologias de deploy

* **Produção recomendada**: serviço `geo-office` (backend, `OFFICE_ROLE=all`), serviço `portal`
  (Next.js, Root Directory `portal`), Postgres e Redis. O portal fala com o backend pela rede privada.
* **Escalável**: backend dividido em `OFFICE_ROLE=api` + `OFFICE_ROLE=worker` (o worker pode ter réplicas).
* **Mínima**: só o backend (sem `PORTAL_URL`), servindo também o site público em HTML sem JavaScript.

## 7. Limitações conhecidas / próximos passos

* Esquema criado com `create_all` + migração leve (`db._add_missing_columns`: só ADICIONA colunas, como NULL).
  Renomear/remover colunas ou mudar tipos exige Alembic.
* No modo IA gratuita não há busca na web: o Radar usa só feeds RSS e o Share of Voice fica no modo
  paramétrico (sem citações reais). A qualidade dos modelos grátis é menor: espere mais revisões do Score Agent.
* Com várias réplicas de worker, falta lock por objetivo em `ScoutAgent._dispatch_ready`.
* O limite anti-spam dos formulários é em memória por processo; com várias réplicas da API, mova para Redis.
* Leads são guardados e mostrados no painel; o envio automático ao fornecedor (e-mail/CRM) ainda não existe.
* Perfis premium com área de login para fornecedores ainda não existem (Camada 2 de monetização).
* O caminho IPv6 do `app/serve.py` não pôde ser testado no ambiente de desenvolvimento (sem IPv6).
* O portal Next.js entrega ~105 kB de JavaScript base do framework; o site simples do backend entrega 0 kB.
  Para crawlers, ambos entregam o HTML completo e o JSON-LD na primeira resposta.
