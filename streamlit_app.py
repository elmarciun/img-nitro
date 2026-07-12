from __future__ import annotations
import asyncio, base64, json, os, random, re, string, time, io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx
import streamlit as st
from PIL import Image

# ═══════════════════════════════════════════════════════════
#  CONFIG
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
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate",
    "origin": "https://davinci.ai",
    "referer": "https://davinci.ai/",
    "user-agent": UA,
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}
H_JSON = {"content-type": "application/json"}
H_FB = {**H_JSON, "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web", "x-firebase-gmpid": FB_GMPID}

DIM_ALIAS = {
    "1:1": ["1:1", "square", "square_hd"],
    "16:9": ["16:9", "landscape_16_9", "landscape"],
    "9:16": ["9:16", "portrait_16_9", "portrait"],
    "4:3": ["4:3", "landscape_4_3"],
    "3:4": ["3:4", "portrait_4_3"],
    "21:9": ["21:9"], "4:5": ["4:5"], "5:4": ["5:4"],
    "2:3": ["2:3"], "3:2": ["3:2"], "auto": ["auto"],
}
_OTP_RE = re.compile(r"\b(\d{6})\b")
_PWC = string.ascii_letters + string.digits + "!@#$%"

# ═══════════════════════════════════════════════════════════
#  HTTP LAYER
# ═══════════════════════════════════════════════════════════
def _client(timeout=30):
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        headers=H_BASE,
    )

async def _post(c, url, body, headers=None, ok=(200, 201), raw=False):
    hdr = {**H_BASE, **(headers or {})}
    if raw:
        r = await c.post(url, content=body, headers=hdr)
    else:
        r = await c.post(url, json=body, headers=hdr)
    if r.status_code not in ok:
        raise RuntimeError(f"POST {url}: {r.status_code} {r.text[:200]}")
    try: return r.json() if r.text else {}
    except: return {}

async def _get(c, url, headers=None, params=None):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.get(url, headers=hdr, params=params)
    try: return r.status_code, (r.json() if r.text else {})
    except: return r.status_code, {}

# ═══════════════════════════════════════════════════════════
#  MAIL / OTP
# ═══════════════════════════════════════════════════════════
async def gen_email(c):
    for _ in range(3):
        try:
            r = await c.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1", timeout=10)
            if r.status_code == 200 and "@" in r.text:
                return r.text.strip()
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
    c += random.choices(_PWC, k=n - 4)
    random.shuffle(c)
    return "".join(c)

