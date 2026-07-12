from __future__ import annotations
import asyncio, base64, json, os, random, re, string, time, io, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx
import streamlit as st
from PIL import Image

# ═══════════════════════════════════════════════════════════
FB_KEY = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs"
FB_GMPID = "1:378221804375:web:32bf22971597e5ef92dc12"
FB_SU  = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}"
FB_LK  = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FB_KEY}"
FB_SI  = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}"
FB_TOK = f"https://securetoken.googleapis.com/v1/token?key={FB_KEY}"
API    = "https://wl-api-web-prod.davinci.ai"
CMS    = "https://wl-cms-web-prod.davinci.ai"
PAY    = "https://payment.davinci.ai/api/v1/auth"
FS_BASE = "https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents"
MAIL   = "https://mail808.elmarciun.workers.dev"

SD = Path(__file__).parent.resolve()
ACCS_FILE = SD / "accounts.json"
MODELS_CACHE = SD / "models_cache.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
H_BASE = {
    "accept": "*/*", "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate",
    "origin": "https://davinci.ai", "referer": "https://davinci.ai/",
    "user-agent": UA,
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "cross-site",
}
H_JSON = {"content-type": "application/json"}
H_FB = {**H_JSON, "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web", "x-firebase-gmpid": FB_GMPID}

DIM_ALIAS = {
    "1:1": ["1:1", "square", "square_hd"],
    "16:9": ["16:9", "landscape_16_9", "landscape"],
    "9:16": ["9:16", "portrait_16_9", "portrait"],
    "4:3": ["4:3", "landscape_4_3"], "3:4": ["3:4", "portrait_4_3"],
    "21:9": ["21:9"], "4:5": ["4:5"], "5:4": ["5:4"],
    "2:3": ["2:3"], "3:2": ["3:2"], "auto": ["auto"],
}
_OTP_RE = re.compile(r"\b(\d{6})\b")
_PWC = string.ascii_letters + string.digits + "!@#$%"

# ═══════════ HTTP ═══════════
def _client(timeout=30):
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0),
                             follow_redirects=True, headers=H_BASE)

async def _post(c, url, body, headers=None, ok=(200, 201), raw=False):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.post(url, content=body, headers=hdr) if raw else await c.post(url, json=body, headers=hdr)
    if r.status_code not in ok: raise RuntimeError(f"POST {url}: {r.status_code} {r.text[:200]}")
    try: return r.json() if r.text else {}
    except: return {}

async def _get(c, url, headers=None, params=None):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.get(url, headers=hdr, params=params)
    try: return r.status_code, (r.json() if r.text else {})
    except: return r.status_code, {}

# ═══════════ MAIL ═══════════
async def gen_email(c):
    for _ in range(3):
        try:
            r = await c.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1", timeout=10)
            if r.status_code == 200 and "@" in r.text: return r.text.strip()
        except: await asyncio.sleep(0.3)
    return None

async def wait_otp(c, email, total=120):
    deadline = time.monotonic() + total
    while time.monotonic() < deadline:
        try:
            r = await c.get(f"{MAIL}/attendi/{email}",
                params={"mittente": "davinci", "codice": 1, "semplice": 1, "timeout": 15000}, timeout=20)
            if r.status_code == 200 and r.text.strip():
                m = _OTP_RE.search(r.text)
                if m: return m.group(1)
            r2 = await c.get(f"{MAIL}/inbox/{email}", timeout=8)
            if r2.status_code == 200:
                try:
                    d = r2.json()
                    msgs = d if isinstance(d, list) else (d.get("dato") or d.get("messages") or [])
                    for msg in (msgs or [])[:5]:
                        mid = msg.get("id") if isinstance(msg, dict) else None
                        if not mid: continue
                        r3 = await c.get(f"{MAIL}/leggi/{email}/{mid}?semplice=1", timeout=8)
                        if r3.status_code == 200:
                            m = _OTP_RE.search(r3.text)
                            if m: return m.group(1)
                except: pass
        except: pass
        await asyncio.sleep(1.2)
    return None

def rand_pw(n=14):
    c = [random.choice(string.ascii_lowercase), random.choice(string.ascii_uppercase),
         random.choice(string.digits), random.choice("!@#$%")]
    c += random.choices(_PWC, k=n-4); random.shuffle(c); return "".join(c)

# ═══════════ SIGNUP ═══════════
async def signup_one():
    async with _client(timeout=45) as c:
        email = await gen_email(c)
        if not email: raise RuntimeError("Email generation failed")
        password = rand_pw()
        d = await _post(c, FB_SU, {"returnSecureToken": True, "email": email,
            "password": password, "clientType": "CLIENT_TYPE_WEB"}, H_FB)
        id_token, refresh_token, local_id = d["idToken"], d["refreshToken"], d["localId"]
        await asyncio.gather(
            _post(c, f"{API}/email-verification-send", {"email": email}, H_JSON),
            _post(c, FB_LK, {"idToken": id_token}, H_FB), return_exceptions=True)
        code = await wait_otp(c, email)
        if not code: raise RuntimeError("OTP timeout")
        v = await _post(c, f"{API}/email-verification-verify-code",
                        {"email": email, "code": code}, H_JSON)
        if not v.get("data", {}).get("verified"): raise RuntimeError("OTP verify failed")
        d2 = await _post(c, FB_SI, {"returnSecureToken": True, "email": email,
            "password": password, "clientType": "CLIENT_TYPE_WEB"}, H_FB)
        id_token, refresh_token = d2["idToken"], d2["refreshToken"]
        ah = {**H_JSON, "x-platform": "web", "x-token": id_token}
        await asyncio.gather(
            _post(c, FB_LK, {"idToken": id_token}, H_FB),
            _get(c, f"{API}/user/credit", ah),
            _get(c, f"{API}/get-user-profile", ah),
            _post(c, f"{PAY}/create-user", {"email": email}, ah),
            return_exceptions=True)
        return {"email": email, "password": password, "local_id": local_id,
                "id_token": id_token, "refresh_token": refresh_token, "credits": 25,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# ═══════════ MODELS ═══════════
_MODELS: Optional[list] = None

async def fetch_models(force=False):
    global _MODELS
    if _MODELS and not force: return _MODELS
    if MODELS_CACHE.exists() and not force:
        try:
            d = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))
            _MODELS = d.get("data", d) if isinstance(d, dict) else d
            return _MODELS
        except: pass
    async with _client(timeout=20) as c:
        r = await c.get(f"{CMS}/image-models", headers=H_BASE)
        if r.status_code != 200: raise RuntimeError(f"Models: {r.status_code}")
        d = r.json()
        try: MODELS_CACHE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        except: pass
        _MODELS = d.get("data", d) if isinstance(d, dict) else d
        return _MODELS

