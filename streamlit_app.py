import streamlit as st
import asyncio, base64, json, os, random, re, string, time, io
from pathlib import Path
from PIL import Image
import httpx

st.set_page_config(page_title="Davinci NITRO", layout="wide", initial_sidebar_state="collapsed")

ACC_FILE = Path("accounts.json")
FB_KEY = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs"
DV_API = "https://wl-api-web-prod.davinci.ai"
DV_CMS = "https://wl-cms-web-prod.davinci.ai"
MAIL = "https://mail808.elmarciun.workers.dev"

MODELS = [
    {"key": "NANO_BANANA_2", "name": "Nano Banana 2", "cost": 25, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "NANO_BANANA_PRO", "name": "Nano Banana Pro", "cost": 25, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "GROK_IMAGINE", "name": "Grok Imagine", "cost": 10, "dims": ["1:1","16:9","9:16"], "ref": True},
    {"key": "FLUX_2_TURBO", "name": "Flux 2 Turbo", "cost": 9, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "GPT_IMAGE_1", "name": "GPT Image 1", "cost": 9, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "QWEN", "name": "Qwen", "cost": 9, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "KONTEXT", "name": "Kontext", "cost": 11, "dims": ["1:1","16:9"], "ref": True},
    {"key": "FLUX_2", "name": "Flux 2", "cost": 12, "dims": ["1:1","16:9","9:16"], "ref": False},
    {"key": "DAVINCI_ULTRA", "name": "Davinci Ultra", "cost": 15, "dims": ["1:1","16:9"], "ref": True},
    {"key": "IDEOGRAM_V3", "name": "Ideogram V3", "cost": 15, "dims": ["1:1","16:9"], "ref": False},
    {"key": "IDEOGRAM_V4", "name": "Ideogram V4", "cost": 15, "dims": ["1:1","16:9"], "ref": False},
    {"key": "SEEDREAM_5_PRO", "name": "Seedream 5 Pro", "cost": 20, "dims": ["1:1"], "ref": False},
]

def load_accs():
    if ACC_FILE.exists():
        try: return json.loads(ACC_FILE.read_text())
        except: return []
    return []

def save_accs(accs):
    try: ACC_FILE.write_text(json.dumps(accs, indent=2))
    except: pass

async def gen_email():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1")
        return r.text.strip() if r.status_code == 200 and "@" in r.text else None

async def wait_otp(email):
    async with httpx.AsyncClient(timeout=15) as c:
        for _ in range(30):
            await asyncio.sleep(3)
            try:
                r = await c.get(f"{MAIL}/attendi/{email}",
                              params={"mittente":"davinci","codice":1,"semplice":1,"timeout":10000})
                if r.status_code == 200:
                    m = re.search(r"\b(\d{6})\b", r.text)
                    if m: return m.group(1)
            except: pass
    return None

async def signup_one():
    async with httpx.AsyncClient(timeout=30) as c:
        email = await gen_email()
        if not email: return None
        pw = "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!"
        
        r = await c.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}",
                        json={"returnSecureToken":True,"email":email,"password":pw,"clientType":"CLIENT_TYPE_WEB"})
        if r.status_code != 200: return None
        
        await c.post(f"{DV_API}/email-verification-send", json={"email":email})
        code = await wait_otp(email)
        if not code: return None
        
        await c.post(f"{DV_API}/email-verification-verify-code", json={"email":email,"code":code})
        
        r2 = await c.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}",
                         json={"returnSecureToken":True,"email":email,"password":pw,"clientType":"CLIENT_TYPE_WEB"})
        d2 = r2.json()
        return {"email": email, "id_token": d2["idToken"], "refresh_token": d2["refreshToken"], "credits": 25}

async def check_credits(token):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{DV_API}/user/credit", headers={"x-platform":"web","x-token":token})
            if r.status_code == 200:
                return int(r.json().get("data", {}).get("credit", 0))
    except: pass
    return 0

async def refresh_token_fn(refresh_tok):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"https://securetoken.googleapis.com/v1/token?key={FB_KEY}",
                            data=f"grant_type=refresh_token&refresh_token={refresh_tok}",
                            headers={"content-type":"application/x-www-form-urlencoded"})
            if r.status_code == 200:
                d = r.json()
                return d["id_token"], d["refresh_token"]
    except: pass
    return None, None

def get_uid(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))["user_id"]
    except: return None

async def generate_image(prompt, model_key, dimension, token):
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{DV_API}/process/txt-image",
                        json={"prompt":prompt,"model":model_key,"dimension":dimension,"artStyleId":0,"imageCount":1},
                        headers={"x-platform":"web","x-token":token,"content-type":"application/json"})
        if r.status_code != 200: return None, f"API Error: {r.status_code}"
        
        data = r.json()
        pid = None
        if isinstance(data.get("data"), list) and data["data"]:
            pid = data["data"][0].get("processId") if isinstance(data["data"][0], dict) else data["data"][0]
        elif isinstance(data.get("data"), dict):
            pid = data["data"].get("processId")
        else:
            pid = data.get("processId")
        
        if not pid: return None, f"No process ID: {data}"
        
        uid = get_uid(token)
        if not uid: return None, "Token decode error"
        
        url = f"https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents/users/{uid}/processes/{pid}"
        
        for _ in range(90):
            await asyncio.sleep(2)
            try:
                r2 = await c.get(url, headers={"authorization":f"Bearer {token}"})
                if r2.status_code == 200:
                    fields = r2.json().get("fields", {})
                    status = fields.get("status", {}).get("stringValue", "")
                    if status in ["COMPLETED", "SUCCESS", "DONE"]:
                        urls = []
                        for k in ["outputs", "output", "images", "results", "imageUrls"]:
                            if k in fields:
                                arr = fields[k].get("arrayValue", {}).get("values", [])
                                for item in arr:
                                    val = item.get("stringValue", "")
                                    if val.startswith("http"): urls.append(val)
                                    elif isinstance(item.get("mapValue"), dict):
                                        for sk, sv in item["mapValue"].get("fields", {}).items():
                                            v = sv.get("stringValue", "")
                                            if v.startswith("http"): urls.append(v)
                        return urls, "OK"
                    elif status in ["FAILED", "ERROR", "CANCELLED"]:
                        err = fields.get("error", {}).get("stringValue", status)
                        return None, f"Failed: {err}"
            except: pass
        return None, "Timeout"

