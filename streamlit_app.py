from __future__ import annotations
import asyncio, base64, json, os, random, re, string, time, io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx
import streamlit as st
from PIL import Image

# ═══════════ CONFIG ═══════════
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
    "accept-language": "en-US,en;q=0.9,it;q=0.8",
    "accept-encoding": "gzip, deflate, br, zstd",
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


# ═══════════ HTTP HELPERS ═══════════
def _client(timeout=30):
    """Client httpx con configurazione anti-bot ottimale."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        http2=False,
        headers=H_BASE,
        verify=True,
    )

async def _post(c, url, body, headers=None, ok=(200, 201), raw_body=False):
    hdr = {**H_BASE, **(headers or {})}
    if raw_body:
        r = await c.post(url, content=body, headers=hdr)
    else:
        r = await c.post(url, json=body, headers=hdr)
    if r.status_code not in ok:
        raise RuntimeError(f"POST {url} -> {r.status_code}: {r.text[:250]}")
    try:
        return r.json() if r.text else {}
    except Exception:
        return {"_raw": r.text}

async def _get(c, url, headers=None, params=None):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.get(url, headers=hdr, params=params)
    try:
        return r.status_code, (r.json() if r.text else {})
    except Exception:
        return r.status_code, {"_raw": r.text}


# ═══════════ 808 MAIL ═══════════
async def gen_email(c):
    for _ in range(3):
        try:
            r = await c.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1", timeout=10)
            if r.status_code == 200 and "@" in r.text:
                return r.text.strip()
        except Exception:
            await asyncio.sleep(0.3)
    return None

async def wait_otp(c, email, total=120):
    deadline = time.monotonic() + total
    while time.monotonic() < deadline:
        try:
            r = await c.get(
                f"{MAIL}/attendi/{email}",
                params={"mittente": "davinci", "codice": 1, "semplice": 1, "timeout": 15000},
                timeout=20,
            )
            if r.status_code == 200 and r.text.strip():
                m = _OTP_RE.search(r.text)
                if m:
                    return m.group(1)
            r2 = await c.get(f"{MAIL}/inbox/{email}", timeout=8)
            if r2.status_code == 200:
                try:
                    d = r2.json()
                    msgs = d if isinstance(d, list) else (d.get("dato") or d.get("messages") or [])
                    for msg in (msgs or [])[:5]:
                        if not isinstance(msg, dict):
                            continue
                        mid = msg.get("id")
                        if not mid:
                            continue
                        r3 = await c.get(f"{MAIL}/leggi/{email}/{mid}?semplice=1", timeout=8)
                        if r3.status_code == 200:
                            m = _OTP_RE.search(r3.text)
                            if m:
                                return m.group(1)
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(1.2)
    return None

def rand_pw(n=14):
    c = [
        random.choice(string.ascii_lowercase),
        random.choice(string.ascii_uppercase),
        random.choice(string.digits),
        random.choice("!@#$%"),
    ]
    c += random.choices(_PWC, k=n - 4)
    random.shuffle(c)
    return "".join(c)


# ═══════════ SIGNUP ═══════════
async def signup_one(status_cb=None):
    async with _client(timeout=45) as c:
        if status_cb: status_cb("Generating email...")
        email = await gen_email(c)
        if not email:
            raise RuntimeError("No email generated")
        password = rand_pw()

        if status_cb: status_cb(f"Registering {email[:30]}...")
        d = await _post(c, FB_SU, {
            "returnSecureToken": True, "email": email,
            "password": password, "clientType": "CLIENT_TYPE_WEB",
        }, H_FB)
        id_token = d["idToken"]
        refresh_token = d["refreshToken"]
        local_id = d["localId"]

        if status_cb: status_cb("Sending verification email...")
        await asyncio.gather(
            _post(c, f"{API}/email-verification-send", {"email": email}, H_JSON),
            _post(c, FB_LK, {"idToken": id_token}, H_FB),
            return_exceptions=True,
        )

        if status_cb: status_cb("Waiting for OTP (up to 2 min)...")
        code = await wait_otp(c, email)
        if not code:
            raise RuntimeError("OTP timeout")

        if status_cb: status_cb(f"Verifying OTP {code}...")
        v = await _post(c, f"{API}/email-verification-verify-code",
                        {"email": email, "code": code}, H_JSON)
        if not v.get("data", {}).get("verified"):
            raise RuntimeError("OTP verification failed")

        if status_cb: status_cb("Finalizing account...")
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


# ═══════════ MODELS ═══════════
_MODELS: Optional[list] = None

async def fetch_models(force=False):
    global _MODELS
    if _MODELS and not force:
        return _MODELS
    if MODELS_CACHE.exists() and not force:
        try:
            d = json.loads(MODELS_CACHE.read_text())
            _MODELS = d.get("data", d) if isinstance(d, dict) else d
            return _MODELS
        except Exception:
            pass
    async with _client(timeout=20) as c:
        r = await c.get(f"{CMS}/image-models", headers=H_BASE)
        if r.status_code != 200:
            raise RuntimeError(f"Models fetch failed: {r.status_code}")
        d = r.json()
        MODELS_CACHE.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        _MODELS = d.get("data", d) if isinstance(d, dict) else d
        return _MODELS

_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
def _mk(m): return m.get("key", "")
def _mn(m): return m.get("modelName") or m.get("name", "")
def _mp(m): return m.get("param", "")
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
        if any(_norm(c) == qn for c in [_mk(m), _mn(m), _mp(m)]):
            return m
    for m in models:
        for c in [_mk(m), _mn(m), _mp(m)]:
            cn = _norm(c)
            if cn and (qn in cn or cn in qn):
                return m
    return None

def resolve_dim(m, ud):
    dims = _mdims(m)
    if not dims: return ud
    if ud in dims: return ud
    ui = ud.lower().replace("x", ":")
    for c in DIM_ALIAS.get(ui, []):
        if c in dims:
            return c
    return dims[0]


# ═══════════ ACCOUNTS PERSISTENCE ═══════════
def load_accs():
    if not ACCS_FILE.exists():
        return []
    try:
        return json.loads(ACCS_FILE.read_text())
    except Exception:
        return []

def save_accs_sync(accs):
    try:
        ACCS_FILE.parent.mkdir(exist_ok=True, parents=True)
        tmp = ACCS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(accs, indent=2, ensure_ascii=False))
        os.replace(tmp, ACCS_FILE)
    except Exception:
        pass


# ═══════════ TOKEN ═══════════
async def refresh_tok(rt):
    async with _client(timeout=15) as c:
        r = await c.post(
            FB_TOK,
            content=f"grant_type=refresh_token&refresh_token={rt}",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "x-firebase-gmpid": FB_GMPID,
                "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web",
                "origin": "https://davinci.ai",
                "referer": "https://davinci.ai/",
                "user-agent": UA,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"Refresh failed: {r.status_code}")
        d = r.json()
        return d["id_token"], d["refresh_token"]

def _jwt(tok, f="exp"):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get(f)
    except Exception:
        return None

def _expired(tok, safety=60):
    e = _jwt(tok, "exp")
    return not e or time.time() >= (e - safety)

def _uid(tok): return _jwt(tok, "user_id") or _jwt(tok, "sub") or ""
def _email(tok): return _jwt(tok, "email") or ""


# ═══════════ RESPONSE PARSING ═══════════
def _pid(r):
    if isinstance(r, str) and len(r) > 8:
        return r
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
                or "storage.googleapis" in o or "firebasestorage" in o
            ):
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


# ═══════════ CREDITS ═══════════
async def check_credits(tok):
    try:
        async with _client(timeout=10) as c:
            st, body = await _get(c, f"{API}/user/credit", {"x-platform": "web", "x-token": tok})
            if st != 200: return 0
            d = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(d, dict):
                return int(d.get("credit") or d.get("balance") or d.get("amount") or 0)
            return int(d) if isinstance(d, (int, float)) else 0
    except Exception:
        return 0

async def _ensure_tok(acc):
    tok = acc.get("id_token", "")
    ref = acc.get("refresh_token", "")
    if _expired(tok) and ref:
        tok, ref = await refresh_tok(ref)
        acc["id_token"] = tok
        acc["refresh_token"] = ref
    return tok

async def scan_credits(accs, concurrency=20):
    sem = asyncio.Semaphore(concurrency)
    async def one(i, a):
        async with sem:
            try:
                tok = await _ensure_tok(a)
                return i, await check_credits(tok), None
            except Exception as e:
                return i, 0, str(e)[:50]
    return await asyncio.gather(*(one(i, a) for i, a in enumerate(accs)))


# ═══════════ ACCOUNT PICKER ═══════════
async def pick_account(need_cr=25, status_cb=None):
    accs = load_accs()
    if not accs:
        if status_cb: status_cb("No accounts, creating one...")
        new = await signup_one(status_cb=status_cb)
        accs.append(new)
        save_accs_sync(accs)
        new["_credits"] = 25
        return new

    if status_cb: status_cb(f"Scanning {len(accs)} accounts...")
    r = await scan_credits(accs)
    save_accs_sync(accs)
    valid = sorted([(i, cr) for i, cr, _ in r if cr >= need_cr], key=lambda x: -x[1])

    if valid:
        i, cr = valid[0]
        acc = accs[i]
        acc["_credits"] = cr
        if status_cb: status_cb(f"Using existing account ({cr}cr)")
        return acc

    if status_cb: status_cb("All accounts exhausted, creating new one...")
    new = await signup_one(status_cb=status_cb)
    accs.append(new)
    save_accs_sync(accs)
    new["_credits"] = 25
    return new


# ═══════════ POLLING ═══════════
async def _poll(c, tok, uid, pid, timeout=300, interval=2.0, status_cb=None):
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
                    if status_cb: status_cb(f"Status: {st}")
                if st in ("COMPLETED", "SUCCESS", "DONE", "FINISHED"):
                    return d
                if st in ("FAILED", "ERROR", "CANCELLED", "REJECTED"):
                    err = (d.get("error") or d.get("errorMessage") or d.get("message")
                           or d.get("failureReason") or d.get("reason") or "")
                    if isinstance(err, dict):
                        err = err.get("message") or err.get("description") or str(err)
                    raise RuntimeError(f"Generation {st}: {err}" if err else f"Generation {st}")
            elif r.status_code == 401:
                raise RuntimeError("Token expired during polling")
        except RuntimeError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"Polling timeout (last: {last})")


# ═══════════ PAYLOAD BUILDER ═══════════
def _build_payload(m, prompt, dim, count, art_style_id, ref_urls=None):
    mid = _mk(m)
    payload = {
        "prompt": prompt,
        "model": mid,
        "dimension": dim,
        "artStyleId": art_style_id,
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


# ═══════════ RESULT ═══════════
@dataclass
class ImageResult:
    process_id: str = ""
    prompt: str = ""
    model: str = ""
    dimension: str = ""
    status: str = ""
    urls: list = field(default_factory=list)
    credits_used: int = 0
    duration_s: float = 0.0
    account_email: str = ""
    error: str = ""


# ═══════════ GENERATE ═══════════
async def generate_image(id_token, prompt, model_key="NANO_BANANA_2", dimension="1:1",
                         art_style_id=0, image_count=1, reference_image_urls=None,
                         refresh_token="", timeout=300, status_cb=None):
    if _expired(id_token):
        if not refresh_token:
            raise RuntimeError("Token expired, no refresh_token")
        id_token, refresh_token = await refresh_tok(refresh_token)

    models = await fetch_models()
    m = find_model(models, model_key)
    if not m:
        raise RuntimeError(f"Model '{model_key}' not found")
    mid, dim, cost = _mk(m), resolve_dim(m, dimension), _mc(m)
    uid, email = _uid(id_token), _email(id_token)

    t0 = time.perf_counter()
    async with _client(timeout=45) as c:
        ah = {**H_JSON, "x-platform": "web", "x-token": id_token}
        payload = _build_payload(m, prompt, dim, image_count, art_style_id, ref_urls=reference_image_urls)
        endpoint = f"{API}/process/txt-image"

        if status_cb: status_cb("Submitting request...")
        resp = await _post(c, endpoint, payload, ah)
        pid = _pid(resp)
        if not pid:
            raise RuntimeError(f"No process ID returned: {resp}")
        if status_cb: status_cb(f"Job {pid[:12]} submitted, polling...")
        doc = await _poll(c, id_token, uid, pid, timeout, status_cb=status_cb)

    dur = time.perf_counter() - t0
    urls = _urls(doc)
    return ImageResult(
        process_id=pid, prompt=prompt, model=mid, dimension=dim,
        status=doc.get("status", "COMPLETED"), urls=urls,
        credits_used=cost, duration_s=dur, account_email=email,
    )

async def download_image(url):
    try:
        async with _client(timeout=60) as c:
            r = await c.get(url)
            if r.status_code == 200:
                return r.content
    except Exception:
        pass
    return None


# ═══════════ UNIFIED SYNC RUNNER ═══════════
def run_async(coro):
    """Esegue coroutine in modo compatibile con Streamlit."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try: loop.close()
        except: pass


