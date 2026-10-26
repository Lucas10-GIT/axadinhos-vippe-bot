import base64
import io
import os
import pandas as pd
import requests
import streamlit as st

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
DATA_PATH = "data/products.csv"

COLS = [
    "id","nome","preco","link","imagem_url","categoria","comissao",
    "ativo","frequencia_dias","cliques","pedidos","comissao_estimada",
    "ultima_publicacao","proxima_publicacao"
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
        "id":"", "nome":"", "preco":"", "link":"", "imagem_url":"",
        "categoria":"", "comissao":0, "ativo":True, "frequencia_dias":3,
        "cliques":0, "pedidos":0, "comissao_estimada":0,
        "ultima_publicacao":"", "proxima_publicacao":""
    }
    for c, v in defaults.items():
        if c not in df.columns:
            df[c] = v
    df = df[COLS]
    for c in ["id","cliques","pedidos"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ["comissao","comissao_estimada","frequencia_dias"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["frequencia_dias"] = df["frequencia_dias"].clip(1,30).astype(int)
    df["ativo"] = df["ativo"].fillna(True).astype(bool)
    return df

def gh_headers(token):
    return {"Accept":"application/vnd.github+json",
            "Authorization":f"Bearer {token}",
            "X-GitHub-Api-Version":"2022-11-28"}

def load():
    token = secret("github_token")
    if not token:
        return clean(pd.DataFrame(columns=COLS)), None, False
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}?ref={BRANCH}"
    r = requests.get(url, headers=gh_headers(token), timeout=20)
    if r.status_code == 404:
        return clean(pd.DataFrame(columns=COLS)), None, True
    r.raise_for_status()
    p = r.json()
    raw = base64.b64decode(p["content"]).decode()
    return clean(pd.read_csv(io.StringIO(raw))), p["sha"], True

def save(df, sha):
    token = secret("github_token")
    if not token:
        return False, "Configure github_token nos Secrets."
    csv = clean(df).to_csv(index=False)
    content = base64.b64encode(csv.encode()).decode()
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}"
    body = {"message":"Atualiza base de produtos","content":content,"branch":BRANCH}
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=gh_headers(token), json=body, timeout=30)
    if not r.ok:
        return False, r.text
    return True, "Base salva."

def ad(row):
    hook = {
        "Casa":"✨ Solução prática para facilitar seu dia a dia!",
        "Casa & Cozinha":"🏠 Achadinho útil para deixar a casa mais prática!",
        "Eletrônicos":"⚡ Achadinho tecnológico que vale conferir!",
        "Pet":"🐾 Achadinho especial para quem ama pets!",
        "Beleza":"✨ Achadinho para melhorar sua rotina!",
        "Acessórios":"🔥 Achadinho útil para ter sempre por perto!"
    }.get(str(row["categoria"]), "🔥 Olha esse achadinho!")
    return (
        f"🔥 *ACHADINHO DO DIA!*\n\n"
        f"🛍️ *{row['nome']}*\n\n{hook}\n\n"
        f"💰 *Preço:* {row['preco'] or 'Confira o preço'}\n\n"
        f"👉 *Ver na Shopee:*\n{row['link']}\n\n"
        "👑 *Axadinhos Vippe*\n_Se é útil, é achadinho!_"
    )

def classify(row):
    clicks = int(row["cliques"])
    orders = int(row["pedidos"])
    if orders >= 2 or (orders >= 1 and clicks >= 20):
        return "🏆 Vencedor"
    if clicks >= 10:
        return "🟡 Em teste"
    return "⚪ Novo"

df, sha, cloud = load()

st.title("👑 Axadinhos Vippe")
st.caption("Planilha + banco persistente + anúncios + Telegram + vencedores")

t1,t2,t3,t4 = st.tabs(["📊 Painel","📋 Produtos","📢 Anúncios","📲 Telegram"])

with t1:
    a,b,c,d = st.columns(4)
    a.metric("Produtos", len(df))
    b.metric("Ativos", int(df["ativo"].sum()) if len(df) else 0)
    c.metric("Pedidos", int(df["pedidos"].sum()) if len(df) else 0)
    d.metric("Comissão", f"R$ {df['comissao_estimada'].sum():.2f}" if len(df) else "R$ 0,00")
    if len(df):
        x=df.copy()
        x["status"]=x.apply(classify,axis=1)
        x["score"]=x["pedidos"]*5 + x["comissao_estimada"] + (x["pedidos"]/x["cliques"].replace(0,1))*100
        st.dataframe(x[["nome","cliques","pedidos","comissao_estimada","status","score"]].sort_values("score",ascending=False),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Adicione seu primeiro produto na aba Produtos.")

with t2:
    st.subheader("📋 Planilha de produtos")
    st.caption("Nome, preço, link da Shopee e URL direta da imagem são os campos principais.")
    edited=st.data_editor(
        df, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "link":st.column_config.LinkColumn("Link Shopee"),
            "imagem_url":st.column_config.LinkColumn("Link da foto"),
            "ativo":st.column_config.CheckboxColumn("Ativo"),
            "frequencia_dias":st.column_config.NumberColumn("Dias",min_value=1,max_value=30),
            "comissao_estimada":st.column_config.NumberColumn("Comissão",format="R$ %.2f"),
        },
        disabled=["id","ultima_publicacao","proxima_publicacao"]
    )
    if st.button("💾 Salvar produtos", type="primary"):
        ok,msg=save(edited,sha)
        (st.success if ok else st.error)(msg)
        if ok: st.rerun()
    st.download_button("⬇️ Baixar CSV", edited.to_csv(index=False).encode(),
                       "axadinhos_vippe_produtos.csv","text/csv")

with t3:
    if len(df):
        nome=st.selectbox("Produto",df["nome"].tolist())
        row=df[df["nome"]==nome].iloc[0]
        st.markdown(ad(row))
    else:
        st.info("Cadastre produtos primeiro.")

with t4:
    st.subheader("📲 Telegram")
    st.write("O envio usa o Bot API oficial do Telegram.")
    st.write("Token:", "✅" if secret("telegram_bot_token") else "❌")
    st.write("Chat/Canal:", "✅" if secret("telegram_chat_id") else "❌")
    if len(df):
        nome=st.selectbox("Testar envio",df["nome"].tolist(),key="tg")
        row=df[df["nome"]==nome].iloc[0]
        if st.button("🚀 Enviar teste agora"):
            token=secret("telegram_bot_token")
            chat=secret("telegram_chat_id")
            if not token or not chat:
                st.error("Configure telegram_bot_token e telegram_chat_id.")
            else:
                base=f"https://api.telegram.org/bot{token}"
                if str(row["imagem_url"]).strip():
                    r=requests.post(f"{base}/sendPhoto",
                        data={"chat_id":chat,"photo":row["imagem_url"],
                              "caption":ad(row),"parse_mode":"Markdown"},timeout=30)
                else:
                    r=requests.post(f"{base}/sendMessage",
                        data={"chat_id":chat,"text":ad(row),
                              "parse_mode":"Markdown"},timeout=30)
                st.success("Enviado!") if r.ok else st.error(r.text)