st.title("🎨 Davinci.ai NITRO")
st.caption("Auto-account rotation | 25+ Models | Free credit recycling")

if 'accounts' not in st.session_state:
    st.session_state.accounts = load_accs()

tab1, tab2, tab3 = st.tabs(["🎨 Generate", "👤 Accounts", "ℹ️ Models"])

with tab1:
    col1, col2 = st.columns([1, 2])
    with col1:
        prompt = st.text_area("Prompt", placeholder="A cyberpunk cat in neon city...", height=120)
        names = {f"{m['name']} ({m['cost']}cr)": m for m in MODELS}
        sel = st.selectbox("Model", list(names.keys()))
        m_data = names[sel]
        dim = st.selectbox("Dimension", m_data['dims'])
        
        if st.button("🚀 Generate", type="primary", use_container_width=True):
            if not prompt:
                st.error("Enter a prompt!")
            else:
                with st.status("Working...", expanded=True) as status:
                    st.write("🔍 Checking accounts...")
                    acc = None
                    for a in st.session_state.accounts:
                        cr = asyncio.run(check_credits(a["id_token"]))
                        if cr >= m_data['cost']:
                            acc = a
                            acc["credits"] = cr
                            break
                        elif cr == 0 and a.get("refresh_token"):
                            new_tok, new_ref = asyncio.run(refresh_token_fn(a["refresh_token"]))
                            if new_tok:
                                a["id_token"] = new_tok
                                a["refresh_token"] = new_ref
                                cr = asyncio.run(check_credits(new_tok))
                                if cr >= m_data['cost']:
                                    acc = a
                                    acc["credits"] = cr
                                    break
                    
                    if not acc:
                        st.write("📝 Creating new account (may take 30-60s)...")
                        acc = asyncio.run(signup_one())
                        if acc:
                            st.session_state.accounts.append(acc)
                            save_accs(st.session_state.accounts)
                            st.write(f"✅ Created: {acc['email']}")
                        else:
                            status.update(label="❌ Signup failed", state="error")
                            st.stop()
                    
                    st.write(f"👤 Using: `{acc['email'][:30]}...` ({acc.get('credits', '?')}cr)")
                    st.write(f"🎨 Generating with {m_data['name']}...")
                    
                    urls, msg = asyncio.run(generate_image(prompt, m_data['key'], dim, acc["id_token"]))
                    
                    if urls:
                        status.update(label=f"✅ Done in {m_data['cost']}cr", state="complete")
                        with col2:
                            for url in urls:
                                st.image(url, use_container_width=True)
                                st.caption(f"[🔗 Full size]({url})")
                    else:
                        status.update(label=f"❌ {msg}", state="error")

with tab2:
    st.subheader("Account Manager")
    c1, c2 = st.columns(2)
    with c1:
        n_acc = st.number_input("Accounts to create", 1, 10, 3)
        if st.button("➕ Create Accounts"):
            bar = st.progress(0)
            for i in range(int(n_acc)):
                with st.spinner(f"Creating {i+1}/{n_acc}..."):
                    acc = asyncio.run(signup_one())
                    if acc:
                        st.session_state.accounts.append(acc)
                        save_accs(st.session_state.accounts)
                        st.success(f"✅ {acc['email']}")
                    else:
                        st.error(f"❌ Failed #{i+1}")
                bar.progress((i+1)/n_acc)
    
    with c2:
        if st.button("💰 Check All Credits"):
            total = 0
            for acc in st.session_state.accounts:
                cr = asyncio.run(check_credits(acc["id_token"]))
                total += cr
                emoji = "🟢" if cr >= 20 else "🟡" if cr > 0 else "🔴"
                st.write(f"{emoji} `{acc['email'][:30]}...` : **{cr}cr**")
            st.divider()
            st.metric("Total Credits", f"{total}cr", f"~{total//25} NanoBanana2")

    st.divider()
    st.write(f"**Total accounts stored: {len(st.session_state.accounts)}**")

with tab3:
    st.subheader("Available Models")
    for m in sorted(MODELS, key=lambda x: x['cost']):
        color = "🟢" if m['cost'] <= 10 else "🟡" if m['cost'] <= 15 else "🔴"
        ref = "🖼️" if m['ref'] else "  "
        st.markdown(f"{color} {ref} **`{m['key']}`** - {m['name']} — **{m['cost']}cr** | Dims: `{', '.join(m['dims'])}`")