# ═══════════════════════════════════════════════════════
# ═══════════   STREAMLIT UI   ═══════════════════════════
# ═══════════════════════════════════════════════════════

st.set_page_config(
    page_title="IMG-NITRO",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS
st.markdown("""
<style>
    /* Hide streamlit branding */
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px;}
    
    /* Header */
    .nitro-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 24px 32px;
        margin-bottom: 24px;
    }
    .nitro-title {
        font-size: 32px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #f1f5f9;
        margin: 0;
        font-family: 'SF Mono', 'Monaco', 'Courier New', monospace;
    }
    .nitro-subtitle {
        font-size: 13px;
        color: #94a3b8;
        margin-top: 6px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .nitro-badge {
        display: inline-block;
        background: #1e40af;
        color: #dbeafe;
        padding: 3px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 8px;
        letter-spacing: 0.5px;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: #0f172a;
        padding: 6px;
        border-radius: 8px;
        border: 1px solid #1e293b;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        color: #94a3b8;
        border-radius: 6px;
        padding: 10px 20px;
        font-weight: 500;
        font-size: 14px;
    }
    .stTabs [aria-selected="true"] {
        background: #1e293b !important;
        color: #f1f5f9 !important;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
        color: white;
        border: none;
        font-weight: 600;
        letter-spacing: 0.3px;
        padding: 10px 24px;
        border-radius: 8px;
        transition: all 0.2s;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
    }
    .stButton > button:disabled {
        background: #334155;
        color: #64748b;
    }
    
    /* Inputs */
    .stTextArea textarea, .stTextInput input {
        background: #0f172a !important;
        border: 1px solid #334155 !important;
        color: #f1f5f9 !important;
        font-family: 'SF Mono', 'Monaco', monospace !important;
    }
    .stSelectbox > div > div {
        background: #0f172a !important;
        border: 1px solid #334155 !important;
    }
    
    /* Model card */
    .model-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 16px;
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 6px;
        margin-bottom: 6px;
        font-family: 'SF Mono', 'Monaco', monospace;
        font-size: 13px;
    }
    .model-key { color: #60a5fa; font-weight: 600; }
    .model-name { color: #cbd5e1; }
    .cost-cheap { color: #10b981; font-weight: 600; }
    .cost-mid { color: #f59e0b; font-weight: 600; }
    .cost-high { color: #ef4444; font-weight: 600; }
    .model-tag {
        display: inline-block;
        background: #1e293b;
        color: #94a3b8;
        padding: 2px 8px;
        border-radius: 3px;
        font-size: 10px;
        margin-left: 6px;
    }
    
    /* Log console */
    .log-console {
        background: #030712;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 16px;
        font-family: 'SF Mono', 'Monaco', monospace;
        font-size: 12px;
        color: #86efac;
        max-height: 300px;
        overflow-y: auto;
    }
    
    /* Metric */
    [data-testid="stMetricValue"] {
        font-family: 'SF Mono', 'Monaco', monospace;
        color: #60a5fa;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="nitro-header">
    <div class="nitro-title">IMG-NITRO<span class="nitro-badge">v2.0</span></div>
    <div class="nitro-subtitle">Neural Image Generation Pipeline — Auto-Rotation Engine</div>
</div>
""", unsafe_allow_html=True)

# Session state
if "accounts" not in st.session_state:
    st.session_state.accounts = load_accs()
if "models" not in st.session_state:
    try:
        st.session_state.models = run_async(fetch_models())
    except Exception as e:
        st.session_state.models = []
        st.error(f"Model fetch error: {e}")
if "logs" not in st.session_state:
    st.session_state.logs = []
if "last_images" not in st.session_state:
    st.session_state.last_images = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{ts}] {msg}")
    st.session_state.logs = st.session_state.logs[-100:]