_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _mk(m): return m.get("key", "")
def _mn(m): return m.get("modelName") or m.get("name", "")
def _mc(m):
    try: return int(m.get("creditSpend") or m.get("cost") or 0)
    except: return 0
def _mdims(m): return [d.get("dimensionKey","") for d in (m.get("dimensions") or []) if d.get("dimensionKey")]
def _mocl(m):
    v = m.get("outputCountLimit")
    return int(v) if v else None
def _mtime(m):
    """Tempo stimato in secondi per generazione (dal CMS o fallback)."""
    v = m.get("outputTime") or m.get("estimatedTime") or m.get("avgTime")
    try: return float(v) if v else 15.0
    except: return 15.0

def find_model(models, q):
    qn = _norm(q)
    if not qn: return None
    for m in models:
        if _norm(_mk(m)) == qn or _norm(_mn(m)) == qn: return m
    for m in models:
        for c in [_mk(m), _mn(m)]:
            cn = _norm(c)
            if cn and (qn in cn or cn in qn): return m
    return None

def resolve_dim(m, ud):
    dims = _mdims(m)
    if not dims: return ud
    if ud in dims: return ud
    lu = ud.lower().replace("x", ":")
    for c in DIM_ALIAS.get(lu, []):
        if c in dims: return c
    return dims[0]

# ═══════════ ACCOUNTS ═══════════
def load_accs():
    if not ACCS_FILE.exists(): return []
    try: return json.loads(ACCS_FILE.read_text(encoding="utf-8"))
    except: return []

def save_accs(accs):
    try:
        ACCS_FILE.parent.mkdir(exist_ok=True, parents=True)
        tmp = ACCS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(accs, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ACCS_FILE)
    except: pass

async def refresh_tok(rt):
    async with _client(timeout=15) as c:
        r = await c.post(FB_TOK, content=f"grant_type=refresh_token&refresh_token={rt}",
            headers={"content-type": "application/x-www-form-urlencoded",
                     "x-firebase-gmpid": FB_GMPID,
                     "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web",
                     "origin": "https://davinci.ai", "referer": "https://davinci.ai/",
                     "user-agent": UA})
        if r.status_code != 200: raise RuntimeError(f"Refresh: {r.status_code}")
        d = r.json(); return d["id_token"], d["refresh_token"]

def _jwt(tok, f="exp"):
    try:
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get(f)
    except: return None
def _expired(tok, safety=60):
    e = _jwt(tok, "exp"); return not e or time.time() >= (e - safety)
def _uid(tok): return _jwt(tok, "user_id") or _jwt(tok, "sub") or ""

def _pid(r):
    if isinstance(r, str) and len(r) > 8: return r
    if isinstance(r, list) and r:
        f = r[0]
        if isinstance(f, str): return f
        if isinstance(f, dict):
            for k in ("processId","process_id","id","jobId","job_id","taskId","uuid"):
                if f.get(k): return str(f[k])
    if isinstance(r, dict):
        for k in ("processId","process_id","id","jobId","job_id","taskId","uuid"):
            if r.get(k): return str(r[k])
        for w in ("data","result","response"):
            if r.get(w):
                p = _pid(r[w])
                if p: return p
    return ""