# ═══════════════════════════════════════════════════════════
#  SIGNUP
# ═══════════════════════════════════════════════════════════
async def signup_one():
    async with _client(timeout=45) as c:
        email = await gen_email(c)
        if not email: raise RuntimeError("Email generation failed")
        password = rand_pw()

        d = await _post(c, FB_SU, {
            "returnSecureToken": True, "email": email,
            "password": password, "clientType": "CLIENT_TYPE_WEB",
        }, H_FB)
        id_token = d["idToken"]
        refresh_token = d["refreshToken"]
        local_id = d["localId"]

        await asyncio.gather(
            _post(c, f"{API}/email-verification-send", {"email": email}, H_JSON),
            _post(c, FB_LK, {"idToken": id_token}, H_FB),
            return_exceptions=True,
        )

        code = await wait_otp(c, email)
        if not code: raise RuntimeError("OTP timeout")

        v = await _post(c, f"{API}/email-verification-verify-code",
                        {"email": email, "code": code}, H_JSON)
        if not v.get("data", {}).get("verified"):
            raise RuntimeError("OTP verify failed")

        d2 = await _post(c, FB_SI, {
            "returnSecureToken": True, "email": email,
            "password": password, "clientType": "CLIENT_TYPE_WEB",
        }, H_FB)
        id_token = d2["idToken"]
        refresh_token = d2["refreshToken"]
        ah = {**H_JSON, "x-platform": "web", "x-token": id_token}

        await asyncio.gather(
            _post(c, FB_LK, {"idToken": id_token}, H_FB),
            _get(c, f"{API}/user/credit", ah),
            _get(c, f"{API}/get-user-profile", ah),
            _post(c, f"{PAY}/create-user", {"email": email}, ah),
            return_exceptions=True,
        )

        return {
            "email": email, "password": password, "local_id": local_id,
            "id_token": id_token, "refresh_token": refresh_token, "credits": 25,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

# ═══════════════════════════════════════════════════════════
#  MODELS
# ═══════════════════════════════════════════════════════════
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
        if r.status_code != 200:
            raise RuntimeError(f"Models fetch: {r.status_code}")
        d = r.json()
        try:
            MODELS_CACHE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        except: pass
        _MODELS = d.get("data", d) if isinstance(d, dict) else d
        return _MODELS

_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _mk(m): return m.get("key", "")
def _mn(m): return m.get("modelName") or m.get("name", "")
def _mc(m):
    try: return int(m.get("creditSpend") or m.get("cost") or 0)
    except: return 0
def _mdims(m): return [d.get("dimensionKey", "") for d in (m.get("dimensions") or []) if d.get("dimensionKey")]
def _mocl(m):
    v = m.get("outputCountLimit")
    return int(v) if v else None

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

# ═══════════════════════════════════════════════════════════
#  ACCOUNTS STORAGE
# ═══════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════
#  TOKEN
# ═══════════════════════════════════════════════════════════
async def refresh_tok(rt):
    async with _client(timeout=15) as c:
        r = await c.post(FB_TOK, content=f"grant_type=refresh_token&refresh_token={rt}",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "x-firebase-gmpid": FB_GMPID,
                "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web",
                "origin": "https://davinci.ai", "referer": "https://davinci.ai/",
                "user-agent": UA,
            })
        if r.status_code != 200:
            raise RuntimeError(f"Refresh: {r.status_code}")
        d = r.json()
        return d["id_token"], d["refresh_token"]

def _jwt(tok, f="exp"):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get(f)
    except: return None

def _expired(tok, safety=60):
    e = _jwt(tok, "exp")
    return not e or time.time() >= (e - safety)

def _uid(tok): return _jwt(tok, "user_id") or _jwt(tok, "sub") or ""
def _email(tok): return _jwt(tok, "email") or ""

# ═══════════════════════════════════════════════════════════
#  RESPONSE PARSING
# ═══════════════════════════════════════════════════════════
def _pid(r):
    if isinstance(r, str) and len(r) > 8: return r
    if isinstance(r, list) and r:
        f = r[0]
        if isinstance(f, str): return f
        if isinstance(f, dict):
            for k in ("processId", "process_id", "id", "jobId", "job_id", "taskId", "uuid"):
                if f.get(k): return str(f[k])
    if isinstance(r, dict):
        for k in ("processId", "process_id", "id", "jobId", "job_id", "taskId", "uuid"):
            if r.get(k): return str(r[k])
        for w in ("data", "result", "response"):
            if r.get(w):
                p = _pid(r[w])
                if p: return p
    return ""

def _fs_val(v):
    if v is None: return None
    for k, fn in [("stringValue", str), ("integerValue", int), ("doubleValue", float),
                  ("booleanValue", bool), ("timestampValue", str)]:
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
            if o.startswith("http") and (
                any(o.lower().endswith(e) for e in [".png", ".jpg", ".jpeg", ".webp", ".gif"])
                or "storage.googleapis" in o or "firebasestorage" in o):
                urls.append(o)
        elif isinstance(o, list):
            for it in o: _rec(it)
        elif isinstance(o, dict):
            for k in ("url", "imageUrl", "image_url", "src", "downloadUrl", "publicUrl", "assetUrl", "outputUrl"):
                if isinstance(o.get(k), str) and o[k].startswith("http"):
                    urls.append(o[k])
            for v in o.values(): _rec(v)
    for k in ("outputs", "output", "images", "results", "urls", "imageUrls", "outputImages", "assets", "data"):
        v = doc.get(k)
        if v: _rec(v)
    seen = set()
    return [u for u in urls if not (u in seen or seen.add(u))]