# Tabs
tab_gen, tab_bulk, tab_acc, tab_models = st.tabs([
    "GENERATE", "BULK", "ACCOUNTS", "MODELS"
])

# ═══════════ TAB GENERATE ═══════════
with tab_gen:
    col_left, col_right = st.columns([1, 1.4], gap="large")

    with col_left:
        st.markdown("##### Configuration")
        prompt = st.text_area("Prompt", height=120, placeholder="Describe your image...", label_visibility="collapsed")

        c1, c2 = st.columns(2)
        with c1:
            models = st.session_state.models or []
            if models:
                sorted_m = sorted(models, key=lambda x: _mc(x))
                labels = [f"{_mk(m)} — {_mc(m)}cr" for m in sorted_m]
                sel_idx = st.selectbox("Model", range(len(labels)), format_func=lambda i: labels[i])
                m_sel = sorted_m[sel_idx]
            else:
                st.warning("No models loaded")
                m_sel = None
        with c2:
            if m_sel:
                dims = _mdims(m_sel) or ["1:1"]
                dim_sel = st.selectbox("Dimension", dims)
            else:
                dim_sel = "1:1"

        c3, c4 = st.columns(2)
        with c3:
            count = st.number_input("Image count", 1, 4, 1)
        with c4:
            art_style = st.number_input("Art style ID", 0, 100, 0)

        ref_img = None
        if m_sel and m_sel.get("referenceImage"):
            st.caption(f"This model supports reference images (up to {m_sel.get('referenceImageLimit', 1)})")
            ref_url = st.text_input("Reference image URL", placeholder="https://...")
            if ref_url.strip():
                ref_img = [ref_url.strip()]

        generate_btn = st.button("GENERATE", type="primary", use_container_width=True, disabled=not m_sel)

    with col_right:
        st.markdown("##### Output")
        img_placeholder = st.empty()
        status_placeholder = st.empty()
        info_placeholder = st.empty()

        if st.session_state.last_images:
            with img_placeholder.container():
                cols = st.columns(min(2, len(st.session_state.last_images)))
                for i, img in enumerate(st.session_state.last_images):
                    with cols[i % len(cols)]:
                        st.image(img, use_container_width=True)

    if generate_btn:
        if not prompt.strip():
            st.error("Prompt is required")
        elif not m_sel:
            st.error("No model selected")
        else:
            need = _mc(m_sel)
            status_box = status_placeholder.container()
            log_area = status_box.empty()
            
            log(f"Starting generation: {_mk(m_sel)} @ {dim_sel} ({need}cr)")

            def cb(msg):
                log(msg)
                log_area.info(msg)

            try:
                # Pick account
                acc = run_async(pick_account(need_cr=need, status_cb=cb))
                st.session_state.accounts = load_accs()
                log(f"Account ready: {acc['email'][:35]} ({acc.get('_credits', '?')}cr)")

                # Generate
                result = run_async(generate_image(
                    id_token=acc["id_token"],
                    refresh_token=acc.get("refresh_token", ""),
                    prompt=prompt,
                    model_key=_mk(m_sel),
                    dimension=dim_sel,
                    art_style_id=int(art_style),
                    image_count=int(count),
                    reference_image_urls=ref_img,
                    status_cb=cb,
                ))

                log(f"Complete: {len(result.urls)} images in {result.duration_s:.1f}s")

                # Download & display
                images = []
                for url in result.urls:
                    data = run_async(download_image(url))
                    if data:
                        img = Image.open(io.BytesIO(data))
                        images.append(img)

                st.session_state.last_images = images
                status_placeholder.empty()

                with info_placeholder.container():
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Status", "OK")
                    m2.metric("Time", f"{result.duration_s:.1f}s")
                    m3.metric("Cost", f"{result.credits_used}cr")
                    m4.metric("Images", len(images))

                with img_placeholder.container():
                    if images:
                        cols = st.columns(min(2, len(images)))
                        for i, img in enumerate(images):
                            with cols[i % len(cols)]:
                                st.image(img, use_container_width=True)
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                st.download_button(
                                    f"Download #{i+1}",
                                    buf.getvalue(),
                                    file_name=f"nitro_{int(time.time())}_{i}.png",
                                    mime="image/png",
                                    key=f"dl_{i}_{time.time()}",
                                )
                    else:
                        st.warning("No images returned")

            except Exception as e:
                log(f"ERROR: {type(e).__name__}: {str(e)[:120]}")
                status_placeholder.error(f"Generation failed: {type(e).__name__}\n\n{str(e)[:300]}")

    # Live log
    if st.session_state.logs:
        st.markdown("##### Log")
        log_html = "<div class='log-console'>" + "<br>".join(st.session_state.logs[-15:]) + "</div>"
        st.markdown(log_html, unsafe_allow_html=True)