def _fs_val(v):
    if v is None: return None
    for k, fn in [("stringValue", str),("integerValue", int),("doubleValue", float),
                  ("booleanValue", bool),("timestampValue", str)]:
        if k in v: return fn(v[k]) if fn != bool else v[k]
    if "nullValue" in v: return None
    if "arrayValue" in v: return [_fs_val(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v: return {k: _fs_val(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return v
def _fs_doc(f): return {k: _fs_val(v) for k, v in (f or {}).items()}

def _urls(doc):
    urls = []
    def _rec(o):
        if isinstance(o, str):
            if o.startswith("http") and (any(o.lower().endswith(e) for e in [".png",".jpg",".jpeg",".webp",".gif"])
                                          or "storage.googleapis" in o or "firebasestorage" in o):
                urls.append(o)
        elif isinstance(o, list):
            for it in o: _rec(it)
        elif isinstance(o, dict):
            for k in ("url","imageUrl","image_url","src","downloadUrl","publicUrl","assetUrl","outputUrl"):
                if isinstance(o.get(k), str) and o[k].startswith("http"): urls.append(o[k])
            for v in o.values(): _rec(v)
    for k in ("outputs","output","images","results","urls","imageUrls","outputImages","assets","data"):
        v = doc.get(k)
        if v: _rec(v)
    seen = set()
    return [u for u in urls if not (u in seen or seen.add(u))]

async def check_credits(tok):
    try:
        async with _client(timeout=10) as c:
            st, body = await _get(c, f"{API}/user/credit", {"x-platform": "web", "x-token": tok})
            if st != 200: return 0
            d = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(d, dict):
                return int(d.get("credit") or d.get("balance") or d.get("amount") or 0)
            return int(d) if isinstance(d, (int, float)) else 0
    except: return 0

async def _ensure_tok(acc):
    tok = acc.get("id_token", ""); ref = acc.get("refresh_token", "")
    if _expired(tok) and ref:
        try:
            tok, ref = await refresh_tok(ref)
            acc["id_token"] = tok; acc["refresh_token"] = ref
        except: pass
    return tok

async def auto_pick_account(need_cr, progress_state=None):
    accs = load_accs()
    accs_sorted = sorted(accs, key=lambda a: -int(a.get("credits", 0)))
    for acc in accs_sorted:
        try:
            tok = await _ensure_tok(acc)
            cr = await check_credits(tok)
            acc["credits"] = cr
            if cr >= need_cr:
                save_accs(accs)
                return acc
        except: continue
    save_accs(accs)
    if progress_state: progress_state["phase"] = "signup"
    new = await signup_one()
    accs.append(new); save_accs(accs)
    return new

async def _poll(c, tok, uid, pid, timeout=300, interval=1.5, progress_state=None):
    url = f"{FS_BASE}/users/{uid}/processes/{pid}"
    hdr = {"authorization": f"Bearer {tok}"}
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            r = await c.get(url, headers=hdr)
            if r.status_code == 200:
                doc = r.json()
                d = _fs_doc(doc.get("fields", {}) if isinstance(doc, dict) else {})
                st = (d.get("status") or "").upper()
                if st != last:
                    last = st
                    if progress_state: progress_state["status"] = st
                if st in ("COMPLETED","SUCCESS","DONE","FINISHED"): return d
                if st in ("FAILED","ERROR","CANCELLED","REJECTED"):
                    err = (d.get("error") or d.get("errorMessage") or d.get("message") or "")
                    if isinstance(err, dict): err = err.get("message") or str(err)
                    raise RuntimeError(f"Generation {st}: {err}" if err else f"Generation {st}")
            elif r.status_code == 401: raise RuntimeError("Token invalidated")
        except RuntimeError: raise
        except: pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timeout (last: {last})")

def _build_payload(m, prompt, dim, count, art_style_id, ref_urls=None):
    payload = {"prompt": prompt, "model": _mk(m), "dimension": dim, "artStyleId": art_style_id}
    max_count = _mocl(m)
    payload["imageCount"] = min(count, max_count) if max_count else count
    if ref_urls and m.get("referenceImage"):
        limit = m.get("referenceImageLimit") or 1
        ref_urls = ref_urls[:limit]
        payload["referenceImages"] = ref_urls
        payload["referenceImage"] = ref_urls[0]
    if m.get("cfg"): payload["cfg"] = 4.0
    if m.get("seed"): payload["seed"] = random.randint(1, 10**9)
    if m.get("negativePrompt"): payload["negativePrompt"] = ""
    return payload

@dataclass
class Result:
    urls: list = field(default_factory=list)
    process_id: str = ""
    model: str = ""
    dimension: str = ""
    duration_s: float = 0.0
    credits_used: int = 0

async def do_generate(prompt, model_key, dimension="1:1", count=1,
                      reference_urls=None, art_style_id=0, progress_state=None):
    models = await fetch_models()
    m = find_model(models, model_key)
    if not m: raise RuntimeError(f"Model '{model_key}' not found")
    need = _mc(m); dim = resolve_dim(m, dimension)

    if progress_state:
        progress_state["phase"] = "account"
        progress_state["est_time"] = _mtime(m) + 3

    acc = await auto_pick_account(need, progress_state=progress_state)
    tok = await _ensure_tok(acc); uid = _uid(tok)
    if not uid: raise RuntimeError("Invalid session token")

    if progress_state: progress_state["phase"] = "submit"
    t0 = time.perf_counter()
    async with _client(timeout=45) as c:
        ah = {**H_JSON, "x-platform": "web", "x-token": tok}
        payload = _build_payload(m, prompt, dim, count, art_style_id, ref_urls=reference_urls)
        resp = await _post(c, f"{API}/process/txt-image", payload, ah)
        pid = _pid(resp)
        if not pid: raise RuntimeError(f"Job not created: {resp}")
        if progress_state:
            progress_state["phase"] = "render"
            progress_state["pid"] = pid[:12]
        doc = await _poll(c, tok, uid, pid, progress_state=progress_state)

    dur = time.perf_counter() - t0
    return Result(urls=_urls(doc), process_id=pid, model=_mk(m),
                  dimension=dim, duration_s=dur, credits_used=need)

async def download_image(url):
    try:
        async with _client(timeout=60) as c:
            r = await c.get(url)
            if r.status_code == 200: return r.content
    except: pass
    return None

def run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try: loop.close()
        except: pass


# ═══════════════════════════════════════════════════════════════════
#                    STREAMLIT UI - ULTRA MODERN
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(page_title="IMG-NITRO", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    
    :root {
        --bg-0: #050510;
        --bg-1: #0a0a1a;
        --bg-2: #10102a;
        --accent-1: #6366f1;
        --accent-2: #a855f7;
        --accent-3: #ec4899;
        --accent-4: #06b6d4;
        --neon-cyan: #22d3ee;
        --neon-pink: #f472b6;
        --neon-green: #4ade80;
        --text-1: #f8fafc;
        --text-2: #94a3b8;
        --text-3: #64748b;
        --border: rgba(99, 102, 241, 0.15);
        --border-hover: rgba(99, 102, 241, 0.4);
    }
    
    html, body, [class*="css"] {
        font-family: 'Space Grotesk', -apple-system, sans-serif !important;
    }
    
    /* Background animato */
    .stApp {
        background: 
            radial-gradient(ellipse 80% 50% at 20% 10%, rgba(99, 102, 241, 0.15), transparent),
            radial-gradient(ellipse 60% 40% at 80% 30%, rgba(168, 85, 247, 0.12), transparent),
            radial-gradient(ellipse 70% 45% at 50% 80%, rgba(236, 72, 153, 0.08), transparent),
            linear-gradient(180deg, #050510 0%, #0a0a1a 100%);
        background-attachment: fixed;
    }
    
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 1rem 2rem 3rem; max-width: 1500px; }
    
    /* ═══ HEADER ═══ */
    .nitro-hero {
        position: relative;
        background: linear-gradient(135deg, rgba(10, 10, 26, 0.9) 0%, rgba(20, 15, 45, 0.9) 100%);
        backdrop-filter: blur(24px);
        border: 1px solid var(--border);
        border-radius: 20px;
        padding: 28px 36px;
        margin-bottom: 20px;
        overflow: hidden;
        box-shadow: 
            0 0 60px rgba(99, 102, 241, 0.15),
            inset 0 1px 0 rgba(255, 255, 255, 0.05);
    }
    .nitro-hero::before {
        content: '';
        position: absolute;
        inset: -50%;
        background: conic-gradient(from 0deg, transparent, rgba(99, 102, 241, 0.1), transparent, rgba(236, 72, 153, 0.1), transparent);
        animation: rotate 12s linear infinite;
        z-index: 0;
    }
    @keyframes rotate { to { transform: rotate(360deg); } }
    
    .nitro-hero-inner { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; }
    
    .nitro-brand {
        font-family: 'JetBrains Mono', monospace;
        font-size: 38px;
        font-weight: 800;
        letter-spacing: -1.5px;
        background: linear-gradient(135deg, #f8fafc 0%, #a855f7 50%, #ec4899 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0;
        line-height: 1;
    }
    .nitro-brand .dash { color: var(--accent-2); -webkit-text-fill-color: var(--accent-2); }
    
    .nitro-tag {
        display: block;
        margin-top: 8px;
        font-size: 11px;
        color: var(--text-3);
        letter-spacing: 3px;
        text-transform: uppercase;
        font-weight: 500;
    }
    
    .nitro-status {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        background: rgba(74, 222, 128, 0.1);
        border: 1px solid rgba(74, 222, 128, 0.3);
        border-radius: 100px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        font-weight: 700;
        color: var(--neon-green);
        letter-spacing: 1px;
    }
    .pulse-dot {
        width: 8px; height: 8px; border-radius: 50%;
        background: var(--neon-green);
        box-shadow: 0 0 12px var(--neon-green);
        animation: pulse-glow 1.6s ease-in-out infinite;
    }
    @keyframes pulse-glow {
        0%, 100% { opacity: 1; transform: scale(1); box-shadow: 0 0 12px var(--neon-green); }
        50% { opacity: 0.6; transform: scale(1.2); box-shadow: 0 0 24px var(--neon-green); }
    }
    
    /* ═══ TABS ═══ */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: rgba(10, 10, 26, 0.6);
        backdrop-filter: blur(12px);
        padding: 6px;
        border-radius: 14px;
        border: 1px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        color: var(--text-3);
        border-radius: 10px;
        padding: 12px 26px;
        font-weight: 600;
        font-size: 12px;
        letter-spacing: 1.5px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        font-family: 'JetBrains Mono', monospace;
    }
    .stTabs [data-baseweb="tab"]:hover { color: var(--text-1); }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2)) !important;
        color: var(--text-1) !important;
        box-shadow: 0 0 20px rgba(99, 102, 241, 0.3);
    }
    
    /* ═══ SECTION TITLE ═══ */
    .sec-t {
        color: var(--text-2);
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 3px;
        font-weight: 700;
        margin: 20px 0 12px 0;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .sec-t::before {
        content: '';
        width: 3px; height: 12px;
        background: linear-gradient(180deg, var(--accent-1), var(--accent-3));
        border-radius: 2px;
    }
    
    /* ═══ INPUTS ═══ */
    .stTextArea textarea, .stTextInput input {
        background: rgba(5, 5, 16, 0.6) !important;
        backdrop-filter: blur(8px) !important;
        border: 1px solid var(--border) !important;
        color: var(--text-1) !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 13px !important;
        border-radius: 12px !important;
        transition: all 0.3s !important;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: var(--accent-1) !important;
        box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.15), 0 0 40px rgba(99, 102, 241, 0.1) !important;
        outline: none !important;
    }
    .stSelectbox > div > div, .stNumberInput > div > div {
        background: rgba(5, 5, 16, 0.6) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
        color: var(--text-1) !important;
    }
    .stNumberInput input { color: var(--text-1) !important; }
    
    /* ═══ BUTTONS ═══ */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
        background-size: 200% 200%;
        color: white;
        border: none;
        font-weight: 700;
        letter-spacing: 2px;
        padding: 14px 32px;
        border-radius: 12px;
        font-size: 12px;
        text-transform: uppercase;
        font-family: 'JetBrains Mono', monospace;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
        box-shadow: 
            0 4px 20px rgba(99, 102, 241, 0.3),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
        animation: gradient-shift 6s ease infinite;
    }
    @keyframes gradient-shift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    .stButton > button:hover {
        transform: translateY(-3px) scale(1.01);
        box-shadow: 
            0 12px 40px rgba(99, 102, 241, 0.5),
            0 0 60px rgba(168, 85, 247, 0.3),
            inset 0 1px 0 rgba(255, 255, 255, 0.3);
    }
    .stButton > button:active { transform: translateY(-1px) scale(0.99); }
    .stButton > button:disabled {
        background: rgba(30, 41, 59, 0.5);
        color: var(--text-3);
        transform: none;
        box-shadow: none;
        animation: none;
    }
    
    /* ═══ ANIMATED PROGRESS BAR ═══ */
    .nitro-progress-wrapper {
        margin: 20px 0;
        padding: 24px;
        background: linear-gradient(135deg, rgba(10, 10, 26, 0.9), rgba(20, 15, 45, 0.9));
        backdrop-filter: blur(20px);
        border: 1px solid var(--border);
        border-radius: 16px;
        box-shadow: 0 0 40px rgba(99, 102, 241, 0.15);
    }
    .nitro-progress-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 14px;
        font-family: 'JetBrains Mono', monospace;
    }
    .nitro-progress-label {
        font-size: 12px;
        color: var(--text-1);
        font-weight: 600;
        letter-spacing: 1px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .nitro-spinner {
        width: 14px; height: 14px;
        border: 2px solid rgba(99, 102, 241, 0.2);
        border-top-color: var(--accent-2);
        border-right-color: var(--accent-3);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    
    .nitro-progress-percent {
        font-size: 24px;
        font-weight: 800;
        background: linear-gradient(135deg, var(--accent-1), var(--accent-3));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-family: 'JetBrains Mono', monospace;
        letter-spacing: -1px;
        min-width: 100px;
        text-align: right;
    }
    
    .nitro-progress-track {
        position: relative;
        height: 12px;
        background: rgba(5, 5, 16, 0.8);
        border-radius: 100px;
        overflow: hidden;
        border: 1px solid var(--border);
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.4);
    }
    .nitro-progress-fill {
        position: absolute;
        top: 0; left: 0; bottom: 0;
        background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899, #06b6d4, #6366f1);
        background-size: 300% 100%;
        border-radius: 100px;
        transition: width 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        animation: gradient-flow 3s linear infinite;
        box-shadow: 
            0 0 20px rgba(168, 85, 247, 0.6),
            0 0 40px rgba(99, 102, 241, 0.3);
    }
    @keyframes gradient-flow {
        0% { background-position: 0% 50%; }
        100% { background-position: 300% 50%; }
    }
    .nitro-progress-fill::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.4) 50%, transparent 100%);
        animation: shimmer 1.5s linear infinite;
    }
    @keyframes shimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
    }
    
    .nitro-progress-meta {
        display: flex;
        justify-content: space-between;
        margin-top: 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: var(--text-3);
        letter-spacing: 0.5px;
    }
    .nitro-progress-phase {
        color: var(--accent-2);
        font-weight: 600;
        text-transform: uppercase;
    }
    
    /* ═══ SHIMMER PLACEHOLDER ═══ */
    .nitro-shimmer {
        width: 100%;
        aspect-ratio: 1;
        background: linear-gradient(90deg,
            rgba(10, 10, 26, 0.6) 0%,
            rgba(99, 102, 241, 0.15) 40%,
            rgba(168, 85, 247, 0.15) 50%,
            rgba(236, 72, 153, 0.15) 60%,
            rgba(10, 10, 26, 0.6) 100%);
        background-size: 300% 100%;
        animation: shimmer-bg 2s linear infinite;
        border-radius: 16px;
        border: 1px solid var(--border);
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-3);
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        letter-spacing: 2px;
    }
    @keyframes shimmer-bg {
        0% { background-position: 100% 0; }
        100% { background-position: -100% 0; }
    }
    
    /* ═══ MODEL CARDS ═══ */
    .mcard {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 16px;
        align-items: center;
        padding: 16px 20px;
        background: linear-gradient(135deg, rgba(10, 10, 26, 0.6), rgba(20, 15, 45, 0.6));
        backdrop-filter: blur(12px);
        border: 1px solid var(--border);
        border-radius: 14px;
        margin-bottom: 10px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .mcard:hover {
        border-color: var(--border-hover);
        transform: translateX(6px);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.2), -8px 0 20px rgba(168, 85, 247, 0.15);
    }
    .mkey {
        color: var(--accent-2);
        font-weight: 700;
        font-size: 15px;
        font-family: 'JetBrains Mono', monospace;
        letter-spacing: -0.3px;
    }
    .mname { color: var(--text-2); font-size: 13px; margin-top: 4px; font-weight: 500; }
    .minfo {
        color: var(--text-3);
        font-size: 11px;
        margin-top: 6px;
        font-family: 'JetBrains Mono', monospace;
    }
    .cheap { background: linear-gradient(135deg, rgba(74, 222, 128, 0.15), rgba(74, 222, 128, 0.05)); color: var(--neon-green); border: 1px solid rgba(74, 222, 128, 0.3); }
    .mid   { background: linear-gradient(135deg, rgba(251, 191, 36, 0.15), rgba(251, 191, 36, 0.05)); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }
    .high  { background: linear-gradient(135deg, rgba(244, 114, 182, 0.15), rgba(244, 114, 182, 0.05)); color: var(--neon-pink); border: 1px solid rgba(244, 114, 182, 0.3); }
    .cost-badge {
        padding: 10px 16px;
        border-radius: 10px;
        font-weight: 700;
        font-size: 15px;
        font-family: 'JetBrains Mono', monospace;
        min-width: 80px;
        text-align: center;
    }
    .tag {
        display: inline-block;
        background: rgba(99, 102, 241, 0.15);
        color: var(--accent-1);
        padding: 3px 8px;
        border-radius: 5px;
        font-size: 9px;
        font-weight: 700;
        margin-left: 6px;
        letter-spacing: 1px;
        border: 1px solid rgba(99, 102, 241, 0.2);
    }
    
    /* ═══ METRICS ═══ */
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        background: linear-gradient(135deg, var(--accent-1), var(--accent-3));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 24px !important;
        font-weight: 800 !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-3) !important;
        text-transform: uppercase !important;
        font-size: 10px !important;
        letter-spacing: 2px !important;
        font-family: 'JetBrains Mono', monospace !important;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(10, 10, 26, 0.6), rgba(20, 15, 45, 0.4));
        backdrop-filter: blur(8px);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 14px 18px;
    }
    
    /* ═══ IMAGE OUTPUT ═══ */
    .stImage img {
        border-radius: 16px;
        box-shadow: 
            0 12px 40px rgba(99, 102, 241, 0.2),
            0 0 60px rgba(168, 85, 247, 0.1);
        transition: all 0.4s;
    }
    .stImage img:hover {
        transform: scale(1.01);
        box-shadow: 
            0 20px 60px rgba(99, 102, 241, 0.35),
            0 0 80px rgba(168, 85, 247, 0.2);
    }
    
    /* ═══ ALERTS ═══ */
    .stAlert {
        background: rgba(10, 10, 26, 0.8) !important;
        backdrop-filter: blur(12px) !important;
        border: 1px solid var(--border) !important;
        border-radius: 12px !important;
    }
    
    /* ═══ CHECKBOX ═══ */
    .stCheckbox { color: var(--text-2) !important; }
    
    /* Scrollbar */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: rgba(5, 5, 16, 0.5); }
    ::-webkit-scrollbar-thumb { 
        background: linear-gradient(180deg, var(--accent-1), var(--accent-2));
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--accent-3); }
    
    /* Caption */
    [data-testid="stCaptionContainer"] {
        color: var(--text-3) !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 11px !important;
        letter-spacing: 0.5px !important;
    }