# ═══════════════════════════════════════════════════════════
#  CREDITS
# ═══════════════════════════════════════════════════════════
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
    tok = acc.get("id_token", "")
    ref = acc.get("refresh_token", "")
    if _expired(tok) and ref:
        try:
            tok, ref = await refresh_tok(ref)
            acc["id_token"] = tok
            acc["refresh_token"] = ref
        except: pass
    return tok

# ═══════════════════════════════════════════════════════════
#  AUTO ACCOUNT PICKER (100% automatic)
# ═══════════════════════════════════════════════════════════
async def auto_pick_account(need_cr, log=None):
    """Trova il primo account con credit sufficienti, altrimenti ne crea uno nuovo."""
    accs = load_accs()
    
    # Try existing accounts (ordered by last credits known, descending)
    accs_sorted = sorted(accs, key=lambda a: -int(a.get("credits", 0)))
    for acc in accs_sorted:
        try:
            tok = await _ensure_tok(acc)
            cr = await check_credits(tok)
            acc["credits"] = cr
            if cr >= need_cr:
                save_accs(accs)
                if log: log(f"Account ready ({cr}cr available)")
                return acc
        except: continue
    
    save_accs(accs)
    
    # Create new one
    if log: log("Provisioning new account (30-90s)...")
    new = await signup_one()
    accs.append(new)
    save_accs(accs)
    if log: log("New account provisioned successfully")
    return new

# ═══════════════════════════════════════════════════════════
#  POLLING
# ═══════════════════════════════════════════════════════════
async def _poll(c, tok, uid, pid, timeout=300, interval=2.0, log=None):
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
                    if log: log(f"Rendering: {st}")
                if st in ("COMPLETED", "SUCCESS", "DONE", "FINISHED"): return d
                if st in ("FAILED", "ERROR", "CANCELLED", "REJECTED"):
                    err = (d.get("error") or d.get("errorMessage") or d.get("message") or "")
                    if isinstance(err, dict): err = err.get("message") or str(err)
                    raise RuntimeError(f"Generation {st}: {err}" if err else f"Generation {st}")
            elif r.status_code == 401:
                raise RuntimeError("Token invalidated")
        except RuntimeError: raise
        except: pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timeout (last: {last})")

# ═══════════════════════════════════════════════════════════
#  PAYLOAD & GENERATE
# ═══════════════════════════════════════════════════════════
def _build_payload(m, prompt, dim, count, art_style_id, ref_urls=None):
    payload = {
        "prompt": prompt, "model": _mk(m),
        "dimension": dim, "artStyleId": art_style_id,
    }
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
                      reference_urls=None, art_style_id=0, log=None):
    models = await fetch_models()
    m = find_model(models, model_key)
    if not m: raise RuntimeError(f"Model '{model_key}' not found")
    need = _mc(m)
    dim = resolve_dim(m, dimension)

    if log: log(f"Preparing generation: {_mk(m)} @ {dim}")
    acc = await auto_pick_account(need, log=log)
    
    tok = await _ensure_tok(acc)
    uid = _uid(tok)
    if not uid: raise RuntimeError("Invalid session token")
    
    t0 = time.perf_counter()
    async with _client(timeout=45) as c:
        ah = {**H_JSON, "x-platform": "web", "x-token": tok}
        payload = _build_payload(m, prompt, dim, count, art_style_id, ref_urls=reference_urls)
        
        if log: log("Submitting to render pipeline...")
        resp = await _post(c, f"{API}/process/txt-image", payload, ah)
        pid = _pid(resp)
        if not pid: raise RuntimeError(f"Job not created: {resp}")
        
        if log: log(f"Job accepted [{pid[:12]}]")
        doc = await _poll(c, tok, uid, pid, log=log)

    dur = time.perf_counter() - t0
    return Result(
        urls=_urls(doc), process_id=pid, model=_mk(m),
        dimension=dim, duration_s=dur, credits_used=need,
    )

