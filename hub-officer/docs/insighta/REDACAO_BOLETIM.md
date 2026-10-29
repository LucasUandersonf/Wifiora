# Operação da Redação: Boletim RCM Brasil

Objetivo: fazer a Insighta virar referência em dados e faturamento na saúde, no mesmo lugar que MV e Tasy ocupam como infraestrutura, por meio de um boletim semanal de alto valor, sem venda direta. Em 6 meses, o gestor deve pensar "Insighta? É o pessoal do boletim de faturamento".

## O que o escritório faz sozinho

| Etapa | Agente | Quando |
|---|---|---|
| Curadoria das fontes oficiais | Clio | Toda semana (a primeira verificação depois de segunda) |
| Redação: manchete, gráfico com fonte, notas de bancada | Calíope | Logo após a curadoria |
| HTML (Outlook e celular), texto puro e versão web | Dédalo | Logo após a redação |
| **Aprovação** | **Você** (prévia, teste no seu e-mail, aprovar) | Até segunda à noite |
| Envio em lotes, só para assinantes confirmados | Dédalo | Terça, 8h |
| Higiene da base (bounces, spam, descadastros) | Automático (webhook) | Contínuo |
| Edição publicada na web (conteúdo indexável para Google e IAs) | Automático | Depois do envio |

## A mudança necessária no plano: de onde vêm os leitores

O plano original previa enviar para uma "base extraída do LinkedIn via API". **Isso não pode ser feito**, por três motivos:

1. **LinkedIn:** o contrato de usuário proíbe raspar e extrair dados, e a API não entrega e-mail de terceiros. O risco é a conta banida e um processo (LinkedIn x hiQ).
2. **Provedores de envio:** Brevo, SES e SendGrid proíbem listas compradas, extraídas ou de terceiros, exigem prova de consentimento e suspendem a conta. Sem provedor não há boletim.
3. **LGPD:** marketing para quem não tem relação com a empresa não se sustenta no "legítimo interesse". O caminho seguro é o consentimento.

E pesa também o lado estratégico: um boletim que chega sem ter sido pedido é spam, e destrói a autoridade que ele deveria construir.

### Como crescer a base de forma legal (e mais rápida do que parece)

1. **Prospecção 1:1 que já existe:** o último e-mail para cada clínica e o e-mail de "não é o momento" já trazem o convite ao boletim.
2. **LinkedIn orgânico, feito por você:** publique o resumo de cada edição com o link de inscrição. Isso não é raspagem; é distribuição.
3. **Landing e blog da Insighta:** um bloco "Assine o Boletim RCM Brasil" (formulário apontando para `/boletim`). Precisa de uma pequena mudança na landing.
4. **Edições públicas na web:** cada edição vira uma página indexável, que traz leitores pela busca e por IAs.
5. **Indicação:** "encaminhe para o faturista" no rodapé (próximo passo, se quiser).
6. **Eventos e grupos do setor:** link de inscrição em palestras, associações e grupos de faturamento.

Meta inicial realista: de 200 a 500 assinantes confirmados em 6 meses. Uma base pequena e qualificada (gestores e faturistas) vale mais do que milhares de e-mails frios.

## Fontes a configurar (`NEWSLETTER_SOURCES`)

Configure só feeds RSS/Atom oficiais que você conferiu no navegador. Os endereços mudam, e a pesquisa não confirmou o feed da ANS:

- Notícias da ANS (gov.br/ans): procure o link "RSS" na página de notícias.
- Imprensa Nacional / Diário Oficial: INLABS (XML do DOU) ou o feed da seção de interesse.
- Notícias de operadoras e entidades do setor que tenham RSS.

Sem fonte configurada, a edição sai só com o guia aprovado do blog. Se também não houver guia, ela não sai: o sistema não inventa notícia.

## Gráfico da semana

Ele só entra com um número tirado de uma fonte da curadoria (ex.: painéis e dados abertos da ANS), e sempre vem com o alerta "conferir os números na fonte". O "Índice de Glosas por Operadora" com dados próprios só vai existir quando a Insighta tiver clientes que autorizem o uso agregado e anônimo dos dados (cláusula em contrato e LGPD). Esse será o ativo mais valioso do boletim no futuro.

## Infraestrutura

- **Provedor de envio** (Brevo, Amazon SES ou SendGrid): conecte pelo SMTP do provedor (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`). Use um remetente próprio (`NEWSLETTER_FROM`, ex.: `boletim@` no domínio principal da Insighta, autenticado com SPF, DKIM e DMARC no provedor). O boletim é opt-in, então pode sair do domínio principal. A prospecção fria continua no domínio separado.
- **Webhook de bounces:** no provedor, aponte os eventos (hard bounce, spam, unsubscribe) para `https://<escritório>/webhooks/boletim?token=<NEWSLETTER_WEBHOOK_SECRET>`. O formato aceito é `{event, email}` ou uma lista desses objetos. Se o formato do provedor for diferente, um adaptador simples resolve.
- **Limite diário:** `NEWSLETTER_DAILY_SEND_CAP` precisa ser menor que o limite do plano do provedor. O que sobrar sai no dia seguinte.
- **Custos:** confira o plano gratuito e o limite diário do provedor na página oficial antes de escolher. Para algumas centenas de assinantes, os planos de entrada costumam bastar.

## Números para acompanhar (painel)

- Assinantes ativos, pendentes (não confirmaram), saídas, bounces e reclamações.
- Edições enviadas e quantidade por edição.
- Próximos passos de medição, ainda não implementados: abertura e cliques (eventos do provedor) e cliques no link da Insighta com UTM `utm_source=boletim`.