# ═══════════ TAB BULK ═══════════
with tab_bulk:
    st.markdown("##### Bulk Generation")
    st.caption("One prompt per line. Accounts rotate automatically.")

    bulk_prompts = st.text_area("Prompts", height=200, placeholder="prompt 1\nprompt 2\nprompt 3...")

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        models = st.session_state.models or []
        if models:
            sorted_m = sorted(models, key=lambda x: _mc(x))
            bulk_labels = [f"{_mk(m)} — {_mc(m)}cr" for m in sorted_m]
            bidx = st.selectbox("Model", range(len(bulk_labels)),
                                format_func=lambda i: bulk_labels[i], key="bulk_model")
            bulk_m = sorted_m[bidx]
        else:
            bulk_m = None
    with bc2:
        if bulk_m:
            bulk_dim = st.selectbox("Dimension", _mdims(bulk_m) or ["1:1"], key="bulk_dim")
        else:
            bulk_dim = "1:1"
    with bc3:
        bulk_conc = st.number_input("Concurrency", 1, 10, 3, key="bulk_conc")

    if st.button("RUN BULK", type="primary", use_container_width=True, disabled=not bulk_m):
        prompts = [p.strip() for p in bulk_prompts.split("\n") if p.strip()]
        if not prompts:
            st.error("No prompts provided")
        else:
            need = _mc(bulk_m)
            progress = st.progress(0)
            status = st.empty()
            results_area = st.container()
            all_images = []

            async def bulk_run():
                sem = asyncio.Semaphore(int(bulk_conc))
                results = [None] * len(prompts)

                async def one(i, prompt):
                    async with sem:
                        try:
                            acc = await pick_account(need_cr=need)
                            r = await generate_image(
                                id_token=acc["id_token"],
                                refresh_token=acc.get("refresh_token", ""),
                                prompt=prompt,
                                model_key=_mk(bulk_m),
                                dimension=bulk_dim,
                            )
                            results[i] = r
                            return r
                        except Exception as e:
                            results[i] = e
                            return None

                await asyncio.gather(*(one(i, p) for i, p in enumerate(prompts)))
                return results

            try:
                status.info(f"Processing {len(prompts)} prompts...")
                results = run_async(bulk_run())
                
                ok = sum(1 for r in results if isinstance(r, ImageResult))
                fail = len(results) - ok
                
                progress.progress(1.0)
                status.success(f"Complete: {ok} successful, {fail} failed")

                with results_area:
                    for i, r in enumerate(results):
                        if isinstance(r, ImageResult) and r.urls:
                            st.markdown(f"**#{i+1}** — {prompts[i][:60]}")
                            cols = st.columns(min(len(r.urls), 4))
                            for j, url in enumerate(r.urls):
                                with cols[j % len(cols)]:
                                    st.image(url, use_container_width=True)
                        else:
                            err = str(r) if isinstance(r, Exception) else "Failed"
                            st.error(f"#{i+1} — {prompts[i][:60]}: {err[:100]}")

            except Exception as e:
                status.error(f"Bulk failed: {e}")


