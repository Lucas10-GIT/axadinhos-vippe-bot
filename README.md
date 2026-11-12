# Axadinhos Vippe Bot

Aplicativo Streamlit para preparar ofertas de afiliados para Pinterest, WhatsApp, Instagram e TikTok. A publicação automatizada permanece somente no Pinterest e exige aprovação manual do produto; WhatsApp, Instagram e TikTok são preparação manual, sem postagem por API. O catálogo operacional fica em `data/products.csv` no GitHub.

## Programas afiliados aceitos

O importador aceita links já gerados no **Amazon Associados** e na **eBay Partner Network (EPN)**. Ele preserva a URL inteira, inclusive os parâmetros de atribuição, mas não cria links afiliados, não abre páginas de produto, não raspa HTML, não segue redirecionamentos e não chama APIs de afiliados. Links diretos da Amazon precisam ter `tag`; links `amzn.to` também são aceitos. Links diretos do eBay precisam incluir o `campid` EPN de 10 dígitos; o encurtador oficial `ebay.us` também é aceito. O usuário deve gerar/copiar os links no portal do respectivo programa.

Links importados entram com dados vazios, inativos, sem aprovação e sem autorização de imagem. Preencha título/categoria/imagem manualmente e confira a atribuição antes de salvar. Para Amazon, o gerador **não inclui preço estático** e bloqueia valores monetários explícitos em título/chamada: preço e disponibilidade devem ser consultados na página Amazon, a menos que no futuro exista API licenciada configurada. A plataforma não usa imagens de produto Amazon por scraping. Só marque **Tenho direito de usar a imagem/arte** se o material for seu ou houver autorização válida.

Para eBay, antes de preparar conteúdo próprio ou publicar um Pin, marque **Aprovação escrita EPN para promoção/conteúdo** somente se essa aprovação tiver sido obtida. O texto de WhatsApp e o handoff ficam bloqueados até a aprovação escrita específica da EPN para mensagens. Os links eBay não são alterados pelo app.

A Shopee foi retirada do fluxo ativo. Os quatro registros anteriores foram preservados, sem possibilidade de publicação, em `data/archive/shopee_products_legacy.csv`; o catálogo principal não os carrega.

## Conteúdo copiável

A aba **Anúncios** monta rascunhos com disclosure próprio por programa e mantém o link original. WhatsApp leva o link no texto, com consentimento do destinatário; Instagram usa CTA para a bio e mostra a URL separada; TikTok mantém a URL separada e lembra a opção nativa de divulgação comercial. Para eBay, o conteúdo permanece condicionado à aprovação EPN; a mensageria requer autorização adicional.

No Amazon Associados, a cópia usa a declaração exigida pelo contrato brasileiro: “Como participante do Programa de Associados da Amazon, sou remunerado pelas compras qualificadas efetuadas”. Para eBay, o texto identifica a relação de afiliado e a possível comissão. Confirme ainda as regras atuais da plataforma social e as exigências legais aplicáveis.

O webhook opcional de WhatsApp é apenas handoff manual de um rascunho aprovado para endpoint controlado pelo usuário. Vem desligado, não envia mensagens, não roda no cron, não recebe contatos e usa HMAC, chave de idempotência e `send=false`. Envio real exigiria integração oficial separada, opt-in/opt-out e demais políticas da Meta.

## Publicação no Pinterest

O publicador usa a API oficial v5 e somente cria Pins linkados ao link afiliado original. Um Pin precisa de produto ativo e aprovado, título revisado, URL afiliada válida, imagem pública HTTPS com autorização confirmada, Board ID e credenciais válidas. Para EPN, também é exigida confirmação de aprovação escrita do conteúdo/método promocional. Mantenha os Pins originais e relevantes e evite conteúdo repetitivo ou em grande volume.

O GitHub Actions publica exclusivamente no Pinterest, no máximo um Pin por execução. O agendamento a cada quatro horas fica bloqueado até que duas variáveis de opt-in sejam ativadas; a ação manual também exige confirmação. Resultados ambíguos entram em revisão e não são reenviados automaticamente.

## Dados e painel

O painel reúne produtos, atividade registrada, comissão estimada e pendências. **Atenção agora** mostra dados incompletos, links sem rastreamento válido, autorização de imagem ausente e aprovações EPN pendentes. As visões rápidas do catálogo são somente leitura; não alteram aprovação nem elegibilidade. A tabela pode ser baixada em CSV, Excel, TSV ou JSON.

## APIs e credenciais

Não há segredo Amazon ou eBay necessário para importar links prontos. A API não está integrada. A Creators API da Amazon exige participação no programa do marketplace-alvo, cadastro para acesso e credenciais; a documentação atualmente lista requisito de 10 vendas qualificadas nos últimos 30 dias. A Browse API do eBay requer token de aplicação e não substitui a geração de URLs EPN rastreadas. Não tente contornar aprovação por scraping.

Veja [CONFIGURAR-SECRETS.md](CONFIGURAR-SECRETS.md) para configurar GitHub, Pinterest e o webhook opcional. Streamlit Cloud e GitHub Actions têm armazenamentos de Secrets separados.

## Testes locais

Os testes usam sessões falsas; não fazem chamadas reais aos programas de afiliados, GitHub, Pinterest ou webhook. Eles cobrem preservação de link, validação de tags/campaign ID, disclosures, gates de aprovação e estados multicanal.

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

## Fontes oficiais

- [Amazon Associates Brasil — Contrato Operacional](https://associados.amazon.com.br/help/operating/agreement/)
- [Amazon Associates Brasil — Políticas do Programa](https://associados.amazon.com.br/help/operating/policies/)
- [Amazon Creators API — introdução e requisitos](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction)
- [eBay Partner Network — Network Agreement](https://partnernetwork.ebay.com/page/network-agreement)
- [eBay EPN — criar link afiliado](https://partnernetwork.ebay.com/resources/create-your-affiliate-link)
- [eBay — estrutura de link rastreado](https://developer.ebay.com/api-docs/buy/static/ref-epn-link.html)