</style>
""", unsafe_allow_html=True)

# HEADER
st.markdown("""
<div class="nitro-hero">
    <div class="nitro-hero-inner">
        <div>
            <div class="nitro-brand">IMG<span class="dash">·</span>NITRO</div>
            <div class="nitro-tag">Automated Neural Image Generation · v2.0</div>
        </div>
        <div class="nitro-status">
            <div class="pulse-dot"></div>
            <span>PIPELINE READY</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# STATE
if "models" not in st.session_state:
    try: st.session_state.models = run(fetch_models())
    except Exception as e:
        st.session_state.models = []
        st.error(f"Models load error: {e}")
if "images" not in st.session_state: st.session_state.images = []
if "last_result" not in st.session_state: st.session_state.last_result = None

# PHASE LABELS
PHASE_LABELS = {
    "init": "Initializing pipeline",
    "account": "Provisioning account",
    "signup": "Creating new account",
    "submit": "Submitting to render engine",
    "render": "Rendering neural image",
    "download": "Downloading assets",
}

def render_progress(percent, phase, elapsed, eta, extra=""):
    """Render ultra-modern progress bar HTML."""
    percent = max(0, min(99.99, percent))
    label = PHASE_LABELS.get(phase, phase.upper())
    if extra: label += f" · {extra}"
    return f"""
    <div class="nitro-progress-wrapper">
        <div class="nitro-progress-header">
            <div class="nitro-progress-label">
                <div class="nitro-spinner"></div>
                <span>{label}</span>
            </div>
            <div class="nitro-progress-percent">{percent:.2f}%</div>
        </div>
        <div class="nitro-progress-track">
            <div class="nitro-progress-fill" style="width: {percent:.4f}%;"></div>
        </div>
        <div class="nitro-progress-meta">
            <span>ELAPSED · <span style="color: var(--text-1);">{elapsed:.2f}s</span></span>
            <span class="nitro-progress-phase">{phase.upper()}</span>
            <span>ETA · <span style="color: var(--text-1);">{eta:.2f}s</span></span>
        </div>
    </div>
    """