# ═══════════ TAB ACCOUNTS ═══════════
with tab_acc:
    st.markdown("##### Account Manager")

    ac1, ac2, ac3 = st.columns([1, 1, 2])
    with ac1:
        n_sign = st.number_input("Create N accounts", 1, 20, 1, key="n_sign")
    with ac2:
        st.markdown("<br>", unsafe_allow_html=True)
        do_sign = st.button("CREATE", use_container_width=True)
    with ac3:
        st.markdown("<br>", unsafe_allow_html=True)
        do_check = st.button("SCAN CREDITS", use_container_width=True)

    if do_sign:
        prog = st.progress(0)
        sts = st.empty()
        for i in range(int(n_sign)):
            sts.info(f"Creating account {i+1}/{n_sign}...")
            try:
                new = run_async(signup_one(status_cb=lambda m: sts.info(f"[{i+1}/{n_sign}] {m}")))
                accs = load_accs()
                accs.append(new)
                save_accs_sync(accs)
                st.session_state.accounts = accs
                sts.success(f"[{i+1}/{n_sign}] Created: {new['email']}")
            except Exception as e:
                sts.error(f"[{i+1}/{n_sign}] Failed: {str(e)[:100]}")
            prog.progress((i + 1) / n_sign)
        st.rerun()

    if do_check:
        accs = st.session_state.accounts
        if not accs:
            st.warning("No accounts to check")
        else:
            with st.spinner(f"Scanning {len(accs)} accounts..."):
                r = run_async(scan_credits(accs))
                save_accs_sync(accs)
            
            total = 0
            rows = []
            for i, cr, err in sorted(r, key=lambda x: -x[1]):
                total += cr
                rows.append({
                    "email": accs[i].get("email", "?")[:45],
                    "credits": cr,
                    "status": "OK" if cr >= 25 else "LOW" if cr > 0 else "EMPTY",
                    "error": err or "",
                })
            
            st.dataframe(rows, use_container_width=True, hide_index=True)
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Accounts", len(accs))
            m2.metric("Total Credits", total)
            m3.metric("Est. Premium Gens", f"{total // 25}")

    st.divider()
    st.caption(f"Storage: {ACCS_FILE} — {len(st.session_state.accounts)} accounts loaded")


