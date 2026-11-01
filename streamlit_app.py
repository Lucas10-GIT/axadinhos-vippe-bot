import base64
import hmac
import io

import pandas as pd
import requests
import streamlit as st
from product_importer import MAX_LINKS_PER_BATCH, import_product_links
from shopee_affiliate_api import ShopeeAffiliateAPIError, check_connection as test_shopee_affiliate_api_connection
from publish_telegram import _redact as redact_secrets, ad as telegram_ad, main as publish_offer, parse_bool
from pinterest_publisher import PinterestPublisherError, build_pin_payload
from spreadsheet_exports import build_exports

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
DATA_PATH = "data/products.csv"

COLS = [
    "id", "nome", "preco", "link", "imagem_url", "categoria", "comissao",
    "ativo", "aprovado_publicacao", "status_publicacao", "frequencia_dias",
    "cliques", "pedidos", "comissao_estimada", "ultima_publicacao",
    "proxima_publicacao", "ultima_tentativa", "telegram_message_id",
    "telegram_status", "pinterest_status", "pinterest_pin_id",
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
        "categoria": "", "comissao": 0, "ativo": True,
        "aprovado_publicacao": False, "status_publicacao": "pronto", "frequencia_dias": 3,
        "cliques": 0, "pedidos": 0, "comissao_estimada": 0,
        "ultima_publicacao": "", "proxima_publicacao": "",
        "ultima_tentativa": "", "telegram_message_id": "",
        "telegram_status": "pendente", "pinterest_status": "pendente", "pinterest_pin_id": "",
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
    df["telegram_status"] = df["telegram_status"].fillna("pendente").astype(str).str.strip().str.casefold()
    df["pinterest_status"] = df["pinterest_status"].fillna("pendente").astype(str).str.strip().str.casefold()
    df.loc[df["telegram_message_id"].fillna("").astype(str).str.strip().ne(""), "telegram_status"] = "enviado"
    df.loc[df["pinterest_pin_id"].fillna("").astype(str).str.strip().ne(""), "pinterest_status"] = "enviado"
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


def ad_preview(row):
    return telegram_ad(row)


def classify(row):
    clicks = int(row["cliques"])
    orders = int(row["pedidos"])
    if orders >= 2 or (orders >= 1 and clicks >= 20):
        return "🏆 Vencedor"
    if clicks >= 10:
        return "🟡 Em teste"
    return "⚪ Novo"


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
st.caption("Produtos, aprovação de ofertas, anúncios e desempenho")
if st.session_state.pop("products_remote_refresh", False):
    st.warning("A base mudou no GitHub. Recarregamos os dados mais recentes para evitar sobrescrever atualizações.")
if not cloud:
    st.warning("A visualização está disponível, mas github_token precisa estar configurado para salvar produtos.")

panel, products, ads, telegram = st.tabs(["📊 Painel", "📋 Produtos", "📢 Anúncios", "📲 Telegram"])

with panel:
    product_col, active_col, orders_col, commission_col = st.columns(4)
    product_col.metric("Produtos", len(df))
    active_col.metric("Ativos", int(df["ativo"].sum()) if len(df) else 0)
    orders_col.metric("Pedidos", int(df["pedidos"].sum()) if len(df) else 0)
    commission_col.metric(
        "Comissão", f"R$ {df['comissao_estimada'].sum():.2f}" if len(df) else "R$ 0,00"
    )
    if len(df):
        summary = df.copy()
        summary["status"] = summary.apply(classify, axis=1)
        summary["score"] = (
            summary["pedidos"] * 5
            + summary["comissao_estimada"]
            + (summary["pedidos"] / summary["cliques"].replace(0, 1)) * 100
        )
        st.dataframe(
            summary[["nome", "cliques", "pedidos", "comissao_estimada", "status", "score"]]
            .sort_values("score", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Adicione seu primeiro produto na aba Produtos.")

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
            "ativo": st.column_config.CheckboxColumn("Ativo"),
            "aprovado_publicacao": st.column_config.CheckboxColumn("Aprovado para publicação"),
            "status_publicacao": st.column_config.SelectboxColumn(
                "Estado da publicação", options=["pronto", "enviando", "enviado", "revisar"]
            ),
            "telegram_status": st.column_config.SelectboxColumn(
                "Status Telegram", options=["pendente", "enviado", "revisar"]
            ),
            "pinterest_status": st.column_config.SelectboxColumn(
                "Status Pinterest", options=["pendente", "enviado", "revisar"]
            ),
            "frequencia_dias": st.column_config.NumberColumn("Dias", min_value=1, max_value=30),
            "comissao_estimada": st.column_config.NumberColumn("Comissão", format="R$ %.2f"),
        },
        disabled=["id", "ultima_publicacao", "proxima_publicacao", "ultima_tentativa", "telegram_message_id", "pinterest_pin_id"],
    )
    edited = clean(edited)
    st.caption(
        "Após uma falha ambígua, confira manualmente o canal antes de mudar o status daquele destino para pendente; "
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
        selected_name = st.selectbox("Produto", df["nome"].tolist())
        selected_row = df[df["nome"] == selected_name].iloc[0]
        st.markdown(ad_preview(selected_row), unsafe_allow_html=True)
    else:
        st.info("Cadastre produtos primeiro.")

with telegram:
    st.subheader("📲 Telegram")
    st.write("Telegram usa o Bot API oficial. Um Pin pode ser publicado na mesma ação quando Pinterest estiver configurado e habilitado.")
    st.write("GitHub — acesso à base:", "✅" if secret("github_token") else "❌")
    st.write("Telegram Bot token:", "✅" if secret("telegram_bot_token") else "❌")
    st.write("Telegram Chat/Canal ID:", "✅" if secret("telegram_chat_id") else "❌")
    pinterest_token = secret("pinterest_access_token")
    pinterest_board_id = secret("pinterest_board_id")
    pinterest_enabled = parse_bool(secret("pinterest_publish_enabled", False), default=False)
    st.write("Pinterest OAuth token:", "✅" if pinterest_token else "❌")
    st.write("Pinterest Board ID:", "✅" if pinterest_board_id else "❌")
    st.write("Pinterest habilitado para envio manual:", "✅" if pinterest_enabled else "⏸️")
    with st.expander("Configurar Pinterest nos Streamlit Secrets"):
        st.caption("O token e o ID do board são obtidos na integração OAuth/API do Pinterest. Não cole os valores no chat nem na planilha.")
        st.caption("Não há teste sem publicação: ao clicar em publicar com Pinterest habilitado, o Pin será criado de verdade.")
        st.code(
            'pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"\n'
            'pinterest_board_id = "ID_NUMERICO_DO_BOARD"\n'
            'pinterest_publish_enabled = false',
            language="toml",
        )
        st.info(
            "A opção false mantém o Pinterest desligado. Para automação pelo GitHub Actions, configure também "
            "PINTEREST_ACCESS_TOKEN e PINTEREST_BOARD_ID em Actions Secrets e a variável "
            "AXADINHOS_PINTEREST_CROSSPOST_ENABLED=true. A variável AXADINHOS_AUTO_PUBLISH continua sendo uma trava separada."
        )
    if pinterest_enabled and (not pinterest_token or not pinterest_board_id):
        st.warning("Pinterest está habilitado, mas faltam o token OAuth e/ou o Board ID; nenhum envio multicanal será iniciado.")
    if len(df):
        selected_name = st.selectbox("Produto para publicação", df["nome"].tolist(), key="telegram_test")
        selected_row = df[df["nome"] == selected_name].iloc[0]
        product_is_approved = (
            parse_bool(selected_row.get("ativo", True), default=True)
            and parse_bool(selected_row.get("aprovado_publicacao", False), default=False)
        )
        publisher_credentials_ready = bool(
            secret("github_token")
            and secret("telegram_bot_token")
            and secret("telegram_chat_id")
            and (not pinterest_enabled or (pinterest_token and pinterest_board_id))
        )
        pinterest_preflight_error = ""
        if pinterest_enabled and pinterest_token and pinterest_board_id and product_is_approved:
            try:
                build_pin_payload(selected_row, str(pinterest_board_id))
            except PinterestPublisherError as exc:
                pinterest_preflight_error = str(exc)
        can_publish = product_is_approved and publisher_credentials_ready and not pinterest_preflight_error
        if not product_is_approved:
            st.warning("Publicação bloqueada: ative e aprove este produto depois de revisar nome, preço, imagem e link.")
        elif not publisher_credentials_ready:
            st.warning("Publicação bloqueada: configure os Secrets obrigatórios indicados acima.")
        elif pinterest_preflight_error:
            st.warning("Pin bloqueado antes do envio: " + pinterest_preflight_error)
        if pinterest_enabled and publisher_credentials_ready and not pinterest_preflight_error:
            st.caption(
                "Um clique envia primeiro ao Telegram e depois cria um Pin linkado com o link afiliado original. "
                "Os canais são sequenciais; se o Pinterest falhar depois do Telegram, o estado exige revisão manual."
            )
        button_label = (
            "🚀 Publicar no Telegram + Pinterest (Pin linkado)"
            if pinterest_enabled else "🚀 Publicar no Telegram"
        )
        if st.button(button_label, disabled=not can_publish):
            github_token = secret("github_token")
            telegram_token = secret("telegram_bot_token")
            chat_id = secret("telegram_chat_id")
            pinterest_token = secret("pinterest_access_token")
            pinterest_board_id = secret("pinterest_board_id")
            pinterest_enabled = parse_bool(secret("pinterest_publish_enabled", False), default=False)
            if not github_token or not telegram_token or not chat_id:
                st.error("Configure github_token, telegram_bot_token e telegram_chat_id nos Secrets.")
            else:
                publish_env = {
                    "PUBLISH_CONFIRMED": "true",
                    "GH_AUTOMATION_TOKEN": github_token,
                    "TELEGRAM_BOT_TOKEN": telegram_token,
                    "TELEGRAM_CHAT_ID": chat_id,
                    "PINTEREST_PUBLISH_ENABLED": str(pinterest_enabled).lower(),
                    "PINTEREST_ACCESS_TOKEN": pinterest_token,
                    "PINTEREST_BOARD_ID": pinterest_board_id,
                }
                try:
                    publish_offer(
                        environ=publish_env,
                        session=requests,
                        product_id=selected_row["id"],
                    )
                    st.success("Oferta publicada nos canais habilitados e estado registrado na base do GitHub.")
                    st.rerun()
                except Exception as exc:
                    st.error("Publicação bloqueada ou falhou: " + redact_secrets(
                        exc, github_token, telegram_token, pinterest_token
                    ))
