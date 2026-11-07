import base64
import hmac
import io
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
from dashboard_metrics import (
    build_attention_items,
    build_category_performance,
    build_dashboard_kpis,
    build_top_products,
)
from offer_copy import MAX_CALLOUT_CHARS
from product_importer import MAX_LINKS_PER_BATCH, import_product_links
from shopee_affiliate_api import ShopeeAffiliateAPIError, check_connection as test_shopee_affiliate_api_connection
from publisher import (
    _redact as redact_secrets,
    enabled_channels,
    is_due,
    main as publish_offer,
    parse_bool,
    publication_cooldown_until,
    rank_candidates,
    score,
)
from pinterest_publisher import PinterestPublisherError, build_pin_payload
from social_copy import SocialCopyError, build_manual_copies
from spreadsheet_exports import build_exports

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
DATA_PATH = "data/products.csv"

COLS = [
    "id", "nome", "preco", "link", "imagem_url", "categoria", "chamada", "comissao",
    "ativo", "aprovado_publicacao", "status_publicacao", "frequencia_dias",
    "cliques", "pedidos", "comissao_estimada", "ultima_publicacao",
    "proxima_publicacao", "ultima_tentativa", "pinterest_status", "pinterest_pin_id",
]

st.set_page_config(page_title="Axadinhos Vippe", page_icon="👑", layout="wide")