# ═══════════ TAB MODELS ═══════════
with tab_models:
    st.markdown("##### Available Models")
    
    if st.button("REFRESH FROM API"):
        try:
            st.session_state.models = run_async(fetch_models(force=True))
            st.success(f"Loaded {len(st.session_state.models)} models")
        except Exception as e:
            st.error(f"Fetch failed: {e}")

    filter_ref = st.checkbox("Only models with reference image support")
    
    models = st.session_state.models or []
    if filter_ref:
        models = [m for m in models if m.get("referenceImage")]
    
    st.caption(f"Showing {len(models)} models")

    for m in sorted(models, key=lambda x: _mc(x)):
        k, n, c = _mk(m), _mn(m), _mc(m)
        dims = ",".join(_mdims(m)[:6])
        cost_class = "cost-cheap" if c <= 10 else "cost-mid" if c <= 15 else "cost-high"
        ref_tag = '<span class="model-tag">REF</span>' if m.get("referenceImage") else ""
        cfg_tag = '<span class="model-tag">CFG</span>' if m.get("cfg") else ""
        seed_tag = '<span class="model-tag">SEED</span>' if m.get("seed") else ""
        max_out = _mocl(m)
        multi_tag = f'<span class="model-tag">×{max_out}</span>' if max_out and max_out > 1 else ""
        
        st.markdown(f"""
        <div class="model-row">
            <div>
                <span class="model-key">{k}</span>
                <span class="model-name"> — {n}</span>
                {ref_tag}{cfg_tag}{seed_tag}{multi_tag}
                <div style="font-size:11px;color:#64748b;margin-top:4px;">
                    dims: {dims} · imgs/acc: {25 // c if c > 0 else '?'}
                </div>
            </div>
            <div class="{cost_class}">{c}cr</div>
        </div>
        """, unsafe_allow_html=True)