async def download_image(url):
    try:
        async with _client(timeout=60) as c:
            r = await c.get(url)
            if r.status_code == 200: return r.content
    except: pass
    return None

# ═══════════════════════════════════════════════════════════
#  ASYNC RUNNER
# ═══════════════════════════════════════════════════════════
def run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try: loop.close()
        except: pass


# ═══════════════════════════════════════════════════════════
#  STREAMLIT UI
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title="IMG-NITRO", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 1.5rem 2rem; max-width: 1500px; }
    
    /* Header */
    .nitro-header {
        background: linear-gradient(135deg, #0a0e1a 0%, #14192a 50%, #1a1f3a 100%);
        border: 1px solid #2a3050;
        border-radius: 14px;
        padding: 26px 34px;
        margin-bottom: 24px;
        position: relative;
        overflow: hidden;
    }
    .nitro-header::before {
        content: '';
        position: absolute;
        top: 0; right: 0; width: 300px; height: 100%;
        background: radial-gradient(circle at right, rgba(99, 102, 241, 0.15) 0%, transparent 70%);
    }
    .nitro-title {
        font-size: 34px;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #f8fafc;
        margin: 0;
        font-family: 'SF Mono', Menlo, monospace;
        position: relative;
    }
    .nitro-title span.accent { color: #6366f1; }
    .nitro-sub {
        font-size: 12px;
        color: #64748b;
        margin-top: 8px;
        letter-spacing: 2px;
        text-transform: uppercase;
        font-weight: 500;
    }
    .status-pill {
        display: inline-block;
        background: #0f5132;
        color: #86efac;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 10px;
        font-weight: 700;
        margin-left: 12px;
        letter-spacing: 1px;
        vertical-align: middle;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: #0a0e1a;
        padding: 4px;
        border-radius: 10px;
        border: 1px solid #1e293b;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        color: #64748b;
        border-radius: 7px;
        padding: 10px 22px;
        font-weight: 600;
        font-size: 13px;
        letter-spacing: 0.5px;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #1e293b 0%, #1e2942 100%) !important;
        color: #f1f5f9 !important;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
        color: white;
        border: none;
        font-weight: 700;
        letter-spacing: 1px;
        padding: 12px 28px;
        border-radius: 10px;
        transition: all 0.2s;
        font-size: 13px;
        text-transform: uppercase;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.4);
    }
    .stButton > button:disabled {
        background: #1e293b;
        color: #475569;
        transform: none;
    }
    
    /* Inputs */
    .stTextArea textarea, .stTextInput input {
        background: #0f172a !important;
        border: 1px solid #1e293b !important;
        color: #e2e8f0 !important;
        font-family: 'SF Mono', Menlo, monospace !important;
        font-size: 13px !important;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1) !important;
    }
    .stSelectbox > div > div, .stNumberInput > div > div > input {
        background: #0f172a !important;
        border: 1px solid #1e293b !important;
        color: #e2e8f0 !important;
    }
    
    /* Model card */
    .mcard {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 16px;
        align-items: center;
        padding: 14px 18px;
        background: linear-gradient(135deg, #0f172a 0%, #131b31 100%);
        border: 1px solid #1e293b;
        border-radius: 10px;
        margin-bottom: 8px;
        transition: all 0.2s;
    }
    .mcard:hover {
        border-color: #6366f1;
        transform: translateX(4px);
    }
    .mkey { color: #818cf8; font-weight: 700; font-size: 14px; font-family: 'SF Mono', monospace; }
    .mname { color: #94a3b8; font-size: 13px; margin-top: 2px; }
    .minfo { color: #475569; font-size: 11px; margin-top: 4px; font-family: 'SF Mono', monospace; }
    .cheap { background: #052e16; color: #4ade80; }
    .mid   { background: #422006; color: #fbbf24; }
    .high  { background: #450a0a; color: #f87171; }
    .cost-badge {
        padding: 8px 14px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 15px;
        font-family: 'SF Mono', monospace;
        min-width: 70px;
        text-align: center;
    }
    .tag {
        display: inline-block;
        background: #1e293b;
        color: #94a3b8;
        padding: 2px 7px;
        border-radius: 3px;
        font-size: 9px;
        font-weight: 700;
        margin-left: 4px;
        letter-spacing: 0.5px;
    }
    
    /* Log console */
    .log-box {
        background: #030712;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 14px 18px;
        font-family: 'SF Mono', Menlo, monospace;
        font-size: 12px;
        color: #4ade80;
        line-height: 1.7;
        max-height: 240px;
        overflow-y: auto;
    }
    .log-box .ts { color: #64748b; }
    
    /* Metric */
    [data-testid="stMetricValue"] {
        font-family: 'SF Mono', Menlo, monospace;
        color: #818cf8;
        font-size: 22px;
    }
    [data-testid="stMetricLabel"] {
        color: #64748b;
        text-transform: uppercase;
        font-size: 10px;
        letter-spacing: 1px;
    }
    
    /* Section title */
    .sec-title {
        color: #94a3b8;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 2px;
        font-weight: 700;
        margin: 16px 0 10px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #1e293b;
    }
    
    /* Alerts */
    .stAlert {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# HEADER
st.markdown("""
<div class="nitro-header">
    <div class="nitro-title">IMG<span class="accent">-</span>NITRO<span class="status-pill">● ONLINE</span></div>
    <div class="nitro-sub">Automated Neural Image Generation · Fully Managed Pipeline</div>
</div>
""", unsafe_allow_html=True)

# SESSION STATE
if "models" not in st.session_state:
    try: st.session_state.models = run(fetch_models())
    except Exception as e:
        st.session_state.models = []
        st.error(f"Failed to load models: {e}")
if "logs" not in st.session_state:
    st.session_state.logs = []
if "images" not in st.session_state:
    st.session_state.images = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None

def log(msg):
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append((ts, msg))
    st.session_state.logs = st.session_state.logs[-30:]

# TABS
tab_gen, tab_bulk, tab_models = st.tabs(["  GENERATE  ", "  BULK  ", "  MODELS  "])

# ═══════════════════════════════════════════════════════════
#  TAB: GENERATE
# ═══════════════════════════════════════════════════════════
with tab_gen:
    col_l, col_r = st.columns([1, 1.6], gap="large")
    
    with col_l:
        st.markdown('<div class="sec-title">Prompt</div>', unsafe_allow_html=True)
        prompt = st.text_area("prompt", height=130, label_visibility="collapsed",
                              placeholder="A cyberpunk samurai in a neon-lit alleyway...")
        
        st.markdown('<div class="sec-title">Model Selection</div>', unsafe_allow_html=True)
        models = st.session_state.models or []
        if models:
            sorted_m = sorted(models, key=lambda x: (_mc(x), _mk(x)))
            labels = []
            for m in sorted_m:
                c = _mc(m)
                icon = "●" if c <= 10 else "◐" if c <= 15 else "○"
                labels.append(f"{icon}  {_mk(m):<26} — {c:>3}cr")
            sel = st.selectbox("model", range(len(labels)),
                               format_func=lambda i: labels[i], label_visibility="collapsed")
            m_sel = sorted_m[sel]
        else:
            m_sel = None
            st.warning("No models available")
        
        c1, c2 = st.columns(2)
        with c1:
            if m_sel:
                dims = _mdims(m_sel) or ["1:1"]
                dim_sel = st.selectbox("Aspect", dims)
            else:
                dim_sel = "1:1"
        with c2:
            max_c = _mocl(m_sel) if m_sel else 4
            count = st.number_input("Count", 1, max_c or 4, 1)
        
        ref_urls = None
        if m_sel and m_sel.get("referenceImage"):
            st.markdown('<div class="sec-title">Reference Image (optional)</div>', unsafe_allow_html=True)
            ref = st.text_input("ref", placeholder="https://image-url...", label_visibility="collapsed")
            if ref.strip(): ref_urls = [ref.strip()]
        
        st.markdown("<br>", unsafe_allow_html=True)
        gen_btn = st.button("● GENERATE", use_container_width=True, disabled=not m_sel or not prompt.strip())
    
    with col_r:
        st.markdown('<div class="sec-title">Output</div>', unsafe_allow_html=True)
        out_area = st.container()
        metrics_area = st.empty()
        status_area = st.empty()
        
        if st.session_state.images and not gen_btn:
            r = st.session_state.last_result
            if r:
                with metrics_area.container():
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Time", f"{r.duration_s:.1f}s")
                    m2.metric("Cost", f"{r.credits_used}cr")
                    m3.metric("Model", r.model[:14])
                    m4.metric("Images", len(st.session_state.images))
            with out_area:
                cols = st.columns(min(2, len(st.session_state.images)))
                for i, img in enumerate(st.session_state.images):
                    with cols[i % len(cols)]:
                        st.image(img, use_container_width=True)
    
    # GENERATION
    if gen_btn:
        st.session_state.logs = []
        st.session_state.images = []
        
        try:
            with status_area.container():
                with st.spinner("Processing..."):
                    result = run(do_generate(
                        prompt=prompt,
                        model_key=_mk(m_sel),
                        dimension=dim_sel,
                        count=int(count),
                        reference_urls=ref_urls,
                        log=log,
                    ))
                    
                    log(f"Downloading {len(result.urls)} image(s)...")
                    images = []
                    for url in result.urls:
                        data = run(download_image(url))
                        if data:
                            images.append(Image.open(io.BytesIO(data)))
                    
                    st.session_state.images = images
                    st.session_state.last_result = result
                    log(f"Complete: {len(images)} image(s) rendered in {result.duration_s:.1f}s")
            
            status_area.empty()
            
            with metrics_area.container():
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Time", f"{result.duration_s:.1f}s")
                m2.metric("Cost", f"{result.credits_used}cr")
                m3.metric("Model", result.model[:14])
                m4.metric("Images", len(images))
            
            with out_area:
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
                    st.warning("No images returned by the pipeline")
        
        except Exception as e:
            log(f"ERROR: {type(e).__name__}: {str(e)[:120]}")
            status_area.error(f"**{type(e).__name__}**\n\n{str(e)[:400]}")
    
    # LOG CONSOLE
    if st.session_state.logs:
        st.markdown('<div class="sec-title">Pipeline Log</div>', unsafe_allow_html=True)
        html = "<div class='log-box'>"
        for ts, msg in st.session_state.logs[-15:]:
            html += f"<span class='ts'>[{ts}]</span> {msg}<br>"
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  TAB: BULK
# ═══════════════════════════════════════════════════════════
with tab_bulk:
    st.markdown('<div class="sec-title">Bulk Prompts</div>', unsafe_allow_html=True)
    st.caption("One prompt per line — accounts rotate automatically")
    
    bulk_prompts = st.text_area("bulk", height=220,
        placeholder="a red dragon\na blue phoenix\na green forest spirit\n...",
        label_visibility="collapsed")
    
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        models = st.session_state.models or []
        if models:
            sorted_m = sorted(models, key=lambda x: _mc(x))
            blabels = [f"{_mk(m)} — {_mc(m)}cr" for m in sorted_m]
            bidx = st.selectbox("Model", range(len(blabels)),
                                format_func=lambda i: blabels[i], key="bm")
            bulk_m = sorted_m[bidx]
        else:
            bulk_m = None
    with bc2:
        bulk_dim = st.selectbox("Aspect", _mdims(bulk_m) or ["1:1"] if bulk_m else ["1:1"], key="bd")
    with bc3:
        bulk_conc = st.number_input("Concurrency", 1, 8, 3, key="bc")
    
    st.markdown("<br>", unsafe_allow_html=True)
    bulk_go = st.button("● RUN BULK PIPELINE", use_container_width=True, disabled=not bulk_m)
    
    if bulk_go:
        prompts = [p.strip() for p in bulk_prompts.split("\n") if p.strip()]
        if not prompts:
            st.error("Provide at least one prompt")
        else:
            progress = st.progress(0)
            status = st.empty()
            results_area = st.container()
            
            async def bulk_run():
                sem = asyncio.Semaphore(int(bulk_conc))
                results = [None] * len(prompts)
                completed = [0]
                
                async def one(i, p):
                    async with sem:
                        try:
                            r = await do_generate(prompt=p, model_key=_mk(bulk_m),
                                                  dimension=bulk_dim, log=None)
                            results[i] = r
                        except Exception as e:
                            results[i] = e
                        completed[0] += 1
                        return i
                
                tasks = [asyncio.create_task(one(i, p)) for i, p in enumerate(prompts)]
                for t in asyncio.as_completed(tasks):
                    await t
                    progress.progress(completed[0] / len(prompts))
                    status.info(f"Processing... {completed[0]}/{len(prompts)}")
                return results
            
            try:
                status.info(f"Starting bulk generation of {len(prompts)} prompts...")
                results = run(bulk_run())
                
                ok = sum(1 for r in results if isinstance(r, Result))
                fail = len(results) - ok
                
                progress.progress(1.0)
                status.success(f"✓ Complete — {ok} succeeded, {fail} failed")
                
                with results_area:
                    for i, r in enumerate(results):
                        if isinstance(r, Result) and r.urls:
                            st.markdown(f"**#{i+1}** · `{prompts[i][:70]}` · {r.duration_s:.1f}s")
                            cols = st.columns(min(len(r.urls), 4))
                            for j, url in enumerate(r.urls):
                                with cols[j % len(cols)]:
                                    st.image(url, use_container_width=True)
                        else:
                            err = str(r) if isinstance(r, Exception) else "no output"
                            st.error(f"#{i+1} · {prompts[i][:60]} · {err[:80]}")
            except Exception as e:
                status.error(f"Bulk error: {e}")


# ═══════════════════════════════════════════════════════════
#  TAB: MODELS
# ═══════════════════════════════════════════════════════════
with tab_models:
    top_c1, top_c2, top_c3 = st.columns([2, 1, 1])
    with top_c1:
        st.markdown('<div class="sec-title">Model Catalog</div>', unsafe_allow_html=True)
    with top_c2:
        filter_ref = st.checkbox("Reference support only")
    with top_c3:
        if st.button("↻ REFRESH", use_container_width=True):
            try:
                st.session_state.models = run(fetch_models(force=True))
                st.success(f"Reloaded {len(st.session_state.models)} models")
                st.rerun()
            except Exception as e:
                st.error(f"Refresh failed: {e}")
    
    models = st.session_state.models or []
    if filter_ref:
        models = [m for m in models if m.get("referenceImage")]
    
    st.caption(f"{len(models)} models available · sorted by cost")
    
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
        
        st.markdown(f"""
        <div class="mcard">
            <div>
                <div><span class="mkey">{k}</span>{tags}</div>
                <div class="mname">{n}</div>
                <div class="minfo">aspects: {dims}</div>
            </div>
            <div class="cost-badge {cost_cls}">{c}cr</div>
        </div>
        """, unsafe_allow_html=True)
