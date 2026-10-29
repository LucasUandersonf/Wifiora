"""Páginas institucionais (autoridade editorial + LGPD). Fonte única para o HTML do FastAPI e o portal Next.js.

Termos e Privacidade são MINUTAS: revise com um advogado antes de lançar. Enquanto os dados da empresa
não estiverem configurados (COMPANY_LEGAL_NAME, COMPANY_CNPJ, CONTACT_EMAIL, DPO_EMAIL), a página mostra a pendência.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

FOOTER_LINKS = [
    ("Sobre", "/sobre"),
    ("Metodologia", "/metodologia"),
    ("Política editorial", "/politica-editorial"),
    ("Solicitar correção", "/correcoes"),
    ("Termos de uso", "/termos"),
    ("Privacidade", "/privacidade"),
]


def _company() -> dict[str, str]:
    st = get_settings()
    return {
        "brand": st.brand_name,
        "legal": st.company_legal_name or "[razão social — configurar COMPANY_LEGAL_NAME]",
        "cnpj": st.company_cnpj or "[CNPJ — configurar COMPANY_CNPJ]",
        "email": st.contact_email or "[e-mail — configurar CONTACT_EMAIL]",
        "dpo": st.dpo_email or st.contact_email or "[e-mail do encarregado — configurar DPO_EMAIL]",
        "city": st.company_city or "[cidade/UF — configurar COMPANY_CITY]",
    }


def company_configured() -> bool:
    st = get_settings()
    return bool(st.company_legal_name and st.company_cnpj and st.contact_email)


def _pages(c: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        "sobre": {
            "title": "Sobre",
            "description": f"O que é o {c['brand']}, quem mantém e como o portal se sustenta.",
            "sections": [
                {"h": "O que fazemos", "p": [
                    f"O {c['brand']} publica comparativos de produtos e serviços B2B do mercado brasileiro com dados estruturados e verificados. "
                    "Cada número tem a fonte oficial de onde veio, a data em que foi conferido e o histórico de alterações.",
                    "Os dados também são publicados em formato legível por máquinas (JSON-LD, padrão Schema.org), para que buscadores e assistentes de IA possam usá-los e citá-los corretamente.",
                ]},
                {"h": "Quem mantém", "p": [f"{c['legal']}, CNPJ {c['cnpj']}, {c['city']}. Contato: {c['email']}."]},
                {"h": "Como nos sustentamos", "list": [
                    "Indicação de interessados (botão “Solicitar demonstração”), sempre com o consentimento de quem preenche.",
                    "Perfis verificados, em que a empresa mantém seus dados atualizados com prioridade.",
                    "Acesso pago à base de dados via API.",
                ], "p": ["Nenhum pagamento altera dados, ordem de exibição ou critérios de avaliação. Conteúdo patrocinado, se existir, será identificado como tal."]},
            ],
        },
        "metodologia": {
            "title": "Metodologia",
            "description": "Como coletamos, verificamos e atualizamos cada dado publicado.",
            "sections": [
                {"h": "1. Fontes", "p": ["Usamos fontes oficiais e públicas: site do fornecedor, página de preços, documentação e cadastros públicos (como a consulta de CNPJ). A coleta respeita o robots.txt de cada site."]},
                {"h": "2. Verificação literal", "p": [
                    "Cada valor publicado precisa vir acompanhado de um trecho copiado da fonte. Um programa confere se esse trecho existe na página e se o valor aparece dentro dele. "
                    "A porcentagem de valores confirmados assim é o grounding, exibido em cada ficha. Valor sem evidência não é publicado."
                ]},
                {"h": "3. Controle de qualidade", "p": ["Antes da publicação, cada entrega passa por regras automáticas (fonte presente, formato correto, valores fora do padrão do mercado) e por uma avaliação de qualidade. Entregas reprovadas são refeitas."]},
                {"h": "4. Revisão humana", "p": ["Fichas com o selo “Validado por especialista” foram conferidas por uma pessoa, com nome e data registrados."]},
                {"h": "5. Critérios editoriais", "p": ["As avaliações mostram apenas critérios objetivos (por exemplo, “emite NF-e”), calculados a partir dos dados verificados. Não publicamos notas, estrelas ou opiniões."]},
                {"h": "6. Atualização e histórico", "p": ["Os dados são reverificados periodicamente. Cada alteração gera uma nova versão, visível na ficha, com os campos que mudaram e a data."]},
                {"h": "Uso de inteligência artificial", "p": ["A coleta e a organização são feitas com auxílio de agentes de IA. A IA não grava dados diretamente: só é publicado o que passa pela verificação literal e pelo controle de qualidade."]},
            ],
        },
        "politica-editorial": {
            "title": "Política editorial",
            "description": "Independência, conflitos de interesse e correções.",
            "sections": [
                {"h": "Independência", "p": ["Fornecedores não pagam para aparecer, nem para mudar dados ou posição. Relações comerciais (indicações, perfis verificados, API) não influenciam o conteúdo."]},
                {"h": "Identificação de conteúdo comercial", "p": ["Qualquer conteúdo patrocinado será marcado de forma visível como “Patrocinado”."]},
                {"h": "Correções", "p": [
                    "Encontrou um erro? Use a página Solicitar correção, informando a fonte oficial. Analisamos cada pedido e, se procedente, corrigimos e registramos a mudança no histórico da ficha.",
                    "Buscamos responder em até 5 dias úteis.",
                ]},
                {"h": "Contato editorial", "p": [c["email"]]},
            ],
        },
        "termos": {
            "title": "Termos de uso",
            "description": "Condições de uso do portal, dos dados e da API.",
            "draft": True,
            "sections": [
                {"h": "1. Quem somos", "p": [f"Este portal é mantido por {c['legal']}, CNPJ {c['cnpj']}."]},
                {"h": "2. Licença dos dados", "p": ["Os dados publicados nas páginas estão sob a licença Creative Commons Atribuição 4.0 (CC BY 4.0): podem ser reutilizados com citação da fonte. O acesso em volume pela API está sujeito a contrato e limites de uso próprios."]},
                {"h": "3. Natureza das informações", "p": ["As informações são compiladas de fontes públicas e podem mudar a qualquer momento. Elas não substituem a confirmação com o fornecedor nem constituem recomendação de compra, aconselhamento fiscal, jurídico ou médico."]},
                {"h": "4. Responsabilidade", "p": ["Empregamos esforços razoáveis para manter os dados corretos, mas não garantimos ausência de erros. Na extensão permitida pela lei, não nos responsabilizamos por decisões tomadas exclusivamente com base no portal."]},
                {"h": "5. Uso proibido", "list": ["Tentar acessar áreas restritas ou burlar limites da API.", "Enviar conteúdo falso pelos formulários.", "Apresentar os dados como se fossem de outra autoria."]},
                {"h": "6. Foro", "p": [f"Fica eleito o foro da comarca de {c['city']}."]},
            ],
        },
        "privacidade": {
            "title": "Política de privacidade",
            "description": "Como tratamos dados pessoais, conforme a LGPD (Lei 13.709/2018).",
            "draft": True,
            "sections": [
                {"h": "Controlador", "p": [f"{c['legal']}, CNPJ {c['cnpj']}. Encarregado de dados (DPO): {c['dpo']}."]},
                {"h": "Quais dados coletamos", "list": [
                    "Formulário “Solicitar demonstração”: nome, e-mail, telefone (opcional), empresa, porte e mensagem.",
                    "Formulário “Solicitar correção”: nome, e-mail, empresa e mensagem.",
                    "Registros técnicos de acesso (endereço IP e data), pelo prazo exigido pelo Marco Civil da Internet.",
                ]},
                {"h": "Para que usamos", "list": [
                    "Demonstração: encaminhar seu pedido ao fornecedor escolhido. Base legal: consentimento (art. 7º, I), dado no próprio formulário.",
                    "Correção: analisar e responder o pedido. Base legal: legítimo interesse (art. 7º, IX).",
                ]},
                {"h": "Compartilhamento", "p": ["Os dados do pedido de demonstração são compartilhados apenas com o fornecedor que você escolheu e somente com seu consentimento. Não vendemos dados pessoais."]},
                {"h": "Cookies", "p": ["O portal não usa cookies de rastreamento ou publicidade."]},
                {"h": "Prazo de guarda", "p": ["Mantemos os dados pelo tempo necessário à finalidade ou ao cumprimento de obrigação legal, e depois os eliminamos."]},
                {"h": "Seus direitos", "p": [f"Você pode pedir confirmação, acesso, correção, anonimização, portabilidade, eliminação e revogação do consentimento (art. 18 da LGPD) pelo e-mail {c['dpo']}."]},
            ],
        },
        "correcoes": {
            "title": "Solicitar correção",
            "description": "Encontrou um dado errado? Envie a correção com a fonte oficial.",
            "sections": [
                {"p": [
                    "Se você representa uma empresa listada ou encontrou um dado desatualizado, envie o pedido abaixo com o link da fonte oficial. "
                    "Pedidos com fonte são analisados mais rápido. Toda correção aceita fica registrada no histórico da ficha."
                ]},
            ],
            "form": "correction",
        },
    }


def institutional_page(slug: str) -> dict[str, Any] | None:
    page = _pages(_company()).get(slug)
    if page is None:
        return None
    return {"slug": slug, **page, "company_configured": company_configured()}


def institutional_slugs() -> list[str]:
    return list(_pages(_company()))
