import base64, io, os
from datetime import datetime, timedelta
import pandas as pd
import requests

OWNER="Lucas10-GIT"; REPO="axadinhos-vippe-bot"; BRANCH="main"
PATH="data/products.csv"

def headers(token):
    return {"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28"}

def load(token):
    u=f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}?ref={BRANCH}"
    r=requests.get(u,headers=headers(token),timeout=20); r.raise_for_status()
    p=r.json(); return pd.read_csv(io.StringIO(base64.b64decode(p["content"]).decode())),p["sha"]

def save(token,df,sha):
    raw=df.to_csv(index=False).encode()
    body={"message":"Publicação automática Axadinhos Vippe","content":base64.b64encode(raw).decode(),"branch":BRANCH,"sha":sha}
    u=f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}"
    r=requests.put(u,headers=headers(token),json=body,timeout=30); r.raise_for_status()

def ad(row):
    return (f"🔥 *ACHADINHO DO DIA!*\n\n🛍️ *{row['nome']}*\n\n"
            f"💰 *Preço:* {row['preco'] or 'Confira o preço'}\n\n"
            f"👉 *Ver na Shopee:*\n{row['link']}\n\n"
            "👑 *Axadinhos Vippe*\n_Se é útil, é achadinho!_")

token=os.environ["GITHUB_TOKEN"]; tg=os.environ["TELEGRAM_BOT_TOKEN"]; chat=os.environ["TELEGRAM_CHAT_ID"]
df,sha=load(token)
now=datetime.utcnow()

candidates=[]
for i,row in df.iterrows():
    if str(row.get("ativo",True)).lower() not in ["true","1","yes"]:
        continue
    freq=int(float(row.get("frequencia_dias",3) or 3))
    last=str(row.get("ultima_publicacao","")).strip()
    due=True
    if last:
        try: due=(now-datetime.fromisoformat(last)).total_seconds() >= freq*86400
        except: pass
    if due: candidates.append((i,row))

if not candidates:
    print("Nenhum produto vencido para publicação.")
    raise SystemExit(0)

def score(row):
    clicks=float(row.get("cliques",0) or 0); orders=float(row.get("pedidos",0) or 0); comm=float(row.get("comissao_estimada",0) or 0)
    return orders*5 + comm + (orders/max(clicks,1))*100

idx,row=max(candidates,key=lambda x:score(x[1]))
base=f"https://api.telegram.org/bot{tg}"
img=str(row.get("imagem_url","")).strip()
if img:
    r=requests.post(f"{base}/sendPhoto",data={"chat_id":chat,"photo":img,"caption":ad(row),"parse_mode":"Markdown"},timeout=30)
else:
    r=requests.post(f"{base}/sendMessage",data={"chat_id":chat,"text":ad(row),"parse_mode":"Markdown"},timeout=30)
r.raise_for_status()

df.at[idx,"ultima_publicacao"]=now.isoformat()
freq=2 if (float(row.get("pedidos",0) or 0)>=2) else 4 if float(row.get("cliques",0) or 0)>=10 else 3
df.at[idx,"frequencia_dias"]=freq
df.at[idx,"proxima_publicacao"]=(now+timedelta(days=freq)).isoformat()
save(token,df,sha)
print(f"Publicado: {row['nome']} | próxima em {freq} dias")