def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def clean(df):
    df = df.copy()
    defaults = {
        "id": "", "nome": "", "preco": "", "link": "", "imagem_url": "",
        "categoria": "", "chamada": "", "comissao": 0, "ativo": True,
        "aprovado_publicacao": False, "status_publicacao": "pronto", "frequencia_dias": 3,
        "cliques": 0, "pedidos": 0, "comissao_estimada": 0,
        "ultima_publicacao": "", "proxima_publicacao": "",
        "ultima_tentativa": "", "pinterest_status": "pendente", "pinterest_pin_id": "",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
    df = df[COLS]
    for column in ["id", "cliques", "pedidos"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
    used_ids = set()
    next_id = max(1, int(df["id"].max()) + 1 if len(df) else 1)
    for index in df.index:
        product_id = int(df.at[index, "id"])
        if product_id <= 0 or product_id in used_ids:
            while next_id in used_ids:
                next_id += 1
            product_id = next_id
            next_id += 1
            df.at[index, "id"] = product_id
        used_ids.add(product_id)
    for column in ["comissao", "comissao_estimada", "frequencia_dias"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["frequencia_dias"] = df["frequencia_dias"].clip(1, 30).astype(int)
    df["ativo"] = df["ativo"].map(lambda value: parse_bool(value, default=True))
    df["aprovado_publicacao"] = df["aprovado_publicacao"].map(
        lambda value: parse_bool(value, default=False)
    )
    df["status_publicacao"] = df["status_publicacao"].fillna("pronto").astype(str).str.strip().str.casefold()
    df["chamada"] = df["chamada"].fillna("").astype(str)
    df["pinterest_status"] = df["pinterest_status"].fillna("pendente").astype(str).str.strip().str.casefold()
    df.loc[df["pinterest_pin_id"].fillna("").astype(str).str.strip().ne(""), "pinterest_status"] = "enviado"
    no_channel_receipt = (
        df["status_publicacao"].eq("enviado")
        & df["pinterest_pin_id"].fillna("").astype(str).str.strip().eq("")
    )
    df.loc[no_channel_receipt, "status_publicacao"] = "revisar"
    return df


def gh_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load():
    token = secret("github_token")
    if not token:
        return clean(pd.DataFrame(columns=COLS)), None, False
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}?ref={BRANCH}"
    response = requests.get(url, headers=gh_headers(token), timeout=20)
    if response.status_code == 404:
        return clean(pd.DataFrame(columns=COLS)), None, True
    response.raise_for_status()
    payload = response.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8-sig")
    return clean(pd.read_csv(io.StringIO(raw))), payload["sha"], True


def save(df, sha):
    token = secret("github_token")
    if not token:
        return False, "Configure github_token nos Secrets."
    csv = clean(df).to_csv(index=False)
    content = base64.b64encode(csv.encode("utf-8")).decode("ascii")
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}"
    body = {"message": "Atualiza base de produtos", "content": content, "branch": BRANCH}
    if sha:
        body["sha"] = sha
    response = requests.put(url, headers=gh_headers(token), json=body, timeout=30)
    if not response.ok:
        return False, response.text
    return True, "Base salva."


df, sha, cloud = load()

# Keep edits/import drafts between Streamlit reruns, but reload if the GitHub
# blob SHA changes so a scheduled publisher cannot be overwritten by a stale UI.
if "products_base_sha" not in st.session_state:
    st.session_state["products_base_sha"] = sha
    st.session_state["products_working_df"] = df.copy()
    st.session_state["products_editor_version"] = 0
elif st.session_state["products_base_sha"] != sha:
    st.session_state["products_base_sha"] = sha
    st.session_state["products_working_df"] = df.copy()
    st.session_state["products_editor_version"] += 1
    st.session_state["products_remote_refresh"] = True

st.title("👑 Axadinhos Vippe")
st.caption("Produtos, aprovação manual, conteúdo copiável e Pins do Pinterest")
if st.session_state.pop("products_remote_refresh", False):
    st.warning("A base mudou no GitHub. Recarregamos os dados mais recentes para evitar sobrescrever atualizações.")
if not cloud:
    st.warning("A visualização está disponível, mas github_token precisa estar configurado para salvar produtos.")

panel, products, ads, channels_tab = st.tabs(["📊 Painel", "📋 Produtos", "📢 Anúncios", "📣 Canais"])

with panel:
    dashboard = build_dashboard_kpis(df)
    st.subheader("Visão geral")
    st.caption("Resumo do catálogo e do desempenho registrado. Os indicadores não publicam nem alteram produtos.")
    with st.container(border=True):
        product_col, approved_col, attention_col, commission_col = st.columns(4)
        product_col.metric("Produtos no catálogo", dashboard["products"])
        approved_col.metric("Ativos e aprovados", dashboard["active_approved"])
        attention_col.metric("Produtos com pendências", dashboard["attention"])
        commission_col.metric(
            "Comissão estimada",
            f"R$ {dashboard['commission']:.2f}".replace(".", ","),
        )

    with st.container(border=True):
        st.markdown("**Atividade registrada**")
        clicks_col, orders_col, pinterest_col = st.columns(3)
        clicks_col.metric("Cliques", dashboard["clicks"])
        orders_col.metric("Pedidos", dashboard["orders"])
        pinterest_col.metric("Pins Pinterest", dashboard["pinterest_pins"])

    attention_col, performance_col = st.columns([1, 1.25], gap="large")
    with attention_col:
        with st.container(border=True):
            st.subheader("Atenção agora")
            attention_items = build_attention_items(df, limit=6)
            if attention_items.empty:
                st.success("Nenhuma pendência de envio, aprovação, ativação ou dados incompletos.")
            else:
                st.dataframe(attention_items, width="stretch", hide_index=True)
                if dashboard["attention"] > len(attention_items):
                    st.caption(
                        f"Mostrando {len(attention_items)} de {dashboard['attention']} itens. "
                        "Consulte a aba Produtos para revisar o restante."
                    )
            st.caption("Esta lista é informativa; os estados só mudam quando você os edita na aba Produtos.")

    with performance_col:
        with st.container(border=True):
            st.subheader("Produtos com atividade")
            top_products = build_top_products(df, limit=5)
            if top_products.empty:
                st.info("Ainda não há cliques, pedidos ou comissões registrados para comparar produtos.")
            else:
                st.dataframe(top_products, width="stretch", hide_index=True)
                st.caption("A pontuação usa o mesmo cálculo do publicador para manter a prioridade consistente.")

            st.markdown("**Desempenho por categoria**")
            category_metrics = build_category_performance(df)
            if not category_metrics.empty and int(category_metrics[["Cliques", "Pedidos"]].to_numpy().sum()) > 0:
                st.bar_chart(
                    category_metrics.head(8).set_index("Categoria")[["Cliques", "Pedidos"]],
                    horizontal=True,
                    height=260,
                    width="stretch",
                )
            else:
                st.info("O gráfico aparecerá quando houver cliques ou pedidos reais registrados.")

    st.divider()
    st.subheader("Fila manual estimada")
    st.caption(
        "Prévia somente leitura dos produtos elegíveis para o Pinterest. Os textos de WhatsApp, Instagram "
        "e TikTok são preparados manualmente na aba Anúncios e não entram nesta fila."
    )
    manual_channels = enabled_channels({
        "PINTEREST_PUBLISH_ENABLED": parse_bool(
            secret("pinterest_publish_enabled", False), default=False
        ),
    })
    manual_credentials_ready = bool(secret("github_token")) and bool(manual_channels) and all(
        secret("pinterest_access_token") and secret("pinterest_board_id")
        for channel in manual_channels
    )
    if not manual_channels:
        st.info("Habilite o opt-in manual do Pinterest na aba Canais para visualizar a fila de Pins.")
    elif not manual_credentials_ready:
        st.warning("A fila ficará disponível quando o acesso ao GitHub e os Secrets do Pinterest estiverem configurados.")
    else:
        queue_now = datetime.now(timezone.utc)
        due_items = rank_candidates(df, queue_now, manual_channels)
        cooldown_until = publication_cooldown_until(df, hours=4)
        if cooldown_until is not None and queue_now < cooldown_until:
            st.info(
                "Intervalo global ativo; a fila não poderá publicar antes de "
                f"{cooldown_until.isoformat()}."
            )
        if due_items:
            queue_rows = []
            for position, (_, row) in enumerate(due_items, start=1):
                queue_rows.append({
                    "Ordem": position,
                    "ID": int(row["id"]),
                    "Produto": row["nome"],
                    "Preço": row["preco"],
                    "Pinterest": row["pinterest_status"],
                    "Score": round(score(row), 2),
                })
            st.dataframe(
                pd.DataFrame(queue_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "O publicador cria no máximo um Pin por execução; o workflow agendado permanece separado e bloqueado por opt-in."
            )
        else:
            st.info("Nenhuma oferta está ativa, aprovada e elegível para o Pinterest.")

with products:
    st.subheader("📋 Planilha de produtos")
    st.caption(
        "Cole links HTTPS da Shopee em lote. O importador tenta preencher automaticamente nome, "
        "preço, foto e categoria lendo metadados, HTML e JSON/estado embutido no código-fonte público, "
        "sem executar JavaScript. Links originais de afiliado são preservados; confira os dados antes de salvar."
    )
    st.info(
        "Importações novas entram como inativas e sem aprovação. Confira nome, preço, imagem e destino; "
        "ative e aprove cada produto somente depois da revisão. Máximo de "
        f"{MAX_LINKS_PER_BATCH} links por lote."
    )

    api_app_id = secret("shopee_affiliate_app_id")
    api_secret = secret("shopee_affiliate_secret")
    api_admin_pin = secret("shopee_affiliate_admin_pin")
    if not api_app_id or not api_secret or not api_admin_pin:
        st.session_state["shopee_affiliate_api_connected"] = False
    with st.expander("🔗 Conectar API de Afiliados Shopee", expanded=False):
        if not api_app_id or not api_secret or not api_admin_pin:
            st.info(
                "Quando a Shopee liberar o acesso, configure os dados abaixo em Manage app → Settings → Secrets no Streamlit Cloud. "
                "O PIN protege as credenciais privadas porque o painel é público. Não os insira na planilha nem no código."
            )
            st.code(
                'shopee_affiliate_app_id = "SEU_APP_ID"\n'
                'shopee_affiliate_secret = "SUA_SECRET"\n'
                'shopee_affiliate_admin_pin = "ESCOLHA_UM_PIN_LONGO_E_PRIVADO"',
                language="toml",
            )
        else:
            api_pin_input = st.text_input(
                "PIN administrativo da API",
                type="password",
                key="shopee_affiliate_admin_pin_input",
            )
            st.caption("Credenciais localizadas nos Secrets. O teste abaixo faz apenas uma consulta de leitura.")
            if st.button("🔌 Conectar / testar API", key="test_shopee_affiliate_api"):
                if not hmac.compare_digest(str(api_pin_input), str(api_admin_pin)):
                    st.session_state["shopee_affiliate_api_connected"] = False
                    st.session_state["shopee_affiliate_api_error"] = "PIN administrativo incorreto."
                else:
                    try:
                        test_shopee_affiliate_api_connection(str(api_app_id), str(api_secret))
                        st.session_state["shopee_affiliate_api_connected"] = True
                        st.session_state["shopee_affiliate_api_message"] = "Conexão validada. A próxima importação usará a API quando o itemId for identificável."
                        st.session_state.pop("shopee_affiliate_api_error", None)
                    except ShopeeAffiliateAPIError as exc:
                        st.session_state["shopee_affiliate_api_connected"] = False
                        st.session_state["shopee_affiliate_api_error"] = str(exc)
            if st.session_state.get("shopee_affiliate_api_connected"):
                st.success(st.session_state.get("shopee_affiliate_api_message", "API conectada."))
            if st.session_state.get("shopee_affiliate_api_error"):
                st.error(st.session_state["shopee_affiliate_api_error"])

    editor_key = f"products_editor_{st.session_state['products_editor_version']}"
    working_df = clean(st.session_state["products_working_df"])
    edited = st.data_editor(
        working_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=editor_key,
        column_config={
            "link": st.column_config.LinkColumn("Link Shopee"),
            "imagem_url": st.column_config.LinkColumn("Link da foto"),
            "chamada": st.column_config.TextColumn(
                "Chamada personalizada",
                max_chars=MAX_CALLOUT_CHARS,
                help="Opcional: uma frase curta e verificável. O sistema sempre acrescenta preço, link e aviso de afiliado.",
            ),
            "ativo": st.column_config.CheckboxColumn("Ativo"),
            "aprovado_publicacao": st.column_config.CheckboxColumn("Aprovado para publicação"),
            "status_publicacao": st.column_config.SelectboxColumn(
                "Estado da publicação", options=["pronto", "enviando", "enviado", "revisar"]
            ),
            "pinterest_status": st.column_config.SelectboxColumn(
                "Status Pinterest", options=["pendente", "enviado", "revisar"]
            ),
            "frequencia_dias": st.column_config.NumberColumn("Dias", min_value=1, max_value=30),
            "comissao_estimada": st.column_config.NumberColumn("Comissão", format="R$ %.2f"),
        },
        disabled=["id", "ultima_publicacao", "proxima_publicacao", "ultima_tentativa", "pinterest_pin_id"],
    )
    edited = clean(edited)
    st.caption(
        "Após uma falha ambígua, confira manualmente cada destino antes de mudar seu status para pendente; "
        "isso evita republicações duplicadas."
    )
    st.session_state["products_working_df"] = edited

    with st.form("bulk_import_form", clear_on_submit=True):
        pasted_links = st.text_area(
            "Links da Shopee (um por linha ou separados por espaço/vírgula)",
            height=150,
            placeholder="https://s.shopee.com.br/...\nhttps://shp.ee/...",
        )
        import_submitted = st.form_submit_button("🔎 Buscar dados e adicionar à tabela")

    if import_submitted:
        api_connected = st.session_state.get("shopee_affiliate_api_connected", False)
        api_credentials = (
            (str(api_app_id), str(api_secret)) if api_connected and api_app_id and api_secret else None
        )
        result = import_product_links(
            pasted_links,
            existing_links=edited["link"].tolist(),
            affiliate_api_credentials=api_credentials,
        )
        if result["products"]:
            additions = pd.DataFrame(result["products"])
            combined = pd.concat([edited, additions], ignore_index=True)
            st.session_state["products_working_df"] = clean(combined)
            st.session_state["products_editor_version"] += 1
            st.session_state["bulk_import_report"] = {
                "added": len(result["products"]),
                "duplicates": result["duplicates"],
                "invalid": result["invalid"],
                "incomplete": result["incomplete"],
                "diagnostics": result["diagnostics"],
                "limit_reached": result["limit_reached"],
            }
            st.rerun()
        else:
            if not pasted_links.strip():
                st.warning("Cole pelo menos um link para importar.")
            elif result["duplicates"] or result["invalid"]:
                st.warning(
                    f"Nenhum produto novo adicionado. Duplicados: {len(result['duplicates'])}; "
                    f"links que não são HTTPS da Shopee: {len(result['invalid'])}."
                )
            else:
                st.warning("Nenhum link Shopee novo foi encontrado no lote.")
            if result["invalid"]:
                st.caption("Links ignorados por domínio/formato:")
                st.code("\n".join(result["invalid"][:10]))

    report = st.session_state.pop("bulk_import_report", None)
    if report:
        st.success(
            f"{report['added']} produto(s) adicionado(s) à tabela como inativos e não aprovados. "
            "Revise os dados e clique em Salvar produtos quando estiver pronto."
        )
        if report["incomplete"]:
            st.warning(
                f"A Shopee não forneceu nome e/ou preço em {len(report['incomplete'])} link(s). "
                "Esses campos ficaram em branco na tabela e precisam ser revisados antes da aprovação."
            )
        if report.get("diagnostics"):
            labels = {
                "nome": "nome",
                "preco": "preço",
                "imagem_url": "foto",
                "categoria": "categoria",
            }
            status_labels = {
                "completo": "Nome e preço encontrados",
                "parcial": "Alguns metadados encontrados",
                "indisponivel": "A página não expôs metadados legíveis no código-fonte HTML inicial",
                "redirecionamento_bloqueado": "Redirecionamento externo bloqueado por segurança",
                "falha_de_conexao": "Não foi possível conectar à página",
                "falha_ao_ler_pagina": "Não foi possível ler a página",
                "resposta_nao_html": "A resposta não era uma página HTML",
            }
            with st.expander("🔍 Resultado da leitura automática por link", expanded=bool(report["incomplete"])):
                for item in report["diagnostics"]:
                    status = item.get("status", "indisponivel")
                    status_text = status_labels.get(status, f"Resposta da página: {status}")
                    st.markdown(f"**{item['link']}**")
                    st.caption(status_text)
                    if item.get("api_used"):
                        st.caption("Dados enriquecidos pela Shopee Affiliate Open API.")
                    found = [labels[field] for field in item.get("extraidos", [])]
                    missing = [labels[field] for field in item.get("faltando", [])]
                    if found:
                        st.write("Encontrados: " + ", ".join(found))
                    if missing:
                        st.warning("Faltando na tabela: " + ", ".join(missing))
                st.info(
                    "A importação lê HTML e dados JSON/estado embutido na resposta pública, mas não executa "
                    "JavaScript nem contorna login, CAPTCHA ou bloqueios. Se a Shopee montar os dados apenas "
                    "após chamadas do navegador, nome/preço podem não estar no código-fonte recebido; use o "
                    "link direto do produto e preencha manualmente os campos que continuarem vazios. "
                    "Os links importados permanecem inativos e sem aprovação."
                )
        if report["duplicates"]:
            st.info(f"{len(report['duplicates'])} link(s) duplicado(s) foram ignorados.")
        if report["invalid"]:
            st.warning(f"{len(report['invalid'])} link(s) que não são Shopee foram ignorados.")
            st.code("\n".join(report["invalid"][:10]))
        if report["limit_reached"]:
            st.info(f"O lote foi limitado a {MAX_LINKS_PER_BATCH} links. Envie o restante em outro lote.")

    if st.button("💾 Salvar produtos", type="primary"):
        ok, message = save(edited, sha)
        (st.success if ok else st.error)(message)
        if ok:
            st.rerun()

    st.caption("Baixe a tabela nos formatos CSV, Excel, TSV ou JSON.")
    exports = build_exports(clean(edited))
    download_columns = st.columns(len(exports))
    for column, (format_name, export) in zip(download_columns, exports.items()):
        column.download_button(
            f"⬇️ {format_name}",
            data=export["data"],
            file_name=export["file_name"],
            mime=export["mime"],
            key=f"download_products_{format_name.casefold()}",
            use_container_width=True,
        )

with ads:
    if len(df):
        product_labels = {
            f"{int(row['id'])} — {row['nome']}": index
            for index, row in df.iterrows()
        }
        selected_label = st.selectbox(
            "Produto para preparar",
            list(product_labels),
            key="manual_copy_product_select",
        )
        selected_row = df.loc[product_labels[selected_label]]
        st.caption(
            "Escolha um formato e copie o rascunho. Esta aba não envia mensagens nem publica conteúdo. "
            "A chamada personalizada, o preço e o link cadastrado são mantidos quando aplicável."
        )
        if not (
            parse_bool(selected_row.get("ativo", False), default=False)
            and parse_bool(selected_row.get("aprovado_publicacao", False), default=False)
        ):
            st.info("Este item ainda não está ativo e aprovado. O texto é apenas uma prévia; revise e aprove antes de publicar por conta própria.")
        try:
            manual_copies = build_manual_copies(selected_row)
        except SocialCopyError as exc:
            st.warning(str(exc))
        else:
            whatsapp_tab, instagram_tab, tiktok_tab = st.tabs([
                "WhatsApp — mensagem",
                "Instagram — legenda",
                "TikTok — texto manual",
            ])
            with whatsapp_tab:
                st.caption("Rascunho copiável. Compartilhe somente com pessoas que aceitaram receber ofertas e respeite pedidos para parar.")
                st.code(manual_copies["whatsapp"], language=None)
            with instagram_tab:
                st.caption("A URL é preservada no texto, mas legendas do feed não tornam URLs clicáveis. Atualize o link do perfil se usar uma chamada para a bio.")
                st.code(manual_copies["instagram"], language=None)
            with tiktok_tab:
                st.caption("A URL afiliada fica separada do texto. Use-a somente em um campo/perfil permitido; não sobreponha links ao vídeo e ative a divulgação comercial no app TikTok.")
                st.code(manual_copies["tiktok"], language=None)
                st.markdown("**URL afiliada original — separada da legenda:**")
                st.code(manual_copies["affiliate_link"], language=None)
    else:
        st.info("Cadastre produtos primeiro.")


with channels_tab:
    st.subheader("📣 Canais")
    st.write(
        "WhatsApp, Instagram e TikTok estão disponíveis apenas para preparar textos copiáveis. "
        "O app não tem conexão de envio por API, não publica nesses canais e não guarda listas de contatos."
    )
    with st.container(border=True):
        st.markdown("**Preparação manual disponível**")
        st.write("WhatsApp: mensagem com aviso de afiliado e link original; compartilhe apenas com quem consentiu em receber ofertas.")
        st.write("Instagram: legenda com aviso e link original em texto; links em legendas do feed não são clicáveis.")
        st.write("TikTok: texto sem URL inserida na legenda e URL afiliada exibida separadamente; ative a divulgação comercial no app antes de publicar.")

    github_token = secret("github_token")
    pinterest_token = secret("pinterest_access_token")
    pinterest_board_id = secret("pinterest_board_id")
    pinterest_enabled = parse_bool(secret("pinterest_publish_enabled", False), default=False)

    st.divider()
    st.subheader("Pinterest — Pin linkado")
    st.caption("Este é o único canal conectado para publicação real. Cada Pin leva ao link afiliado original. O botão cria conteúdo público, sem modo de teste.")
    st.write("GitHub — acesso à base:", "✅" if github_token else "❌")
    st.write("Pinterest — OAuth token:", "✅" if pinterest_token else "❌")
    st.write("Pinterest — Board ID:", "✅" if pinterest_board_id else "❌")
    st.write("Pinterest — publicação manual habilitada:", "✅" if pinterest_enabled else "⏸️")

    with st.expander("Configurar Pinterest nos Streamlit Secrets"):
        st.caption("Adicione as credenciais em Manage app → Settings → Secrets. Não cole tokens no chat, na planilha nem no código.")
        st.code(
            'pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"\n'
            'pinterest_board_id = "ID_NUMERICO_DO_BOARD"\n'
            'pinterest_publish_enabled = false',
            language="toml",
        )

    if not github_token:
        st.warning("Publicação bloqueada: configure github_token para salvar o estado no CSV do GitHub.")
    if not pinterest_enabled:
        st.info("A publicação manual do Pinterest está desativada por padrão. Habilite-a somente quando estiver pronto para criar Pins reais.")
    if pinterest_enabled and (not pinterest_token or not pinterest_board_id):
        st.warning("Pinterest foi habilitado, mas faltam pinterest_access_token e/ou pinterest_board_id nos Secrets.")

    requested_channels = enabled_channels({"PINTEREST_PUBLISH_ENABLED": pinterest_enabled})
    if len(df):
        product_labels = {
            f"{int(row['id'])} — {row['nome']}": index
            for index, row in df.iterrows()
        }
        selected_label = st.selectbox(
            "Produto para publicação no Pinterest",
            list(product_labels),
            key="channel_product_select",
        )
        selected_row = df.loc[product_labels[selected_label]]
        now = datetime.now(timezone.utc)
        product_is_approved = (
            parse_bool(selected_row.get("ativo", True), default=True)
            and parse_bool(selected_row.get("aprovado_publicacao", False), default=False)
        )
        product_is_due = is_due(selected_row, now, requested_channels)
        cooldown_until = publication_cooldown_until(df, hours=4)
        cooldown_active = cooldown_until is not None and now < cooldown_until

        preflight_errors = []
        if requested_channels and pinterest_token and pinterest_board_id and product_is_approved:
            try:
                build_pin_payload(selected_row, str(pinterest_board_id))
            except PinterestPublisherError as exc:
                preflight_errors.append("Pinterest: " + str(exc))

        channel_credentials_ready = bool(requested_channels and pinterest_token and pinterest_board_id)
        can_publish = bool(
            github_token
            and channel_credentials_ready
            and product_is_approved
            and product_is_due
            and not cooldown_active
            and not preflight_errors
        )

        if not product_is_approved:
            st.warning("Publicação bloqueada: ative e aprove este produto somente depois de revisar nome, preço, imagem e link.")
        elif requested_channels and not product_is_due:
            st.warning("Este produto ainda não está elegível. Confira aprovação, estado Pinterest e frequência na tabela.")
        if cooldown_active:
            st.info(f"Intervalo global mínimo de quatro horas ativo até {cooldown_until.isoformat()}.")
        for error in preflight_errors:
            st.warning("Pré-validação bloqueou a publicação antes do envio. " + error)

        if can_publish:
            st.caption("Destino: Pinterest. A ação cria um Pin público com a URL original de afiliado e registra o recibo no CSV.")
        button_label = "🚀 Criar Pin linkado no Pinterest" if requested_channels else "🔒 Habilite a publicação do Pinterest"
        if st.button(button_label, type="primary", disabled=not can_publish):
            publish_env = {
                "PUBLISH_CONFIRMED": "true",
                "GH_AUTOMATION_TOKEN": str(github_token),
                "GITHUB_TOKEN": str(github_token),
                "PINTEREST_PUBLISH_ENABLED": str(pinterest_enabled).lower(),
                "PINTEREST_ACCESS_TOKEN": str(pinterest_token or ""),
                "PINTEREST_BOARD_ID": str(pinterest_board_id or ""),
            }
            try:
                publish_offer(
                    environ=publish_env,
                    session=requests,
                    product_id=selected_row["id"],
                )
                st.success("Pin criado no Pinterest e estado registrado na base do GitHub.")
                st.rerun()
            except Exception as exc:
                st.error(
                    "Publicação bloqueada ou falhou: "
                    + redact_secrets(exc, github_token, pinterest_token)
                )
    else:
        st.info("Cadastre produtos primeiro.")
