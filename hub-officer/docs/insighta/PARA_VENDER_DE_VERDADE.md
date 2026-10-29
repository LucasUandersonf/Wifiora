# O que falta para o escritório vender a Insighta de verdade

Hoje tudo roda em **modo demonstração**: e-mails "simulados", clínicas de exemplo e IA de teste. Para ligar, siga a ordem abaixo. Os preços foram pesquisados em 29/10/2026, em parte em sites de terceiros, então **confira na página oficial antes de pagar**.

## 1. Coisas que você contrata

| # | Item | Para quê | Custo estimado | Observação |
|---|---|---|---|---|
| 1 | **Domínio da Insighta** (`.com.br`) | Landing, e-mail e blog com autoridade própria | **R$ 40/ano** no Registro.br | É o item C1 do lançamento da Insighta. Bloqueia todo o resto |
| 2 | **Segundo domínio só para prospecção** (ex.: `insighta-clinicas.com.br`) | E-mail frio sai por ele. Se cair em spam, o domínio principal e o e-mail dos clientes ficam protegidos | **R$ 40/ano** | Prática padrão de outbound. O site dele redireciona para a landing |
| 3 | **Caixa de e-mail** no domínio de prospecção | Enviar (SMTP) e ler respostas (IMAP) | Zoho Mail Lite: cerca de **US$ 1/usuário/mês** (anual). Google Workspace Starter: cerca de **US$ 7/usuário/mês** (anual) | Configure SPF, DKIM e DMARC. **Aqueça o domínio**: comece com 5 a 10 e-mails/dia e suba aos poucos até 20 a 30 em 3 a 4 semanas |
| 4 | **Chave do Google Maps** (Places API New) | Diana acha clínicas | **US$ 0** dentro da cota grátis mensal | A busca que traz o site da clínica é cobrada na faixa "Text Search Enterprise", com cota grátis mensal (cerca de 1.000 chamadas) e depois cerca de US$ 35 por mil. Com o limite padrão de 10 buscas/dia (~300/mês), fica dentro da cota. Precisa de conta de faturamento no Google Cloud com cartão. Coloque um **alerta de orçamento** e restrinja a chave à Places API |
| 5 | **Hospedagem do escritório** (Railway) | Escritório no ar 24h (painel + agendadores + banco) | Plano Hobby: **US$ 5/mês**, com US$ 5 de uso incluso. Estimativa real: US$ 5 a 15/mês com Postgres | Projeto separado do da Insighta. Só faço o deploy com o seu OK explícito |
| 6 | **IA** | Escrever e-mails e conteúdo | **US$ 0** com IAs gratuitas (Groq/Gemini) | Já suportado (rodízio + cota diária). Uma IA paga melhora o texto, mas é opcional |

**Total para começar: cerca de R$ 80/ano de domínios + US$ 6 a 22/mês** (cerca de R$ 35 a 125/mês, dependendo do câmbio e do e-mail escolhido).

## 2. Configuração do escritório (variáveis de ambiente)

```
BUSINESS=insighta
INSIGHTA_LANDING_URL=https://<domínio da landing>
GOOGLE_MAPS_API_KEY=<chave restrita à Places API>
PLACES_DAILY_CALL_CAP=10
SMTP_HOST=… SMTP_USER=… SMTP_PASSWORD=… SMTP_FROM="Nome da Insighta <contato@dominio-de-prospeccao>"
IMAP_HOST=… IMAP_USER=… IMAP_PASSWORD=…
COMPANY_CNPJ=<CNPJ da Insighta, vai no rodapé>
PUBLIC_BASE_URL=https://<endereço público do escritório>   # links de descadastro
SALES_DAILY_EMAIL_CAP=10        # subir aos poucos (aquecimento)
CONTENT_ENABLED=true
ALLOW_WEB_FETCH=true
```

Depois, ligue no painel: **Comercial ligado** e **Time de conteúdo ligado**.

## 3. Ajustes no lado da Insighta (decisão sua, por causa do feature freeze)

1. **`ROBOTS=index, follow`** no serviço da landing em produção. Hoje o padrão é `noindex`, então Google e IAs ignoram a página.
2. Copiar **`docs/insighta/llms.txt`** para `landing/site/`.
3. **Guardar a origem do cadastro (UTM)** no signup da Insighta. Os e-mails já mandam `utm_source`, `utm_campaign` e `utm_content`. Sem guardar isso no cadastro, não dá para medir quantas clínicas que o escritório contatou viraram teste e pagamento. É uma mudança pequena: ler os parâmetros da URL no signup e salvar na conta.
4. Publicar as páginas de conteúdo aprovadas (em `/<slug>`) e incluí-las no `sitemap.xml`.

## 4. O que continua sendo humano

- **Ligar para quem respondeu com interesse.** O painel avisa, e é a ação que mais converte.
- **Aprovar ou rejeitar os rascunhos de conteúdo** (5 minutos por semana).
- **LinkedIn:** a IA pode rascunhar, mas quem envia é você. O LinkedIn proíbe automação.
- **WhatsApp:** só com clínicas que pediram o contato.

## 5. Ordem sugerida

1. Domínios e e-mail com SPF/DKIM/DMARC (semana 1).
2. Chave do Maps com alerta de orçamento e deploy do escritório (semana 1).
3. Comercial ligado com 5 a 10 e-mails/dia e revisão diária no painel (semanas 2 a 4, aquecendo).
4. `ROBOTS`, `llms.txt` e as 3 primeiras páginas de conteúdo publicadas (semanas 2 a 4).
5. UTM no signup, para medir conversão real (quando o freeze permitir).

## Fontes dos preços

- Google Maps Platform, tabela de preços: https://developers.google.com/maps/billing-and-pricing/pricing
- Registro.br, R$ 40/ano (Teletime, out/2026): https://teletime.com.br/14/10/2026/br-6-milhoes/
- Zoho Mail (Capterra): https://www.capterra.com/p/174694/Zoho-Mail/pricing/
- Google Workspace (guia 2026): https://www.eesel.ai/pt/blog/google-workspace-pricing
- Railway, planos: https://docs.railway.com/pricing/plans
