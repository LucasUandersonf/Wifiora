# Auditoria GEO/SEO da landing da Insighta — 29/10/2026

Feita pelo time de Conteúdo & GEO do escritório, sobre o código em `insighta-rcm-frontend_novo/landing/site` (o site no ar não pôde ser acessado deste ambiente; repita a checagem com o domínio real).

## Nota técnica: 8/12 hoje → 12/12 com 4 ajustes

| Item | Situação | Observação |
|---|---|---|
| HTTPS | ok (Railway) | |
| Robôs de IA liberados no robots.txt | ok | `Allow: /` para todos |
| JSON-LD na página | ok | Organization, SoftwareApplication (3 ofertas) e FAQPage (16 perguntas) |
| Título, descrição, canonical, h1 único, `lang="pt-BR"`, Open Graph | ok | 15 h2, nenhuma imagem sem `alt`, HTML servido pronto (sem depender de JavaScript) |
| Sitemap | **parcial** | só 1 URL; vai crescer com as páginas de conteúdo |
| llms.txt | **falta** | proposta pronta em `docs/insighta/llms.txt` |
| Indexação liberada | **falta em produção** | `start.sh` usa `ROBOTS="noindex, nofollow"` por padrão (cabeçalho `X-Robots-Tag`). Em produção precisa `ROBOTS=index, follow`, senão Google e IAs ignoram o site |
| Domínio próprio | **falta (C1)** | canonical e sitemap usam `__SITE_URL__`; em `*.up.railway.app` o site não acumula autoridade |

## Ajustes, em ordem
1. **Domínio próprio** (C1) e `SITE_URL` apontando para ele.
2. **`ROBOTS=index, follow`** na variável do serviço `landing` de produção (só produção; homologação continua `noindex`).
3. **`llms.txt`**: basta copiar `docs/insighta/llms.txt` para `site/`. O nginx já troca `__SITE_URL__`/`__APP_URL__` em arquivos de texto (`sub_filter_types text/plain`), como faz no `robots.txt`.
4. **Páginas de conteúdo** (cada uma no sitemap): o `ESTRATEGIA.md` já prevê "o que é glosa médica", "como fazer recurso de glosa" e "como reduzir faltas em clínica". O escritório escreve os rascunhos; o fundador aprova.

Nada disso foi alterado no repositório da Insighta (feature freeze do `develop` e decisão do fundador).
