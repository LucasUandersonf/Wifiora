"""Configuração central (12-factor). Todos os valores vêm de variáveis de ambiente / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Aplicação -------------------------------------------------------
    app_env: str = "development"
    port: int = 8000
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    # all = API + agentes no mesmo processo | api = só HTTP | worker = só agentes
    office_role: str = "all"
    office_autostart: bool = True

    # --- Persistência ----------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./office.db"
    redis_url: str | None = None  # vazio = barramento em memória (dev/testes)

    # --- LLM ---------------------------------------------------------------
    # free (IAs gratuitas em rodízio) | anthropic | openai | gemini | mock
    llm_provider: str = "mock"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    # Modelos por "tier" de agente. Ajuste para modelos mais baratos se desejar.
    model_strategic: str = "claude-opus-5-5"  # CVO
    model_worker: str = "claude-opus-5-5"  # Scouts e especialistas
    model_judge: str = "claude-opus-5-5"  # Score Agent
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.5-pro"
    llm_max_tokens: int = 16000
    # IAs gratuitas (LLM_PROVIDER=free): rotas "provedor:modelo" separadas por "|", tentadas em ordem.
    # Os modelos grátis mudam com frequência: confira no painel de cada provedor antes de usar.
    free_llm_routes: str = "groq:llama-3.3-70b-versatile|gemini:gemini-2.5-flash|openrouter:openrouter/free"
    free_llm_routes_strategic: str = ""  # opcional: rotas preferidas para o CVO (ex.: um modelo maior)
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    free_llm_timeout_seconds: float = 90.0
    free_llm_max_tokens: int = 4096  # planos grátis limitam tokens por minuto; respostas longas estouram
    # Máximo de chamadas de IA por dia (0 = sem limite). Atingido, o escritório descansa até 00:00 UTC.
    llm_daily_call_limit: int = 0
    # No modo mock, registra um custo "simulado" para o dashboard ter dados realistas.
    mock_simulate_cost: bool = True
    # Atraso por chamada no modo mock, para dar para acompanhar o escritório trabalhando.
    mock_latency_seconds: float = 1.5

    # --- Governança / operação -----------------------------------------
    cycle_interval_seconds: int = 900  # intervalo entre ciclos estratégicos do CVO
    autonomy_level: int = 1  # 0 = tudo precisa de aprovação | 1 = publica sozinho, gasto extra precisa de aprovação | 2 = autonomia total
    daily_llm_budget_usd: float = 10.0
    monthly_budget_usd: float = 300.0
    infra_monthly_cost_usd: float = 20.0  # Railway (estimativa) — rateado por dia
    domain_monthly_cost_usd: float = 5.0
    starting_cash_usd: float = 1000.0
    score_threshold: float = 0.75
    max_revisions: int = 2
    default_niche: str = "Finanças pessoais"  # nome ou slug de um nicho do catálogo (app/core/niches.py)
    niche_rotation: bool = True  # nicho em foco já publicado? o CVO passa ao próximo nicho ativo sem hub

    # --- Radar de Ondas (inteligência de tendências) -------------------
    radar_enabled: bool = True
    radar_interval_seconds: int = 43200  # a cada 12 h (cada varredura faz até ~20 buscas na web)
    # Consultas para a busca na web (separadas por "|"). Cobrem GEO, anúncios e compras dentro de IAs.
    radar_queries: str = (
        "anúncios no ChatGPT publicidade|ads in AI assistants ChatGPT Gemini Perplexity Copilot|"
        "agentic commerce checkout inside AI assistant|AI shopping agents merchants protocol|"
        "generative engine optimization GEO news|Google AI Mode AI Overviews ads update|"
        "OpenAI GPTBot OAI-SearchBot crawler changes|llms.txt adoption AI crawlers|"
        "IA generativa compras Brasil varejo B2B|AI search market share Google ChatGPT Perplexity|"
        "AI publisher program revenue share Perplexity OpenAI Google|pay per crawl AI content licensing publishers|"
        "affiliate links in AI answers shopping commissions|RAG dataset ingestion structured data LLM grounding|"
        "knowledge graph entity Wikidata AI search citations"
    )
    # Feeds RSS/Atom complementares (separados por vírgula). Confira no painel quais respondem.
    radar_feeds: str = (
        "https://searchengineland.com/feed,https://www.searchenginejournal.com/feed/,"
        "https://techcrunch.com/category/artificial-intelligence/feed/,https://openai.com/news/rss.xml,"
        "https://blog.google/technology/ai/rss/"
    )

    # --- Painel de Viabilidade (metas aprovadas pelo fundador) ----------
    viability_enabled: bool = True
    viability_bots_days: int = 30  # até aqui, robôs de IA precisam ter lido o hub
    viability_traction_days: int = 90  # até aqui: citação em IA e primeiros pedidos de demonstração
    viability_revenue_days: int = 180  # até aqui: receita do hub cobrindo o custo do hub
    viability_min_leads: int = 1
    council_weekly: bool = True  # o Conselho se reúne toda semana, logo após o veredito

    # --- Rastreador de IA (várias IAs) -----------------------------------
    perplexity_api_key: str | None = None
    tracker_openai_model: str = "gpt-4o-mini"  # modelo com busca na web na Responses API (confira o atual)
    tracker_openai_search_tool: str = "web_search"
    tracker_perplexity_model: str = "sonar"
    tracker_default_queries: int = 20  # 10 a 50 perguntas de compra por relatório

    # --- Comercial automático (agência) ---------------------------------
    agency_name: str = "Agência de Visibilidade em IA"
    sales_enabled: bool = False  # liga o funil automático (prospecção → e-mail → proposta → cobrança → entrega)
    sales_auto_send: bool = True  # envia e-mails sozinho (com SMTP configurado); falso = só rascunhos
    sales_daily_email_cap: int = 20  # máximo de e-mails de prospecção por dia (protege a reputação do domínio)
    sales_interval_seconds: int = 1800
    sales_new_prospects_per_run: int = 5
    # Segmentos-alvo (perfil de cliente), separados por "|". Começa pelas categorias que o ChatGPT Ads abriu no Brasil.
    sales_segments: str = "loja online de suplementos|loja online de moda|agência de turismo|loja online de cosméticos|loja online de pet shop"
    sales_cities: str = "São Paulo|Rio de Janeiro|Belo Horizonte|Curitiba|Porto Alegre"
    price_diagnostico_brl: float = 490.0  # hipóteses de preço — ajuste conforme o mercado responder
    price_mensal_brl: float = 1490.0
    brl_per_usd: float = 5.5  # para lançar receita em reais no ledger (que é em dólar)
    payment_link_diagnostico: str | None = None  # Stripe Payment Link (aceita ?client_reference_id=)
    payment_link_mensal: str | None = None
    stripe_webhook_secret: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None  # ex.: "Ana da Agência <contato@seudominio.com.br>"
    imap_host: str | None = None
    imap_user: str | None = None
    imap_password: str | None = None

    # --- Insighta (o escritório como área comercial/marketing do SaaS) ---
    business: str = "agencia"  # agencia | insighta — o que o comercial vende
    insighta_app_url: str = "https://insighta-rcm-frontendnovo-production.up.railway.app"
    insighta_landing_url: str | None = None  # página de vendas (landing); sem ela, usa o app
    insighta_api_url: str = "https://insighta-rcm-backendnovo-production.up.railway.app"
    insighta_segments: str = "clínica odontológica|clínica de fisioterapia|clínica médica|clínica de estética|clínica de imagem|clínica oftalmológica|clínica de psicologia|laboratório de análises clínicas"
    insighta_cities: str = "São Paulo|Rio de Janeiro|Belo Horizonte|Curitiba|Porto Alegre|Brasília|Salvador|Recife|Goiânia|Campinas"
    insighta_price_basic_brl: float = 490.0
    insighta_price_pro_brl: float = 1290.0
    insighta_price_founders_brl: float = 800.0
    insighta_trial_days: int = 14
    content_enabled: bool = False  # time de Conteúdo & GEO: 1 rascunho por semana para aprovação + auditoria da landing
    content_interval_hours: int = 168
    # Boletim executivo (newsletter editorial) — só para assinantes que confirmaram (opt-in duplo)
    newsletter_enabled: bool = False  # curadoria + redação semanal (envio sempre depende da aprovação do fundador)
    newsletter_name: str = "Boletim RCM Brasil"
    newsletter_tagline: str = "Inteligência semanal sobre faturamento, glosas e regras da saúde suplementar"
    newsletter_sources: str = ""  # feeds RSS/Atom separados por "|" (ANS, Imprensa Nacional, operadoras…) — confira cada URL
    newsletter_from: str | None = None  # remetente do boletim (ex.: "Boletim RCM Brasil <boletim@seudominio>"); sem ele usa SMTP_FROM
    newsletter_send_weekday: int = 1  # 0=segunda … 1=terça
    newsletter_send_hour: int = 8  # horário de São Paulo
    newsletter_daily_send_cap: int = 250  # respeite o limite do seu provedor (Brevo, SES, SendGrid…)
    newsletter_webhook_secret: str | None = None  # bounces/reclamações do provedor de envio
    newsletter_test_email: str | None = None  # para "enviar teste para mim"
    google_maps_api_key: str | None = None  # Places API (New) — busca oficial no Google Maps, paga por chamada
    places_daily_call_cap: int = 10  # buscas no Google Maps por dia (cada uma traz até 20 clínicas)
    places_cost_per_call_usd: float = 0.035  # ESTIMATIVA para o livro-caixa — confira a tabela oficial do Google

    # --- Segurança / integrações ----------------------------------------
    founder_token: str = "change-me"
    alert_webhook_url: str | None = None  # Slack/Discord incoming webhook
    allow_web_fetch: bool = True  # agentes de extração podem acessar sites públicos
    brand_name: str = "Hub Semântico BR"

    # --- Dados da empresa (páginas institucionais, termos, LGPD) -------------
    company_legal_name: str | None = None
    company_cnpj: str | None = None
    contact_email: str | None = None
    dpo_email: str | None = None
    company_city: str | None = None

    # --- Portal público ----------------------------------------------------
    # URL do portal Next.js. Quando definida, as páginas HTML do FastAPI redirecionam (301) para lá.
    portal_url: str | None = None
    # Segredo compartilhado com o portal para revalidar páginas (ISR sob demanda) ao publicar.
    revalidate_secret: str | None = None
    # Chave do IndexNow (Bing/Yandex/Seznam): avisa os buscadores quando uma página muda.
    indexnow_key: str | None = None

    @property
    def async_database_url(self) -> str:
        """Railway entrega `postgres://` / `postgresql://`; o SQLAlchemy async precisa do driver explícito."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://") :]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        return url

    @property
    def sales_segment_list(self) -> list[str]:
        return [x.strip() for x in self.sales_segments.split("|") if x.strip()]

    @property
    def insighta_segment_list(self) -> list[str]:
        return [x.strip() for x in self.insighta_segments.split("|") if x.strip()]

    @property
    def insighta_city_list(self) -> list[str]:
        return [x.strip() for x in self.insighta_cities.split("|") if x.strip()]

    @property
    def sales_city_list(self) -> list[str]:
        return [x.strip() for x in self.sales_cities.split("|") if x.strip()]

    @property
    def radar_query_list(self) -> list[str]:
        return [q.strip() for q in self.radar_queries.split("|") if q.strip()]

    @property
    def radar_feed_list(self) -> list[str]:
        return [f.strip() for f in self.radar_feeds.split(",") if f.strip()]

    @property
    def runs_agents(self) -> bool:
        return self.office_role in ("all", "worker")

    @property
    def runs_api(self) -> bool:
        return self.office_role in ("all", "api")


@lru_cache
def get_settings() -> Settings:
    return Settings()