def shimmer_placeholder():
    return '<div class="nitro-shimmer">AWAITING GENERATION</div>'

# TABS
tab_gen, tab_bulk, tab_models = st.tabs(["  GENERATE  ", "  BULK  ", "  MODELS  "])

# ═══════════ TAB GENERATE ═══════════
with tab_gen:
    col_l, col_r = st.columns([1, 1.6], gap="large")
    
    with col_l:
        st.markdown('<div class="sec-t">PROMPT</div>', unsafe_allow_html=True)
        prompt = st.text_area("p", height=140, label_visibility="collapsed",
                              placeholder="Describe your vision in vivid detail...")
        
        st.markdown('<div class="sec-t">MODEL</div>', unsafe_allow_html=True)
        models = st.session_state.models or []
        m_sel = None
        if models:
            sorted_m = sorted(models, key=lambda x: (_mc(x), _mk(x)))
            labels = []
            for m in sorted_m:
                c = _mc(m)
                icon = "◉" if c <= 10 else "◐" if c <= 15 else "○"
                labels.append(f"{icon}  {_mk(m):<28} — {c:>3}cr")
            sel = st.selectbox("m", range(len(labels)),
                               format_func=lambda i: labels[i], label_visibility="collapsed")
            m_sel = sorted_m[sel]
        else:
            st.warning("No models loaded")
        
        c1, c2 = st.columns(2)
        with c1:
            dims = _mdims(m_sel) if m_sel else ["1:1"]
            if not dims: dims = ["1:1"]
            dim_sel = st.selectbox("Aspect ratio", dims)
        with c2:
            max_c = _mocl(m_sel) if m_sel else 4
            count = st.number_input("Count", 1, max_c or 4, 1)
        
        ref_urls = None
        if m_sel and m_sel.get("referenceImage"):
            st.markdown('<div class="sec-t">REFERENCE IMAGE</div>', unsafe_allow_html=True)
            ref = st.text_input("r", placeholder="https://...", label_visibility="collapsed")
            if ref.strip(): ref_urls = [ref.strip()]
        
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        gen_btn = st.button("▶  GENERATE", use_container_width=True,
                            disabled=not m_sel or not prompt.strip())
    
    with col_r:
        st.markdown('<div class="sec-t">OUTPUT</div>', unsafe_allow_html=True)
        output_slot = st.empty()
        metrics_slot = st.empty()
        progress_slot = st.empty()
        
        # Show existing images or shimmer
        if st.session_state.images and not gen_btn:
            r = st.session_state.last_result
            if r:
                with metrics_slot.container():
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Time", f"{r.duration_s:.2f}s")
                    m2.metric("Cost", f"{r.credits_used}cr")
                    m3.metric("Model", r.model[:12])
                    m4.metric("Images", len(st.session_state.images))
            with output_slot.container():
                cols = st.columns(min(2, len(st.session_state.images)))
                for i, img in enumerate(st.session_state.images):
                    with cols[i % len(cols)]:
                        st.image(img, use_container_width=True)
        elif not gen_btn:
            output_slot.markdown(shimmer_placeholder(), unsafe_allow_html=True)
    
    # ═══════════ GENERATION WITH LIVE PROGRESS ═══════════
    if gen_btn:
        st.session_state.images = []
        output_slot.markdown(shimmer_placeholder(), unsafe_allow_html=True)
        metrics_slot.empty()
        
        # Shared state between async task and UI thread
        progress_state = {
            "phase": "init",
            "status": "",
            "pid": "",
            "est_time": _mtime(m_sel) + 15,  # +15s buffer for signup/setup
        }
        
        # Container for background thread result
        result_holder = {"result": None, "error": None, "done": False}
        
        def gen_worker():
            try:
                res = run(do_generate(
                    prompt=prompt,
                    model_key=_mk(m_sel),
                    dimension=dim_sel,
                    count=int(count),
                    reference_urls=ref_urls,
                    progress_state=progress_state,
                ))
                result_holder["result"] = res
            except Exception as e:
                result_holder["error"] = e
            finally:
                result_holder["done"] = True
        
        # Start background thread
        t = threading.Thread(target=gen_worker, daemon=True)
        t.start()
        
        # ═══ LIVE PROGRESS LOOP ═══
        start = time.perf_counter()
        est = progress_state["est_time"]
        last_render = 0
        
        while not result_holder["done"]:
            elapsed = time.perf_counter() - start
            
            # Non-linear progress: fast start, slow near end
            # Uses exponential decay to approach but never reach 100%
            raw_ratio = elapsed / max(est, 1)
            # Sigmoid-like: 1 - exp(-x) but capped
            progress = (1 - pow(2.718281828, -raw_ratio * 1.8)) * 99.5
            progress = min(progress, 98.5)
            
            phase = progress_state.get("phase", "init")
            status = progress_state.get("status", "")
            pid = progress_state.get("pid", "")
            
            eta = max(0, est - elapsed)
            extra = pid if pid else status
            
            progress_slot.markdown(
                render_progress(progress, phase, elapsed, eta, extra),
                unsafe_allow_html=True,
            )
            
            time.sleep(0.05)  # 20 FPS
            
            # Safety: after 5 min bail out (though thread will keep polling)
            if elapsed > 400:
                break
        
        t.join(timeout=1)
        
        elapsed_final = time.perf_counter() - start
        
        if result_holder["error"]:
            err = result_holder["error"]
            progress_slot.error(f"**{type(err).__name__}**\n\n{str(err)[:400]}")
            output_slot.markdown(shimmer_placeholder(), unsafe_allow_html=True)
        else:
            result = result_holder["result"]
            
            # Final 100% render
            progress_slot.markdown(f"""
            <div class="nitro-progress-wrapper" style="border-color: rgba(74, 222, 128, 0.4); box-shadow: 0 0 40px rgba(74, 222, 128, 0.2);">
                <div class="nitro-progress-header">
                    <div class="nitro-progress-label" style="color: var(--neon-green);">
                        ✓ RENDER COMPLETE
                    </div>
                    <div class="nitro-progress-percent" style="background: linear-gradient(135deg, #4ade80, #22d3ee); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">100.00%</div>
                </div>
                <div class="nitro-progress-track">
                    <div class="nitro-progress-fill" style="width: 100%; background: linear-gradient(90deg, #4ade80, #22d3ee, #4ade80); animation: gradient-flow 2s linear infinite;"></div>
                </div>
                <div class="nitro-progress-meta">
                    <span>TOTAL · <span style="color: var(--text-1);">{elapsed_final:.2f}s</span></span>
                    <span class="nitro-progress-phase" style="color: var(--neon-green);">SUCCESS</span>
                    <span>IMAGES · <span style="color: var(--text-1);">{len(result.urls)}</span></span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Download images
            images = []
            for url in result.urls:
                data = run(download_image(url))
                if data:
                    try:
                        images.append(Image.open(io.BytesIO(data)))
                    except: pass
            
            st.session_state.images = images
            st.session_state.last_result = result
            
            with metrics_slot.container():
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Time", f"{result.duration_s:.2f}s")
                m2.metric("Cost", f"{result.credits_used}cr")
                m3.metric("Model", result.model[:12])
                m4.metric("Images", len(images))
            
            with output_slot.container():
                if images:
                    cols = st.columns(min(2, len(images)))
                    for i, img in enumerate(images):
                        with cols[i % len(cols)]:
                            st.image(img, use_container_width=True)
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            st.download_button(
                                f"↓ Download #{i+1}",
                                buf.getvalue(),
                                file_name=f"nitro_{int(time.time())}_{i}.png",
                                mime="image/png",
                                key=f"dl_{i}_{time.time()}",
                                use_container_width=True,
                            )
                else:
                    st.warning("Pipeline returned no images")


# ═══════════ TAB BULK ═══════════
with tab_bulk:
    st.markdown('<div class="sec-t">BULK PROMPTS</div>', unsafe_allow_html=True)
    st.caption("One prompt per line · accounts rotate automatically")
    
    bulk_prompts = st.text_area("b", height=220,
        placeholder="a red dragon flying over a volcano\na blue phoenix in aurora skies\na cybernetic samurai...",
        label_visibility="collapsed")
    
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        models = st.session_state.models or []
        bulk_m = None
        if models:
            sorted_m = sorted(models, key=lambda x: _mc(x))
            blabels = [f"{_mk(m)} — {_mc(m)}cr" for m in sorted_m]
            bidx = st.selectbox("Model", range(len(blabels)),
                                format_func=lambda i: blabels[i], key="bm")
            bulk_m = sorted_m[bidx]
    with bc2:
        bulk_dim = st.selectbox("Aspect", _mdims(bulk_m) or ["1:1"] if bulk_m else ["1:1"], key="bd")
    with bc3:
        bulk_conc = st.number_input("Concurrency", 1, 8, 3, key="bc")
    
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    bulk_go = st.button("▶  RUN BULK PIPELINE", use_container_width=True, disabled=not bulk_m)
    
    if bulk_go:
        prompts = [p.strip() for p in bulk_prompts.split("\n") if p.strip()]
        if not prompts:
            st.error("Provide at least one prompt")
        else:
            progress_slot_bulk = st.empty()
            results_area = st.container()
            
            state = {"done": 0, "total": len(prompts), "results": [None] * len(prompts)}
            
            async def bulk_run():
                sem = asyncio.Semaphore(int(bulk_conc))
                async def one(i, p):
                    async with sem:
                        try:
                            r = await do_generate(prompt=p, model_key=_mk(bulk_m),
                                                  dimension=bulk_dim)
                            state["results"][i] = r
                        except Exception as e:
                            state["results"][i] = e
                        state["done"] += 1
                await asyncio.gather(*(one(i, p) for i, p in enumerate(prompts)))
            
            holder = {"done": False, "error": None}
            def worker():
                try: run(bulk_run())
                except Exception as e: holder["error"] = e
                finally: holder["done"] = True
            
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            
            start = time.perf_counter()
            per_prompt = _mtime(bulk_m) + 5
            est_total = (len(prompts) / int(bulk_conc)) * per_prompt
            
            while not holder["done"]:
                elapsed = time.perf_counter() - start
                done = state["done"]
                # Blend real progress with time-based
                real_prog = (done / len(prompts)) * 100
                time_prog = (1 - pow(2.718281828, -elapsed / max(est_total, 1) * 1.8)) * 99
                progress = max(real_prog, min(time_prog, 98)) if done < len(prompts) else 99
                
                eta = max(0, est_total - elapsed)
                
                progress_slot_bulk.markdown(
                    render_progress(progress, "render", elapsed, eta,
                                    f"{done}/{len(prompts)}"),
                    unsafe_allow_html=True,
                )
                time.sleep(0.1)
            
            t.join(timeout=1)
            elapsed_final = time.perf_counter() - start
            
            ok = sum(1 for r in state["results"] if isinstance(r, Result))
            fail = len(state["results"]) - ok
            
            progress_slot_bulk.markdown(f"""
            <div class="nitro-progress-wrapper" style="border-color: rgba(74, 222, 128, 0.4);">
                <div class="nitro-progress-header">
                    <div class="nitro-progress-label" style="color: var(--neon-green);">✓ BULK COMPLETE</div>
                    <div class="nitro-progress-percent" style="background: linear-gradient(135deg, #4ade80, #22d3ee); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">100.00%</div>
                </div>
                <div class="nitro-progress-track">
                    <div class="nitro-progress-fill" style="width: 100%; background: linear-gradient(90deg, #4ade80, #22d3ee, #4ade80);"></div>
                </div>
                <div class="nitro-progress-meta">
                    <span>TOTAL · <span style="color: var(--text-1);">{elapsed_final:.2f}s</span></span>
                    <span class="nitro-progress-phase" style="color: var(--neon-green);">{ok} OK · {fail} FAIL</span>
                    <span>PROMPTS · <span style="color: var(--text-1);">{len(prompts)}</span></span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            with results_area:
                for i, r in enumerate(state["results"]):
                    if isinstance(r, Result) and r.urls:
                        st.markdown(f"**#{i+1}** · `{prompts[i][:70]}` · {r.duration_s:.2f}s")
                        cols = st.columns(min(len(r.urls), 4))
                        for j, url in enumerate(r.urls):
                            with cols[j % len(cols)]:
                                st.image(url, use_container_width=True)
                    else:
                        err = str(r) if isinstance(r, Exception) else "no output"
                        st.error(f"#{i+1} · {prompts[i][:60]} · {err[:80]}")


# ═══════════ TAB MODELS ═══════════
with tab_models:
    top_c1, top_c2, top_c3 = st.columns([2, 1, 1])
    with top_c1:
        st.markdown('<div class="sec-t">MODEL CATALOG</div>', unsafe_allow_html=True)
    with top_c2:
        filter_ref = st.checkbox("Reference support only")
    with top_c3:
        if st.button("↻  REFRESH", use_container_width=True):
            try:
                st.session_state.models = run(fetch_models(force=True))
                st.success(f"Reloaded {len(st.session_state.models)} models")
                st.rerun()
            except Exception as e:
                st.error(f"Refresh failed: {e}")
    
    models = st.session_state.models or []
    if filter_ref:
        models = [m for m in models if m.get("referenceImage")]
    
    st.caption(f"{len(models)} models · sorted by cost")
    
    for m in sorted(models, key=lambda x: _mc(x)):
        k, n, c = _mk(m), _mn(m), _mc(m)
        dims = " · ".join(_mdims(m)[:5])
        cost_cls = "cheap" if c <= 10 else "mid" if c <= 15 else "high"
        tags = ""
        if m.get("referenceImage"): tags += '<span class="tag">REF</span>'
        if m.get("cfg"): tags += '<span class="tag">CFG</span>'
        if m.get("seed"): tags += '<span class="tag">SEED</span>'
        max_out = _mocl(m)
        if max_out and max_out > 1: tags += f'<span class="tag">×{max_out}</span>'
        et = _mtime(m)
        
        st.markdown(f"""
        <div class="mcard">
            <div>
                <div><span class="mkey">{k}</span>{tags}</div>
                <div class="mname">{n}</div>
                <div class="minfo">aspects: {dims} · ~{et:.0f}s</div>
            </div>
            <div class="cost-badge {cost_cls}">{c}cr</div>
        </div>
        """, unsafe_allow_html=True)
