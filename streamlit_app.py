"""
Nitro · Neural Image Generation Pipeline
Fully automated · Multi-model · AI prompt enhancement · Reference upload
"""
from __future__ import annotations
import asyncio, base64, json, os, random, re, string, time, io, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx
import streamlit as st
from PIL import Image

# ═══════════════════════════════════════════════════════════════════
FB_KEY = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs"
FB_GMPID = "1:378221804375:web:32bf22971597e5ef92dc12"
FB_SU  = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}"
FB_LK  = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FB_KEY}"
FB_SI  = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}"
FB_TOK = f"https://securetoken.googleapis.com/v1/token?key={FB_KEY}"
API    = "https://wl-api-web-prod.davinci.ai"
CMS    = "https://wl-cms-web-prod.davinci.ai"
PAY    = "https://payment.davinci.ai/api/v1/auth"
FS_BASE  = "https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents"
MAIL     = "https://mail808.elmarciun.workers.dev"
FILES808 = "https://808files.elmarciun.workers.dev"
NVIDIA   = "https://elmarcito-nvidia.hf.space/v1"

SD = Path(__file__).parent.resolve()
ACCS_FILE    = SD / "accounts.json"
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
H_FB   = {**H_JSON, "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web",
          "x-firebase-gmpid": FB_GMPID}

DIM_ALIAS = {
    "1:1": ["1:1", "square", "square_hd"],
    "16:9": ["16:9", "landscape_16_9", "landscape"],
    "9:16": ["9:16", "portrait_16_9", "portrait"],
    "4:3": ["4:3", "landscape_4_3"], "3:4": ["3:4", "portrait_4_3"],
    "21:9": ["21:9"], "4:5": ["4:5"], "5:4": ["5:4"],
    "2:3": ["2:3"], "3:2": ["3:2"], "auto": ["auto"],
}
DIM_LABEL = {
    "1:1": "Quadrato (1:1)", "16:9": "Orizzontale (16:9)",
    "9:16": "Verticale (9:16)", "4:3": "Classico (4:3)",
    "3:4": "Ritratto (3:4)", "21:9": "Ultra-wide (21:9)",
    "4:5": "Social (4:5)", "5:4": "Foto (5:4)",
    "2:3": "Poster (2:3)", "3:2": "Fotocamera (3:2)",
    "auto": "Automatico",
}

LLM_MODELS = {
    "auto":      {"key": "meta/llama-3.3-70b-instruct", "label": "Automatico (consigliato)"},
    "fast":      {"key": "meta/llama-3.1-8b-instruct",  "label": "Veloce (Llama 8B)"},
    "smart":     {"key": "meta/llama-3.3-70b-instruct", "label": "Intelligente (Llama 70B)"},
    "reasoning": {"key": "nvidia/nemotron-3-nano-omni", "label": "Ragionamento (Nemotron)"},
    "creative":  {"key": "qwen/qwen3-next-80b",         "label": "Creativo (Qwen 80B)"},
    "translate": {"key": "sarvamai/sarvam-m",           "label": "Traduzione"},
}

ENHANCE_SYS = """Sei un assistente esperto nella creazione di prompt per generatori di immagini AI.

Trasforma la descrizione dell'utente in un prompt IN INGLESE altamente dettagliato, cinematografico e visivamente ricco.

REGOLE:
1. Traduci sempre in inglese perfetto
2. Aggiungi dettagli visivi: illuminazione, atmosfera, stile, angolazione, materiali, colori
3. Se l'utente menziona PIÙ SOGGETTI (es. "goku che combatte drago e fenice"), assicurati che TUTTI i soggetti siano nel prompt finale
4. Mantieni fedelmente l'INTENZIONE originale, non aggiungere elementi non richiesti
5. Aggiungi termini di qualità: "highly detailed", "8k", "cinematic" o "epic anime style" quando appropriato
6. Rispondi SOLO con il prompt migliorato, senza spiegazioni né virgolette né prefissi
7. Massimo 100 parole

Esempi:
Input: "un gatto sul divano"
Output: A fluffy orange tabby cat resting on a plush grey velvet sofa, cozy living room with soft afternoon sunlight, warm ambient lighting, shallow depth of field, professional photography, highly detailed, 8k

Input: "goku che combatte drago rosso e fenice"
Output: Epic anime battle scene, Goku in Ultra Instinct form with silver hair and glowing aura, simultaneously fighting a massive red fire-breathing dragon and a majestic flame phoenix, dynamic action pose, energy blasts, dramatic sky, mountain battlefield, vibrant anime art style, highly detailed, cinematic composition"""

_OTP_RE = re.compile(r"\b(\d{6})\b")
_PWC = string.ascii_letters + string.digits + "!@#$%"

# Thread lock per accesso file account (fix bulk race condition)
_ACC_LOCK = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
def _client(timeout: int = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True, headers=H_BASE,
    )

async def _post(c, url, body, headers=None, ok=(200, 201), raw=False):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.post(url, content=body, headers=hdr) if raw else await c.post(url, json=body, headers=hdr)
    if r.status_code not in ok:
        raise RuntimeError(f"POST {url}: {r.status_code} {r.text[:200]}")
    try: return r.json() if r.text else {}
    except: return {}

async def _get(c, url, headers=None, params=None):
    hdr = {**H_BASE, **(headers or {})}
    r = await c.get(url, headers=hdr, params=params)
    try: return r.status_code, (r.json() if r.text else {})
    except: return r.status_code, {}


# ═══════════════════════════════════════════════════════════════════
async def gen_email(c) -> Optional[str]:
    for _ in range(3):
        try:
            r = await c.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1", timeout=10)
            if r.status_code == 200 and "@" in r.text:
                return r.text.strip()
        except: await asyncio.sleep(0.3)
    return None

async def wait_otp(c, email: str, total: int = 120) -> Optional[str]:
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

def rand_pw(n: int = 14) -> str:
    c = [random.choice(string.ascii_lowercase), random.choice(string.ascii_uppercase),
         random.choice(string.digits), random.choice("!@#$%")]
    c += random.choices(_PWC, k=n - 4); random.shuffle(c)
    return "".join(c)


# ═══════════════════════════════════════════════════════════════════
async def signup_one() -> dict:
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


# ═══════════════════════════════════════════════════════════════════
async def upload_808files(image_bytes: bytes, filename: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        try:
            r1 = await c.post(f"{FILES808}/api/token")
            if r1.status_code != 200: return None
            token_data = r1.json()
            if not token_data.get("ok"): return None
            token = token_data["token"]

            ext = filename.lower().split(".")[-1] if "." in filename else "png"
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
            files = {"file": (filename, image_bytes, mime)}
            data = {"token": token}
            r2 = await c.post("https://upload.gofile.io/uploadfile",
                              files=files, data=data)
            if r2.status_code != 200: return None
            gd = r2.json().get("data", {})
            if not gd.get("id"): return None

            servers = gd.get("servers", ["store1"])
            reg_body = {
                "token": token, "id": gd["id"],
                "server": servers[0] if servers else "store1",
                "filename": gd.get("name", filename),
                "folder_id": gd.get("parentFolder", ""),
                "folder_code": gd.get("parentFolderCode", ""),
                "download_page": gd.get("downloadPage", ""),
                "size": gd.get("size", len(image_bytes)),
                "mimetype": gd.get("mimetype", mime),
            }
            r3 = await c.post(f"{FILES808}/api/register", json=reg_body)
            if r3.status_code != 200: return None
            reg = r3.json()
            if reg.get("ok") and reg.get("stream"):
                return reg["stream"]
        except Exception as e:
            print(f"[808files] {e}")
    return None


# ═══════════════════════════════════════════════════════════════════
async def enhance_prompt(user_prompt: str,
                          model_key: str = "meta/llama-3.3-70b-instruct",
                          has_reference: bool = False) -> Optional[str]:
    system = ENHANCE_SYS
    if has_reference:
        system += "\n\nIMPORTANTE: L'utente sta usando un'IMMAGINE DI RIFERIMENTO. Integra nel prompt riferimenti come 'this person', 'this face', 'same identity as reference' mantenendo coerenza."
    body = {"message": user_prompt, "model": model_key, "system": system}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(f"{NVIDIA}/chat", json=body,
                             headers={"content-type": "application/json"})
            if r.status_code == 200:
                data = r.json()
                for k in ("response", "message", "content", "text", "answer", "reply"):
                    v = data.get(k) if isinstance(data, dict) else None
                    if isinstance(v, str) and v.strip():
                        return v.strip().strip('"').strip("'")
                if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                    for k in ("response", "message", "content", "text"):
                        v = data["data"].get(k)
                        if v: return str(v).strip().strip('"').strip("'")
                if isinstance(data, str): return data.strip()
        except Exception as e:
            print(f"[enhance] {e}")
    return None


# ═══════════════════════════════════════════════════════════════════
_MODELS: Optional[list] = None

async def fetch_models(force: bool = False) -> list:
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
def _mdims(m): return [d.get("dimensionKey","") for d in (m.get("dimensions") or []) if d.get("dimensionKey")]
def _mocl(m):
    v = m.get("outputCountLimit")
    return int(v) if v else None
def _mtime(m):
    v = m.get("outputTime") or m.get("estimatedTime") or m.get("avgTime")
    try: return float(v) if v else 15.0
    except: return 15.0
def _mc(m):
    try: return int(m.get("creditSpend") or m.get("cost") or 0)
    except: return 0

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


# ═══════════════════════════════════════════════════════════════════
def load_accs() -> list:
    with _ACC_LOCK:
        if not ACCS_FILE.exists(): return []
        try: return json.loads(ACCS_FILE.read_text(encoding="utf-8"))
        except: return []

def save_accs(accs: list):
    with _ACC_LOCK:
        try:
            ACCS_FILE.parent.mkdir(exist_ok=True, parents=True)
            tmp = ACCS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(accs, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, ACCS_FILE)
        except Exception as e:
            print(f"[save_accs] {e}")


# ═══════════════════════════════════════════════════════════════════
async def refresh_tok(rt: str):
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


# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
async def check_credits(tok):
    try:
        async with _client(timeout=10) as c:
            st_, body = await _get(c, f"{API}/user/credit", {"x-platform": "web", "x-token": tok})
            if st_ != 200: return 0
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


# Async lock separato per pick_account (evita signup paralleli inutili)
_PICK_LOCK = asyncio.Lock()

async def auto_pick_account(need_cr: int, progress_state=None, exclude_ids=None) -> dict:
    """Trova account con crediti; se nessuno disponibile ne crea uno nuovo (thread-safe)."""
    exclude_ids = exclude_ids or set()
    async with _PICK_LOCK:
        accs = load_accs()
        accs_sorted = sorted(accs, key=lambda a: -int(a.get("credits", 0)))
        for acc in accs_sorted:
            if acc.get("local_id") in exclude_ids:
                continue
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
        accs = load_accs()  # ricarica per non sovrascrivere modifiche parallele
        accs.append(new)
        save_accs(accs)
        return new


# ═══════════════════════════════════════════════════════════════════
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
                st_ = (d.get("status") or "").upper()
                if st_ != last:
                    last = st_
                    if progress_state: progress_state["status"] = st_
                if st_ in ("COMPLETED","SUCCESS","DONE","FINISHED"): return d
                if st_ in ("FAILED","ERROR","CANCELLED","REJECTED"):
                    err = (d.get("error") or d.get("errorMessage") or d.get("message") or "")
                    if isinstance(err, dict): err = err.get("message") or str(err)
                    raise RuntimeError(f"Generation {st_}: {err}" if err else f"Generation {st_}")
            elif r.status_code == 401: raise RuntimeError("Token invalidated")
        except RuntimeError: raise
        except: pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timeout (last: {last})")


# ═══════════════════════════════════════════════════════════════════
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
    original_prompt: str = ""
    final_prompt: str = ""


async def do_generate(prompt: str, model_key: str, dimension: str = "1:1",
                      count: int = 1, reference_urls=None, reference_bytes=None,
                      reference_filename: Optional[str] = None, art_style_id: int = 0,
                      enhance: bool = False,
                      enhance_model: str = "meta/llama-3.3-70b-instruct",
                      progress_state=None,
                      max_retries: int = 3) -> Result:
    models = await fetch_models()
    m = find_model(models, model_key)
    if not m: raise RuntimeError(f"Modello '{model_key}' non trovato")
    need = _mc(m); dim = resolve_dim(m, dimension)

    if progress_state:
        progress_state["phase"] = "init"
        progress_state["est_time"] = _mtime(m) + 15 + (25 if reference_bytes else 0) + (8 if enhance else 0)

    # Enhance
    final_prompt = prompt
    if enhance:
        if progress_state: progress_state["phase"] = "enhance"
        enhanced = await enhance_prompt(prompt, enhance_model,
                                         has_reference=bool(reference_bytes or reference_urls))
        if enhanced and len(enhanced) > 10:
            final_prompt = enhanced

    # Upload ref (una volta sola, prima del retry loop)
    final_ref_urls = list(reference_urls) if reference_urls else []
    if reference_bytes:
        if progress_state: progress_state["phase"] = "upload"
        uploaded_url = await upload_808files(reference_bytes, reference_filename or "reference.png")
        if not uploaded_url:
            raise RuntimeError("Upload immagine fallito")
        final_ref_urls.insert(0, uploaded_url)

    # Retry loop con account rotation
    tried_ids = set()
    last_err = None
    t0 = time.perf_counter()

    for attempt in range(max_retries):
        try:
            if progress_state: progress_state["phase"] = "account"
            acc = await auto_pick_account(need, progress_state=progress_state, exclude_ids=tried_ids)
            tried_ids.add(acc.get("local_id"))
            tok = await _ensure_tok(acc)
            uid = _uid(tok)
            if not uid:
                last_err = RuntimeError("Sessione non valida")
                continue

            if progress_state: progress_state["phase"] = "submit"
            async with _client(timeout=60) as c:
                ah = {**H_JSON, "x-platform": "web", "x-token": tok}
                payload = _build_payload(m, final_prompt, dim, count, art_style_id,
                                          ref_urls=final_ref_urls if final_ref_urls else None)
                resp = await _post(c, f"{API}/process/txt-image", payload, ah)
                pid = _pid(resp)
                if not pid:
                    last_err = RuntimeError(f"Job non creato: {resp}")
                    continue
                if progress_state:
                    progress_state["phase"] = "render"
                    progress_state["pid"] = pid[:12]
                doc = await _poll(c, tok, uid, pid, progress_state=progress_state)

            dur = time.perf_counter() - t0
            return Result(urls=_urls(doc), process_id=pid, model=_mk(m),
                          dimension=dim, duration_s=dur,
                          original_prompt=prompt, final_prompt=final_prompt)

        except Exception as e:
            last_err = e
            print(f"[gen attempt {attempt+1}] {type(e).__name__}: {e}")
            await asyncio.sleep(1.0 + attempt)
            continue

    raise RuntimeError(f"Generazione fallita dopo {max_retries} tentativi: {last_err}")


async def download_image(url: str) -> Optional[bytes]:
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
#                          STREAMLIT UI
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Nitro", layout="wide", initial_sidebar_state="collapsed")

if "theme" not in st.session_state: st.session_state.theme = "dark"
THEME = st.session_state.theme

# ═══ Palette ═══
if THEME == "dark":
    C = {
        "bg": "#08051a",
        "bg_2": "#120b2e",
        "bg_3": "#1b1240",
        "surface": "#17102e",
        "surface_h": "#221847",
        "border": "rgba(147, 112, 250, 0.15)",
        "border_h": "rgba(196, 132, 252, 0.5)",
        "text": "#faf5ff",
        "text_2": "#d8b4fe",
        "text_3": "#a78bfa",
        "accent": "#c084fc",
        "accent_2": "#a855f7",
        "accent_3": "#ec4899",
        "accent_h": "#d8b4fe",
        "danger": "#f87171",
        "success": "#4ade80",
        "info": "#60a5fa",
        "input_bg": "#0e0821",
        "shadow": "0 8px 32px rgba(139, 92, 246, 0.18)",
        "glow": "0 0 80px rgba(168, 85, 247, 0.25)",
        "btn_bg": "linear-gradient(135deg, #7c3aed 0%, #a855f7 40%, #ec4899 100%)",
        "btn_h": "linear-gradient(135deg, #a855f7 0%, #c084fc 40%, #f472b6 100%)",
        "prog_bg": "linear-gradient(90deg, #7c3aed, #a855f7, #ec4899, #a855f7, #7c3aed)",
        "code_bg": "#0a0518",
        "code_text": "#f3e8ff",
        "code_key": "#c084fc",
        "code_str": "#86efac",
        "code_num": "#fbbf24",
    }
else:
    C = {
        "bg": "#ffffff",
        "bg_2": "#fafafa",
        "bg_3": "#f0f0f0",
        "surface": "#ffffff",
        "surface_h": "#f7f7f8",
        "border": "#e5e5e7",
        "border_h": "#d0d0d5",
        "text": "#0d0d0d",
        "text_2": "#4a4a4a",
        "text_3": "#8e8e93",
        "accent": "#10a37f",
        "accent_2": "#10a37f",
        "accent_3": "#0d8968",
        "accent_h": "#0d8968",
        "danger": "#ef4444",
        "success": "#10a37f",
        "info": "#3b82f6",
        "input_bg": "#ffffff",
        "shadow": "0 1px 3px rgba(0, 0, 0, 0.05), 0 4px 12px rgba(0, 0, 0, 0.04)",
        "glow": "none",
        "btn_bg": "#10a37f",
        "btn_h": "#0d8968",
        "prog_bg": "linear-gradient(90deg, #10a37f, #14c19a, #10a37f)",
        "code_bg": "#fafafa",
        "code_text": "#1a1a1a",
        "code_key": "#7c3aed",
        "code_str": "#059669",
        "code_num": "#0284c7",
    }

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {{
    --bg: {C['bg']}; --bg-2: {C['bg_2']}; --bg-3: {C['bg_3']};
    --surface: {C['surface']}; --surface-h: {C['surface_h']};
    --border: {C['border']}; --border-h: {C['border_h']};
    --text: {C['text']}; --text-2: {C['text_2']}; --text-3: {C['text_3']};
    --accent: {C['accent']}; --accent-2: {C['accent_2']};
    --accent-3: {C['accent_3']}; --accent-h: {C['accent_h']};
    --danger: {C['danger']}; --success: {C['success']}; --info: {C['info']};
    --input-bg: {C['input_bg']};
    --shadow: {C['shadow']}; --glow: {C['glow']};
    --code-bg: {C['code_bg']}; --code-text: {C['code_text']};
    --code-key: {C['code_key']}; --code-str: {C['code_str']}; --code-num: {C['code_num']};
}}
* {{ box-sizing: border-box; }}
html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, sans-serif !important;
    color: var(--text) !important;
}}
.stApp {{
    background: var(--bg) !important;
    {"background-image: radial-gradient(ellipse 90% 60% at 15% 0%, rgba(168, 85, 247, 0.18), transparent 60%), radial-gradient(ellipse 70% 50% at 85% 20%, rgba(236, 72, 153, 0.12), transparent 60%), radial-gradient(ellipse 80% 60% at 50% 100%, rgba(124, 58, 237, 0.10), transparent 60%) !important; background-attachment: fixed !important;" if THEME == "dark" else ""}
}}
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding: 1.5rem 2rem 3rem !important; max-width: 1200px !important; }}

.nav {{ display: flex; align-items: center; justify-content: space-between;
    padding: 14px 22px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 18px; margin-bottom: 20px;
    {"box-shadow: var(--glow), inset 0 1px 0 rgba(255,255,255,0.05);" if THEME == "dark" else "box-shadow: var(--shadow);"} }}
.logo {{ display: flex; align-items: center; gap: 12px; font-size: 18px;
    font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
.logo-dot {{ width: 34px; height: 34px; background: {C['btn_bg']};
    border-radius: 11px; display: flex; align-items: center; justify-content: center;
    color: white; font-weight: 700; font-size: 16px; font-family: 'JetBrains Mono', monospace;
    {"box-shadow: 0 4px 20px rgba(168, 85, 247, 0.5), inset 0 1px 0 rgba(255,255,255,0.2);" if THEME == "dark" else "box-shadow: 0 2px 8px rgba(16, 163, 127, 0.3);"} }}
.badge {{ background: var(--bg-2); color: var(--text-2); padding: 3px 10px;
    border-radius: 8px; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
    margin-left: 4px; border: 1px solid var(--border); }}

div[data-testid="stButton"]:has(button[kind="secondary"]) button {{
    background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border) !important; padding: 8px 16px !important;
    font-size: 13px !important; font-weight: 500 !important; text-transform: none !important;
    letter-spacing: 0 !important; border-radius: 100px !important; box-shadow: none !important;
    min-height: 38px !important; }}
div[data-testid="stButton"]:has(button[kind="secondary"]) button:hover {{
    background: var(--surface-h) !important; border-color: var(--border-h) !important;
    transform: none !important; }}

.stTabs [data-baseweb="tab-list"] {{ gap: 4px; background: var(--bg-2);
    padding: 5px; border-radius: 100px; border: 1px solid var(--border);
    width: fit-content; margin: 0 auto 24px auto;
    {"box-shadow: inset 0 1px 3px rgba(0,0,0,0.2);" if THEME == "dark" else ""} }}
.stTabs [data-baseweb="tab"] {{ background: transparent; color: var(--text-2);
    border-radius: 100px; padding: 9px 24px; font-weight: 500; font-size: 13px;
    letter-spacing: 0; text-transform: none; font-family: 'Inter', sans-serif !important;
    transition: all 0.25s ease; border: none !important; }}
.stTabs [data-baseweb="tab"]:hover {{ color: var(--text); }}
.stTabs [aria-selected="true"] {{
    background: {C['btn_bg'] if THEME == "dark" else "var(--surface)"} !important;
    color: {"white" if THEME == "dark" else "var(--text)"} !important;
    box-shadow: {"0 6px 24px rgba(168, 85, 247, 0.5)" if THEME == "dark" else "var(--shadow)"}; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none !important; }}

.sec-label {{ color: var(--text) !important; font-size: 14px; font-weight: 600; margin: 20px 0 10px 0; }}

.stTextArea textarea {{ background: var(--input-bg) !important; border: 1px solid var(--border) !important;
    color: var(--text) !important; font-family: 'Inter', sans-serif !important;
    font-size: 15px !important; border-radius: 20px !important; padding: 16px 20px !important;
    transition: all 0.2s !important; resize: none !important;
    box-shadow: {"inset 0 2px 8px rgba(0,0,0,0.15)" if THEME == "dark" else "var(--shadow)"}; }}
.stTextArea textarea:focus {{ border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.15), var(--shadow) !important; outline: none !important; }}
.stTextArea textarea::placeholder {{ color: var(--text-3) !important; opacity: 1 !important; }}
.stTextInput input {{ background: var(--input-bg) !important; border: 1px solid var(--border) !important;
    color: var(--text) !important; font-family: 'Inter', sans-serif !important;
    font-size: 14px !important; border-radius: 100px !important; padding: 10px 20px !important;
    height: 44px !important; }}
.stTextInput input:focus {{ border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.15) !important; outline: none !important; }}

.stSelectbox > div > div {{ background: var(--input-bg) !important;
    border: 1px solid var(--border) !important; border-radius: 14px !important;
    color: var(--text) !important; min-height: 44px !important; }}
.stSelectbox > div > div:hover {{ border-color: var(--border-h) !important; }}
.stSelectbox [data-baseweb="select"] > div {{ background: transparent !important;
    color: var(--text) !important; font-family: 'Inter', sans-serif !important; }}
.stSelectbox [data-baseweb="select"] span,
.stSelectbox [data-baseweb="select"] input {{ color: var(--text) !important; }}

[data-baseweb="popover"] > div {{ background: var(--surface) !important;
    border: 1px solid var(--border) !important; border-radius: 14px !important;
    box-shadow: var(--shadow), var(--glow) !important; overflow: hidden !important; }}
[data-baseweb="menu"] {{ background: var(--surface) !important; }}
[data-baseweb="menu"] li {{ color: var(--text) !important;
    font-family: 'Inter', sans-serif !important; font-size: 14px !important;
    padding: 12px 16px !important; background: var(--surface) !important; }}
[data-baseweb="menu"] li:hover {{ background: var(--surface-h) !important; color: var(--text) !important; }}
[data-baseweb="menu"] li[aria-selected="true"] {{
    background: {"rgba(168, 85, 247, 0.2)" if THEME == "dark" else "var(--surface-h)"} !important;
    color: var(--text) !important; }}

.stNumberInput > div > div {{ background: var(--input-bg) !important;
    border: 1px solid var(--border) !important; border-radius: 14px !important;
    min-height: 44px !important; }}
.stNumberInput input {{ background: transparent !important; color: var(--text) !important; }}
.stNumberInput button {{ background: transparent !important; color: var(--text-2) !important; border: none !important; }}
.stNumberInput button:hover {{ background: var(--surface-h) !important; color: var(--text) !important; }}

.stTextArea label, .stTextInput label, .stSelectbox label, .stNumberInput label,
.stFileUploader label {{ color: var(--text) !important; font-size: 14px !important;
    font-weight: 600 !important; font-family: 'Inter', sans-serif !important; }}

[data-testid="stFileUploader"] section {{ background: var(--input-bg) !important;
    border: 2px dashed var(--border) !important; border-radius: 20px !important;
    padding: 24px !important; transition: all 0.2s !important; }}
[data-testid="stFileUploader"] section:hover {{ border-color: var(--accent) !important;
    background: var(--surface-h) !important; }}
[data-testid="stFileUploader"] section > div {{ color: var(--text-2) !important; }}
[data-testid="stFileUploader"] section small {{ color: var(--text-3) !important; }}
[data-testid="stFileUploader"] button {{ background: var(--surface) !important;
    color: var(--text) !important; border: 1px solid var(--border) !important;
    border-radius: 100px !important; font-weight: 500 !important; font-size: 13px !important;
    padding: 8px 20px !important; }}
[data-testid="stFileUploader"] button:hover {{ background: var(--surface-h) !important;
    border-color: var(--accent) !important; }}
[data-testid="stFileUploaderFile"] {{ background: var(--surface) !important;
    border: 1px solid var(--border) !important; border-radius: 12px !important;
    padding: 8px 12px !important; }}
[data-testid="stFileUploaderFile"] small, [data-testid="stFileUploaderFile"] div {{ color: var(--text) !important; }}

div[data-testid="stButton"] > button:not([kind="secondary"]) {{
    background: {C['btn_bg']} !important; color: white !important; border: none !important;
    font-weight: 600 !important; font-size: 15px !important; letter-spacing: 0 !important;
    padding: 14px 28px !important; border-radius: 100px !important; text-transform: none !important;
    font-family: 'Inter', sans-serif !important; transition: all 0.25s !important;
    min-height: 50px !important;
    {"box-shadow: 0 6px 24px rgba(168, 85, 247, 0.4), inset 0 1px 0 rgba(255,255,255,0.15);" if THEME == "dark" else "box-shadow: 0 2px 6px rgba(16, 163, 127, 0.2);"} }}
div[data-testid="stButton"] > button:not([kind="secondary"]):hover {{
    background: {C['btn_h']} !important; transform: translateY(-2px) !important;
    {"box-shadow: 0 12px 40px rgba(168, 85, 247, 0.6);" if THEME == "dark" else "box-shadow: 0 4px 12px rgba(16, 163, 127, 0.35);"} }}
div[data-testid="stButton"] > button:disabled {{ background: var(--bg-3) !important;
    color: var(--text-3) !important; opacity: 0.5 !important; box-shadow: none !important;
    transform: none !important; }}

.stDownloadButton > button {{ background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border) !important; border-radius: 100px !important;
    font-weight: 500 !important; font-size: 13px !important; padding: 10px 20px !important; }}
.stDownloadButton > button:hover {{ background: var(--surface-h) !important;
    border-color: var(--accent) !important; color: var(--accent) !important; }}

.np-wrap {{ margin: 16px 0; padding: 22px 26px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 20px; box-shadow: var(--shadow); }}
.np-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }}
.np-label {{ display: flex; align-items: center; gap: 10px; color: var(--text);
    font-size: 14px; font-weight: 600; }}
.np-spin {{ width: 16px; height: 16px; border: 2px solid var(--border);
    border-top-color: var(--accent); border-right-color: var(--accent-3);
    border-radius: 50%; animation: spin 0.8s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.np-pct {{ font-size: 20px; font-weight: 700;
    {"background: linear-gradient(135deg, var(--accent), var(--accent-3)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;" if THEME == "dark" else "color: var(--accent);"}
    font-family: 'JetBrains Mono', monospace; letter-spacing: -0.5px; min-width: 90px; text-align: right; }}
.np-track {{ position: relative; height: 8px; background: var(--bg-3);
    border-radius: 100px; overflow: hidden; }}
.np-fill {{ position: absolute; top: 0; left: 0; bottom: 0; background: {C['prog_bg']};
    background-size: 300% 100%; border-radius: 100px;
    transition: width 0.1s cubic-bezier(0.4, 0, 0.2, 1); animation: flow 3s linear infinite;
    {"box-shadow: 0 0 20px rgba(168, 85, 247, 0.5);" if THEME == "dark" else ""} }}
@keyframes flow {{ 0% {{ background-position: 0% 50%; }} 100% {{ background-position: 300% 50%; }} }}
.np-fill::after {{ content: ''; position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.35) 50%, transparent 100%);
    animation: shim 1.6s linear infinite; }}
@keyframes shim {{ 0% {{ transform: translateX(-100%); }} 100% {{ transform: translateX(100%); }} }}
.np-meta {{ display: flex; justify-content: space-between; margin-top: 14px;
    font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-3); }}
.np-phase {{ color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
.np-wrap.done {{ border-color: var(--success);
    {"background: rgba(74, 222, 128, 0.06);" if THEME == "dark" else "background: rgba(16, 163, 127, 0.04);"} }}
.np-wrap.done .np-label {{ color: var(--success); }}
.np-wrap.done .np-pct {{ color: var(--success); -webkit-text-fill-color: var(--success); }}

.np-placeholder {{ width: 100%; aspect-ratio: 1; max-height: 500px; background: var(--bg-2);
    border: 2px dashed var(--border); border-radius: 20px; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 12px; color: var(--text-3);
    font-size: 14px; font-weight: 500; }}
.np-placeholder svg {{ opacity: 0.4; }}

.mcard {{ display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center;
    padding: 18px 22px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; margin-bottom: 10px; transition: all 0.2s; }}
.mcard:hover {{ border-color: var(--border-h); background: var(--surface-h); transform: translateX(4px); }}
.mkey {{ color: var(--text); font-weight: 700; font-size: 15px; font-family: 'JetBrains Mono', monospace; }}
.mname {{ color: var(--text-2); font-size: 13px; margin-top: 4px; }}
.minfo {{ color: var(--text-3); font-size: 11px; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }}
.tag {{ display: inline-block;
    background: {"rgba(168, 85, 247, 0.18)" if THEME == "dark" else "var(--bg-2)"};
    color: var(--accent); padding: 3px 8px; border-radius: 6px; font-size: 9px;
    font-weight: 700; margin-left: 6px; letter-spacing: 0.5px; border: 1px solid var(--border); }}
.mtime {{ background: {"rgba(168, 85, 247, 0.12)" if THEME == "dark" else "var(--bg-2)"};
    color: var(--text-2); padding: 6px 14px; border-radius: 100px; font-weight: 600;
    font-size: 12px; font-family: 'JetBrains Mono', monospace; }}

[data-testid="stMetric"] {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 16px 20px; }}
[data-testid="stMetricValue"] {{ color: var(--text) !important; font-size: 22px !important;
    font-weight: 700 !important; font-family: 'JetBrains Mono', monospace !important; }}
[data-testid="stMetricLabel"] {{ color: var(--text-3) !important; font-size: 11px !important;
    font-weight: 600 !important; text-transform: uppercase !important; letter-spacing: 0.5px !important; }}

.stImage img {{ border-radius: 16px; box-shadow: var(--shadow); }}
.stAlert, [data-baseweb="notification"] {{ background: var(--surface) !important;
    border: 1px solid var(--border) !important; border-radius: 14px !important;
    color: var(--text) !important; }}
.stAlert p, .stAlert div, [data-baseweb="notification"] p {{ color: var(--text) !important; }}
[data-testid="stCaptionContainer"] {{ color: var(--text-3) !important; font-size: 12px !important; }}
.stSuccess {{ background: {"rgba(74, 222, 128, 0.1)" if THEME == "dark" else "rgba(16, 163, 127, 0.05)"} !important;
    border-color: var(--success) !important; color: var(--success) !important; }}
.stError {{ background: {"rgba(248, 113, 113, 0.1)" if THEME == "dark" else "rgba(239, 68, 68, 0.05)"} !important;
    border-color: var(--danger) !important; }}
.stWarning {{ background: var(--bg-2) !important; border-color: var(--border) !important; color: var(--text) !important; }}
.stInfo {{ background: var(--surface) !important; border: 1px solid var(--info) !important;
    color: var(--text) !important; border-radius: 14px !important; }}
.stCheckbox label {{ color: var(--text) !important; font-size: 13px !important; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 100px; border: 2px solid var(--bg); }}
::-webkit-scrollbar-thumb:hover {{ background: var(--accent); }}
.stMarkdown, .stMarkdown p, .stMarkdown span {{ color: var(--text) !important; }}
[data-testid="stVerticalBlock"] {{ gap: 0.5rem; }}

/* ═══ API DOCS ═══ */
.api-block {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: 20px; padding: 24px 28px; margin-bottom: 20px; box-shadow: var(--shadow); }}
.api-title {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }}
.api-method {{ display: inline-block; padding: 5px 12px; border-radius: 8px;
    font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
.api-method.post {{ background: {"rgba(74, 222, 128, 0.18)" if THEME == "dark" else "rgba(16, 163, 127, 0.1)"};
    color: var(--success); border: 1px solid var(--success); }}
.api-method.get {{ background: {"rgba(96, 165, 250, 0.18)" if THEME == "dark" else "rgba(59, 130, 246, 0.1)"};
    color: var(--info); border: 1px solid var(--info); }}
.api-url {{ font-family: 'JetBrains Mono', monospace; font-size: 13px;
    color: var(--text); background: var(--bg-2); padding: 6px 12px;
    border-radius: 8px; border: 1px solid var(--border); word-break: break-all; }}
.api-desc {{ color: var(--text-2); font-size: 14px; margin: 8px 0 16px 0; line-height: 1.6; }}

div[data-testid="stCodeBlock"] pre {{
    background: var(--code-bg) !important; color: var(--code-text) !important;
    border-radius: 12px !important; padding: 18px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 13px !important; line-height: 1.65 !important;
    border: 1px solid var(--border) !important; }}
div[data-testid="stCodeBlock"] code {{
    color: var(--code-text) !important; font-family: 'JetBrains Mono', monospace !important; }}
div[data-testid="stCodeBlock"] button {{
    background: var(--surface) !important; color: var(--text-2) !important;
    border: 1px solid var(--border) !important; border-radius: 8px !important; }}
div[data-testid="stCodeBlock"] button:hover {{
    background: var(--surface-h) !important; color: var(--accent) !important;
    border-color: var(--accent) !important; }}
code:not(pre code) {{
    background: var(--bg-2) !important; color: var(--accent) !important;
    padding: 2px 6px !important; border-radius: 4px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important; border: 1px solid var(--border) !important; }}

.streamlit-expanderHeader {{
    background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border) !important; border-radius: 12px !important; }}
.streamlit-expanderHeader:hover {{ border-color: var(--accent) !important; }}
.streamlit-expanderContent {{
    background: var(--surface) !important;
    border: 1px solid var(--border) !important; border-top: none !important;
    border-radius: 0 0 12px 12px !important; padding: 16px !important; }}
</style>
""", unsafe_allow_html=True)


# ═══ NAVBAR ═══
nav_l, nav_r = st.columns([6, 1.2])
with nav_l:
    st.markdown("""
    <div class="nav">
        <div class="logo"><div class="logo-dot">N</div><span>Nitro</span><span class="badge">v2</span></div>
    </div>
    """, unsafe_allow_html=True)
with nav_r:
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    theme_label = "☾  Scuro" if THEME == "light" else "☀  Chiaro"
    if st.button(theme_label, key="theme_btn", type="secondary", use_container_width=True):
        st.session_state.theme = "dark" if THEME == "light" else "light"
        st.rerun()

# STATE
if "models" not in st.session_state:
    try: st.session_state.models = run(fetch_models())
    except Exception as e:
        st.session_state.models = []
        st.error(f"Errore caricamento modelli: {e}")
if "images" not in st.session_state: st.session_state.images = []
if "last_result" not in st.session_state: st.session_state.last_result = None

PHASE_LABELS = {
    "init": "Inizializzazione",
    "enhance": "L'AI sta perfezionando il tuo prompt",
    "account": "Preparazione sessione",
    "signup": "Configurazione servizio",
    "upload": "Caricamento immagine di riferimento",
    "submit": "Invio richiesta",
    "render": "Generazione in corso",
}

def render_progress(percent, phase, elapsed, eta, extra=""):
    percent = max(0, min(99.99, percent))
    label = PHASE_LABELS.get(phase, phase.title())
    if extra: label += f"  ·  {extra}"
    return f"""
    <div class="np-wrap">
        <div class="np-head">
            <div class="np-label"><div class="np-spin"></div><span>{label}</span></div>
            <div class="np-pct">{percent:.2f}%</div>
        </div>
        <div class="np-track"><div class="np-fill" style="width: {percent:.4f}%;"></div></div>
        <div class="np-meta">
            <span>{elapsed:.2f}s trascorsi</span>
            <span class="np-phase">{phase}</span>
            <span>~{eta:.1f}s rimanenti</span>
        </div>
    </div>
    """

def render_done(elapsed, count):
    w = "immagine" if count == 1 else "immagini"
    return f"""
    <div class="np-wrap done">
        <div class="np-head">
            <div class="np-label">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                <span>Completato</span>
            </div>
            <div class="np-pct">100.00%</div>
        </div>
        <div class="np-track"><div class="np-fill" style="width: 100%;"></div></div>
        <div class="np-meta">
            <span>{elapsed:.2f}s totali</span>
            <span class="np-phase">successo</span>
            <span>{count} {w}</span>
        </div>
    </div>
    """

def placeholder():
    return '''<div class="np-placeholder">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
        <div>La tua immagine apparirà qui</div>
    </div>'''


# ═══ TABS ═══
tab_gen, tab_bulk, tab_models, tab_api = st.tabs(["Genera", "Multiplo", "Modelli", "API"])


# ═══ GENERA ═══
with tab_gen:
    col_l, col_r = st.columns([1, 1.4], gap="large")
    with col_l:
        st.markdown('<div class="sec-label">Descrizione</div>', unsafe_allow_html=True)
        prompt = st.text_area("p", height=130, label_visibility="collapsed",
                              placeholder="Descrivi in italiano quello che vuoi creare...")

        enh_c1, enh_c2 = st.columns([1, 2])
        with enh_c1:
            use_enhance = st.checkbox("✨ Migliora con AI", value=True,
                                       help="L'AI traduce e ottimizza il prompt automaticamente")
        with enh_c2:
            if use_enhance:
                enh_choice = st.selectbox(
                    "e", list(LLM_MODELS.keys()),
                    format_func=lambda k: LLM_MODELS[k]["label"],
                    label_visibility="collapsed", index=0)
                enh_model_key = LLM_MODELS[enh_choice]["key"]
            else:
                enh_model_key = None

        st.markdown('<div class="sec-label">Modello</div>', unsafe_allow_html=True)
        models = st.session_state.models or []
        m_sel = None
        if models:
            sorted_m = sorted(models, key=lambda x: (_mtime(x), _mk(x)))
            labels = [_mn(m) or _mk(m) for m in sorted_m]
            sel = st.selectbox("m", range(len(labels)),
                               format_func=lambda i: labels[i], label_visibility="collapsed")
            m_sel = sorted_m[sel]
        else:
            st.warning("Nessun modello disponibile")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="sec-label">Formato</div>', unsafe_allow_html=True)
            dims = _mdims(m_sel) if m_sel else ["1:1"]
            if not dims: dims = ["1:1"]
            dim_sel = st.selectbox("d", dims,
                                    format_func=lambda x: DIM_LABEL.get(x, x),
                                    label_visibility="collapsed")
        with c2:
            st.markdown('<div class="sec-label">Quantità</div>', unsafe_allow_html=True)
            max_c = _mocl(m_sel) if m_sel else 4
            count = st.number_input("c", 1, max_c or 4, 1, label_visibility="collapsed")

        ref_bytes = None
        ref_filename = None
        if m_sel and m_sel.get("referenceImage"):
            st.markdown('<div class="sec-label">Immagine di riferimento (opzionale)</div>', unsafe_allow_html=True)
            uploaded = st.file_uploader("u", type=["png", "jpg", "jpeg", "webp"],
                                         accept_multiple_files=False,
                                         label_visibility="collapsed",
                                         help="Trascina qui un'immagine o clicca per selezionarla")
            if uploaded is not None:
                ref_bytes = uploaded.read()
                ref_filename = uploaded.name
                st.image(uploaded, width=140)

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        gen_btn = st.button("Genera immagine", use_container_width=True,
                            disabled=not m_sel or not prompt.strip(), key="gen_btn")

    with col_r:
        st.markdown('<div class="sec-label">Risultato</div>', unsafe_allow_html=True)
        output_slot = st.empty()
        metrics_slot = st.empty()
        prompt_slot = st.empty()
        progress_slot = st.empty()

        if st.session_state.images and not gen_btn:
            r = st.session_state.last_result
            if r:
                with metrics_slot.container():
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Tempo", f"{r.duration_s:.2f}s")
                    m2.metric("Modello", r.model[:14])
                    m3.metric("Immagini", len(st.session_state.images))
                if r.final_prompt and r.final_prompt != r.original_prompt:
                    with prompt_slot.container():
                        with st.expander("✨ Prompt migliorato dall'AI", expanded=False):
                            st.markdown(f"**Originale:** _{r.original_prompt}_")
                            st.markdown(f"**Migliorato:**")
                            st.code(r.final_prompt, language=None)
            with output_slot.container():
                cols = st.columns(min(2, len(st.session_state.images)))
                for i, img in enumerate(st.session_state.images):
                    with cols[i % len(cols)]:
                        st.image(img, use_container_width=True)
        elif not gen_btn:
            output_slot.markdown(placeholder(), unsafe_allow_html=True)

    if gen_btn:
        st.session_state.images = []
        output_slot.markdown(placeholder(), unsafe_allow_html=True)
        metrics_slot.empty()
        prompt_slot.empty()

        est_extra = (25 if ref_bytes else 0) + (8 if use_enhance else 0)
        progress_state = {
            "phase": "init", "status": "", "pid": "",
            "est_time": _mtime(m_sel) + 15 + est_extra,
        }
        result_holder = {"result": None, "error": None, "done": False}

        def gen_worker():
            try:
                res = run(do_generate(
                    prompt=prompt, model_key=_mk(m_sel),
                    dimension=dim_sel, count=int(count),
                    reference_bytes=ref_bytes, reference_filename=ref_filename,
                    enhance=use_enhance,
                    enhance_model=enh_model_key or "meta/llama-3.3-70b-instruct",
                    progress_state=progress_state))
                result_holder["result"] = res
            except Exception as e:
                result_holder["error"] = e
            finally:
                result_holder["done"] = True

        t = threading.Thread(target=gen_worker, daemon=True); t.start()
        start = time.perf_counter()
        est = progress_state["est_time"]

        while not result_holder["done"]:
            elapsed = time.perf_counter() - start
            est_current = progress_state.get("est_time", est)
            raw = elapsed / max(est_current, 1)
            progress = (1 - pow(2.718281828, -raw * 1.8)) * 99.5
            progress = min(progress, 98.5)
            phase = progress_state.get("phase", "init")
            eta = max(0, est_current - elapsed)
            progress_slot.markdown(render_progress(progress, phase, elapsed, eta, ""),
                                    unsafe_allow_html=True)
            time.sleep(0.05)
            if elapsed > 400: break

        t.join(timeout=1)
        elapsed_final = time.perf_counter() - start

        if result_holder["error"]:
            err = result_holder["error"]
            progress_slot.error(f"Errore durante la generazione: {str(err)[:250]}")
            output_slot.markdown(placeholder(), unsafe_allow_html=True)
        else:
            result = result_holder["result"]
            progress_slot.markdown(render_done(elapsed_final, len(result.urls)), unsafe_allow_html=True)

            if result.final_prompt and result.final_prompt != result.original_prompt:
                with prompt_slot.container():
                    with st.expander("✨ Prompt migliorato dall'AI", expanded=True):
                        st.markdown(f"**Originale:** _{result.original_prompt}_")
                        st.markdown(f"**Migliorato:**")
                        st.code(result.final_prompt, language=None)

            images = []
            for url in result.urls:
                data = run(download_image(url))
                if data:
                    try: images.append(Image.open(io.BytesIO(data)))
                    except: pass
            st.session_state.images = images
            st.session_state.last_result = result

            with metrics_slot.container():
                m1, m2, m3 = st.columns(3)
                m1.metric("Tempo", f"{result.duration_s:.2f}s")
                m2.metric("Modello", result.model[:14])
                m3.metric("Immagini", len(images))

            with output_slot.container():
                if images:
                    cols = st.columns(min(2, len(images)))
                    for i, img in enumerate(images):
                        with cols[i % len(cols)]:
                            st.image(img, use_container_width=True)
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            st.download_button(f"Scarica #{i+1}", buf.getvalue(),
                                file_name=f"nitro_{int(time.time())}_{i}.png",
                                mime="image/png", key=f"dl_{i}_{time.time()}",
                                use_container_width=True)
                else:
                    st.warning("Nessuna immagine ricevuta")


# ═══ MULTIPLO ═══
with tab_bulk:
    st.markdown('<div class="sec-label">Descrizioni (una per riga)</div>', unsafe_allow_html=True)
    bulk_prompts = st.text_area("b", height=200,
        placeholder="un drago rosso\nuna fenice blu\ngoku che combatte entrambi...",
        label_visibility="collapsed")

    b_enh_c1, b_enh_c2 = st.columns([1, 2])
    with b_enh_c1:
        bulk_use_enhance = st.checkbox("✨ Migliora ogni prompt con AI", value=True, key="bulk_enh")
    with b_enh_c2:
        if bulk_use_enhance:
            b_enh = st.selectbox("be", list(LLM_MODELS.keys()),
                                  format_func=lambda k: LLM_MODELS[k]["label"],
                                  key="be", label_visibility="collapsed", index=1)
            bulk_enh_model = LLM_MODELS[b_enh]["key"]
        else:
            bulk_enh_model = None

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        st.markdown('<div class="sec-label">Modello</div>', unsafe_allow_html=True)
        models = st.session_state.models or []
        bulk_m = None
        if models:
            sorted_m = sorted(models, key=lambda x: _mtime(x))
            blabels = [_mn(m) or _mk(m) for m in sorted_m]
            bidx = st.selectbox("bm", range(len(blabels)),
                                format_func=lambda i: blabels[i], key="bm",
                                label_visibility="collapsed")
            bulk_m = sorted_m[bidx]
    with bc2:
        st.markdown('<div class="sec-label">Formato</div>', unsafe_allow_html=True)
        bd_dims = _mdims(bulk_m) if bulk_m else ["1:1"]
        if not bd_dims: bd_dims = ["1:1"]
        bulk_dim = st.selectbox("bd", bd_dims,
                                 format_func=lambda x: DIM_LABEL.get(x, x),
                                 key="bd", label_visibility="collapsed")
    with bc3:
        st.markdown('<div class="sec-label">Contemporanee</div>', unsafe_allow_html=True)
        bulk_conc = st.number_input("bc", 1, 5, 2, key="bc", label_visibility="collapsed",
                                     help="Numero di generazioni parallele (max consigliato: 3)")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    bulk_go = st.button("Genera tutte", use_container_width=True, disabled=not bulk_m, key="bulk_go")

    if bulk_go:
        prompts = [p.strip() for p in bulk_prompts.split("\n") if p.strip()]
        if not prompts:
            st.error("Inserisci almeno una descrizione")
        else:
            progress_slot_bulk = st.empty()
            results_area = st.container()
            state = {"done": 0, "total": len(prompts), "results": [None] * len(prompts)}

            async def bulk_run():
                sem = asyncio.Semaphore(int(bulk_conc))
                async def one(i, p):
                    async with sem:
                        try:
                            r = await do_generate(
                                prompt=p, model_key=_mk(bulk_m), dimension=bulk_dim,
                                enhance=bulk_use_enhance,
                                enhance_model=bulk_enh_model or "meta/llama-3.1-8b-instruct",
                                max_retries=3)
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

            t = threading.Thread(target=worker, daemon=True); t.start()
            start = time.perf_counter()
            per_prompt = _mtime(bulk_m) + 5 + (5 if bulk_use_enhance else 0)
            est_total = (len(prompts) / int(bulk_conc)) * per_prompt

            while not holder["done"]:
                elapsed = time.perf_counter() - start
                done = state["done"]
                real_prog = (done / len(prompts)) * 100
                time_prog = (1 - pow(2.718281828, -elapsed / max(est_total, 1) * 1.8)) * 99
                progress = max(real_prog, min(time_prog, 98)) if done < len(prompts) else 99
                eta = max(0, est_total - elapsed)
                progress_slot_bulk.markdown(
                    render_progress(progress, "render", elapsed, eta, f"{done}/{len(prompts)}"),
                    unsafe_allow_html=True)
                time.sleep(0.1)

            t.join(timeout=1)
            elapsed_final = time.perf_counter() - start
            ok = sum(1 for r in state["results"] if isinstance(r, Result))
            progress_slot_bulk.markdown(render_done(elapsed_final, ok), unsafe_allow_html=True)

            with results_area:
                for i, r in enumerate(state["results"]):
                    if isinstance(r, Result) and r.urls:
                        st.markdown(f"**{i+1}.** {prompts[i][:70]}  ·  *{r.duration_s:.2f}s*")
                        if r.final_prompt and r.final_prompt != r.original_prompt:
                            with st.expander("✨ Prompt AI", expanded=False):
                                st.code(r.final_prompt, language=None)
                        cols = st.columns(min(len(r.urls), 4))
                        for j, url in enumerate(r.urls):
                            with cols[j % len(cols)]:
                                st.image(url, use_container_width=True)
                    else:
                        err = str(r) if isinstance(r, Exception) else "nessun output"
                        st.error(f"{i+1}. {prompts[i][:60]} — {err[:100]}")


# ═══ MODELLI ═══
with tab_models:
    top_c1, top_c2, top_c3 = st.columns([2, 1, 1])
    with top_c1:
        st.markdown('<div class="sec-label">Elenco modelli disponibili</div>', unsafe_allow_html=True)
    with top_c2:
        filter_ref = st.checkbox("Solo con riferimento")
    with top_c3:
        if st.button("Aggiorna", use_container_width=True, key="refresh_btn"):
            try:
                st.session_state.models = run(fetch_models(force=True))
                st.success(f"Caricati {len(st.session_state.models)} modelli")
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")

    models = st.session_state.models or []
    if filter_ref:
        models = [m for m in models if m.get("referenceImage")]

    st.caption(f"{len(models)} modelli disponibili · ordinati per velocità")

    for m in sorted(models, key=lambda x: _mtime(x)):
        k, n = _mk(m), _mn(m)
        dims = " · ".join([DIM_LABEL.get(d, d) for d in _mdims(m)[:4]])
        tags = ""
        if m.get("referenceImage"): tags += '<span class="tag">RIF</span>'
        if m.get("cfg"): tags += '<span class="tag">CFG</span>'
        max_out = _mocl(m)
        if max_out and max_out > 1: tags += f'<span class="tag">×{max_out}</span>'
        et = _mtime(m)
        st.markdown(f"""
        <div class="mcard">
            <div>
                <div><span class="mkey">{n or k}</span>{tags}</div>
                <div class="minfo">{dims}</div>
            </div>
            <div class="mtime">~{et:.0f}s</div>
        </div>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
#                       API DOCS - REAL EXAMPLES
# ═══════════════════════════════════════════════════════════════════
with tab_api:
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span style="font-size: 24px; font-weight: 700;">Documentazione API</span>
            <span class="badge">v1</span>
        </div>
        <div class="api-desc">
            Le API mostrate qui sono <strong>funzionanti e testate</strong>. Usa direttamente i worker
            (<code>808files</code>, <code>Nvidia LLM</code>, <code>mail808</code>) e le API di davinci per replicare
            il funzionamento di Nitro nel tuo codice. Ogni esempio è pronto da copiare e incollare.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ═══ 1. 808FILES UPLOAD ═══
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span class="api-method post">POST</span>
            <span class="api-url">https://808files.elmarciun.workers.dev/api/token</span>
        </div>
        <div class="api-title">
            <span class="api-method post">POST</span>
            <span class="api-url">https://upload.gofile.io/uploadfile</span>
        </div>
        <div class="api-title">
            <span class="api-method post">POST</span>
            <span class="api-url">https://808files.elmarciun.workers.dev/api/register</span>
        </div>
        <div class="api-desc">
            <strong>Upload file anonimo permanente (3-step).</strong>
            Ritorna un URL diretto usabile ovunque, senza autenticazione.
        </div>
    </div>
    """, unsafe_allow_html=True)

    up_py, up_curl, up_js, up_ps = st.tabs(["Python", "cURL", "JavaScript", "PowerShell"])
    with up_py:
        st.code('''import requests

API = "https://808files.elmarciun.workers.dev"

# Step 1: ottieni token
token = requests.post(f"{API}/api/token").json()["token"]

# Step 2: upload su gofile
with open("mia_foto.jpg", "rb") as f:
    r = requests.post(
        "https://upload.gofile.io/uploadfile",
        data={"token": token},
        files={"file": f},
    )
d = r.json()["data"]

# Step 3: registra e ottieni URL permanente
r = requests.post(f"{API}/api/register", json={
    "token": token,
    "id": d["id"],
    "server": d.get("servers", ["store1"])[0],
    "filename": d["name"],
    "folder_id": d["parentFolder"],
    "folder_code": d.get("parentFolderCode"),
    "download_page": d["downloadPage"],
    "size": d["size"],
    "mimetype": d.get("mimetype", "application/octet-stream"),
})
result = r.json()
print("URL diretto:", result["stream"])
print("Link condivisione:", result["link"])
''', language="python")

    with up_curl:
        st.code('''# Step 1: token
TOKEN=$(curl -s -X POST https://808files.elmarciun.workers.dev/api/token | jq -r .token)

# Step 2: upload
UPLOAD=$(curl -s -X POST https://upload.gofile.io/uploadfile \\
    -F "token=$TOKEN" -F "file=@mia_foto.jpg")

FILE_ID=$(echo $UPLOAD | jq -r .data.id)
FILE_NAME=$(echo $UPLOAD | jq -r .data.name)
FOLDER=$(echo $UPLOAD | jq -r .data.parentFolder)
SERVER=$(echo $UPLOAD | jq -r '.data.servers[0]')
SIZE=$(echo $UPLOAD | jq -r .data.size)
PAGE=$(echo $UPLOAD | jq -r .data.downloadPage)

# Step 3: register
curl -X POST https://808files.elmarciun.workers.dev/api/register \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"token\\": \\"$TOKEN\\",
    \\"id\\": \\"$FILE_ID\\",
    \\"server\\": \\"$SERVER\\",
    \\"filename\\": \\"$FILE_NAME\\",
    \\"folder_id\\": \\"$FOLDER\\",
    \\"download_page\\": \\"$PAGE\\",
    \\"size\\": $SIZE,
    \\"mimetype\\": \\"image/jpeg\\"
  }"
''', language="bash")

    with up_js:
        st.code('''const API = "https://808files.elmarciun.workers.dev";

async function upload808(file) {
  // Step 1: token
  const { token } = await fetch(`${API}/api/token`, {
    method: "POST"
  }).then(r => r.json());

  // Step 2: upload su gofile
  const fd = new FormData();
  fd.append("token", token);
  fd.append("file", file);
  const uploadRes = await fetch("https://upload.gofile.io/uploadfile", {
    method: "POST",
    body: fd,
  }).then(r => r.json());
  const d = uploadRes.data;

  // Step 3: register
  const reg = await fetch(`${API}/api/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token,
      id: d.id,
      server: (d.servers || ["store1"])[0],
      filename: d.name,
      folder_id: d.parentFolder,
      folder_code: d.parentFolderCode,
      download_page: d.downloadPage,
      size: d.size,
      mimetype: d.mimetype || "application/octet-stream",
    }),
  }).then(r => r.json());

  return reg.stream; // URL diretto permanente
}

// Uso:
const fileInput = document.querySelector('input[type=file]');
const url = await upload808(fileInput.files[0]);
console.log("URL:", url);
''', language="javascript")

    with up_ps:
        st.code('''$API = "https://808files.elmarciun.workers.dev"

# Step 1: token
$token = (Invoke-RestMethod -Uri "$API/api/token" -Method Post).token

# Step 2: upload
$form = @{
    token = $token
    file  = Get-Item -Path "mia_foto.jpg"
}
$upload = Invoke-RestMethod -Uri "https://upload.gofile.io/uploadfile" `
    -Method Post -Form $form
$d = $upload.data

# Step 3: register
$body = @{
    token = $token
    id = $d.id
    server = $d.servers[0]
    filename = $d.name
    folder_id = $d.parentFolder
    folder_code = $d.parentFolderCode
    download_page = $d.downloadPage
    size = $d.size
    mimetype = $d.mimetype
} | ConvertTo-Json

$result = Invoke-RestMethod -Uri "$API/api/register" `
    -Method Post -Body $body -ContentType "application/json"

Write-Host "URL:" $result.stream
''', language="powershell")


    # ═══ 2. NVIDIA LLM - ENHANCE PROMPT ═══
    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span class="api-method post">POST</span>
            <span class="api-url">https://elmarcito-nvidia.hf.space/v1/chat</span>
        </div>
        <div class="api-title">
            <span class="api-method get">GET</span>
            <span class="api-url">https://elmarcito-nvidia.hf.space/v1/chat/get</span>
        </div>
        <div class="api-desc">
            <strong>Chat con modelli LLM Nvidia NIM.</strong>
            Usa questa API per far ragionare un LLM sul tuo prompt italiano e trasformarlo in un prompt inglese
            ottimizzato per generatori di immagini. Modelli disponibili:
            <code>meta/llama-3.3-70b-instruct</code>, <code>meta/llama-3.1-8b-instruct</code>,
            <code>nvidia/nemotron-3-nano-omni</code>, <code>qwen/qwen3-next-80b</code>, e molti altri.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("**Body per POST:**")
    st.code('''{
  "message": "goku che combatte drago rosso e fenice",
  "model": "meta/llama-3.3-70b-instruct",
  "system": "Sei un esperto di prompt per generatori di immagini AI. Traduci in inglese e arricchisci con dettagli visivi cinematografici. Rispondi solo con il prompt migliorato."
}''', language="json")

    en_py, en_curl, en_js, en_ps = st.tabs(["Python", "cURL", "JavaScript", "PowerShell"])
    with en_py:
        st.code('''import requests

def enhance_prompt(italian_prompt):
    system = """Sei un esperto di prompt per generatori di immagini AI.
Traduci sempre in inglese, aggiungi dettagli visivi (illuminazione, stile, atmosfera).
Se ci sono più soggetti, includili tutti. Rispondi SOLO con il prompt migliorato."""
    
    r = requests.post(
        "https://elmarcito-nvidia.hf.space/v1/chat",
        json={
            "message": italian_prompt,
            "model": "meta/llama-3.3-70b-instruct",
            "system": system,
        },
        timeout=60,
    )
    data = r.json()
    # La risposta può essere in vari campi
    for k in ("response", "message", "content", "text"):
        if k in data and data[k]:
            return data[k].strip().strip('"')
    return None

result = enhance_prompt("goku che combatte drago rosso e fenice")
print(result)
# Output: "Epic anime battle scene, Goku in Ultra Instinct form..."
''', language="python")

    with en_curl:
        st.code('''# POST (raccomandato)
curl -X POST https://elmarcito-nvidia.hf.space/v1/chat \\
  -H "Content-Type: application/json" \\
  -d '{
    "message": "goku che combatte drago rosso e fenice",
    "model": "meta/llama-3.3-70b-instruct",
    "system": "Sei un esperto di prompt AI. Traduci in inglese con dettagli visivi cinematografici. Rispondi solo con il prompt."
  }'

# GET (quick test)
curl "https://elmarcito-nvidia.hf.space/v1/chat/get?message=Ciao&model=meta/llama-3.1-8b-instruct"

# SSE Streaming
curl -N "https://elmarcito-nvidia.hf.space/v1/chat/stream?message=Ciao&model=meta/llama-3.1-8b-instruct"
''', language="bash")

    with en_js:
        st.code('''async function enhancePrompt(italianPrompt) {
  const system = `Sei un esperto di prompt per generatori di immagini AI.
Traduci sempre in inglese, aggiungi dettagli visivi.
Se ci sono più soggetti, includili tutti. Rispondi SOLO con il prompt migliorato.`;

  const r = await fetch("https://elmarcito-nvidia.hf.space/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: italianPrompt,
      model: "meta/llama-3.3-70b-instruct",
      system,
    }),
  });
  const data = await r.json();
  for (const k of ["response", "message", "content", "text"]) {
    if (data[k]) return data[k].trim().replace(/^["']|["']$/g, "");
  }
  return null;
}

const enhanced = await enhancePrompt("goku che combatte drago rosso");
console.log(enhanced);
''', language="javascript")

    with en_ps:
        st.code('''$system = "Sei un esperto di prompt AI. Traduci in inglese con dettagli visivi. Rispondi solo con il prompt."

$body = @{
    message = "goku che combatte drago rosso e fenice"
    model   = "meta/llama-3.3-70b-instruct"
    system  = $system
} | ConvertTo-Json

$r = Invoke-RestMethod -Uri "https://elmarcito-nvidia.hf.space/v1/chat" `
    -Method Post -Body $body -ContentType "application/json"

Write-Host $r.response
''', language="powershell")


    # ═══ 3. MAIL808 - EMAIL TEMPORANEE ═══
    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span class="api-method get">GET</span>
            <span class="api-url">https://mail808.elmarciun.workers.dev/genera</span>
        </div>
        <div class="api-title">
            <span class="api-method get">GET</span>
            <span class="api-url">https://mail808.elmarciun.workers.dev/attendi/{email}</span>
        </div>
        <div class="api-desc">
            <strong>Email temporanee usa-e-getta con attesa OTP.</strong>
            Genera indirizzi Gmail dot-trick e cattura codici a 6 cifre automaticamente.
        </div>
    </div>
    """, unsafe_allow_html=True)

    mail_py, mail_curl, mail_js = st.tabs(["Python", "cURL", "JavaScript"])
    with mail_py:
        st.code('''import requests, re, time

MAIL = "https://mail808.elmarciun.workers.dev"

# Genera email temporanea Gmail
email = requests.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1").text.strip()
print("Email:", email)

# Attendi OTP a 6 cifre (max 90s)
deadline = time.time() + 90
while time.time() < deadline:
    r = requests.get(f"{MAIL}/attendi/{email}", params={
        "mittente": "davinci",  # filtra per mittente (opzionale)
        "codice": 1,             # estrai solo il codice
        "semplice": 1,
        "timeout": 15000,
    }, timeout=20)
    if r.status_code == 200 and r.text.strip():
        match = re.search(r"\\b(\\d{6})\\b", r.text)
        if match:
            print("OTP:", match.group(1))
            break
    time.sleep(1)
''', language="python")

    with mail_curl:
        st.code('''# Genera email
curl "https://mail808.elmarciun.workers.dev/genera?tipi=dotGmail&semplice=1"

# Attendi OTP (blocking, max 15s per chiamata)
curl "https://mail808.elmarciun.workers.dev/attendi/your.email@gmail.com?mittente=davinci&codice=1&semplice=1&timeout=15000"

# Leggi inbox
curl "https://mail808.elmarciun.workers.dev/inbox/your.email@gmail.com"
''', language="bash")

    with mail_js:
        st.code('''const MAIL = "https://mail808.elmarciun.workers.dev";

// Genera email
const email = (await fetch(`${MAIL}/genera?tipi=dotGmail&semplice=1`)
  .then(r => r.text())).trim();
console.log("Email:", email);

// Attendi OTP
const params = new URLSearchParams({
  mittente: "davinci", codice: "1", semplice: "1", timeout: "60000"
});
const otp = await fetch(`${MAIL}/attendi/${email}?${params}`)
  .then(r => r.text());
console.log("OTP:", otp.match(/\\b(\\d{6})\\b/)?.[1]);
''', language="javascript")


    # ═══ 4. DAVINCI GENERATE (funziona con auth token JWT) ═══
    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span class="api-method get">GET</span>
            <span class="api-url">https://wl-cms-web-prod.davinci.ai/image-models</span>
        </div>
        <div class="api-title">
            <span class="api-method post">POST</span>
            <span class="api-url">https://wl-api-web-prod.davinci.ai/process/txt-image</span>
        </div>
        <div class="api-desc">
            <strong>API dirette davinci.ai per generare immagini.</strong>
            Richiedono un token JWT Firebase (ottenibile via signup/login).
            Ecco il flusso completo che replica quello di Nitro.
        </div>
    </div>
    """, unsafe_allow_html=True)

    dv_py = st.tabs(["Python — flusso completo"])[0]
    with dv_py:
        st.code('''"""
Flusso completo per generare un'immagine su davinci.ai.
Include signup automatico + upload riferimento + generazione.
"""
import requests, time, base64, json, random, string, re

FB_KEY = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs"
FB_GMPID = "1:378221804375:web:32bf22971597e5ef92dc12"
API = "https://wl-api-web-prod.davinci.ai"
CMS = "https://wl-cms-web-prod.davinci.ai"
FS  = "https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents"
MAIL = "https://mail808.elmarciun.workers.dev"

HEADERS = {
    "origin": "https://davinci.ai",
    "referer": "https://davinci.ai/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0",
}
H_FB = {**HEADERS, "content-type": "application/json",
        "x-firebase-gmpid": FB_GMPID,
        "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web"}


def signup():
    """Crea un account davinci con verifica email OTP."""
    email = requests.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1").text.strip()
    pw = "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "!"

    # 1. Firebase signup
    d = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}",
        headers=H_FB,
        json={"returnSecureToken": True, "email": email,
              "password": pw, "clientType": "CLIENT_TYPE_WEB"},
    ).json()
    id_token = d["idToken"]
    refresh_token = d["refreshToken"]

    # 2. Send OTP
    requests.post(f"{API}/email-verification-send",
                  headers={"content-type": "application/json"},
                  json={"email": email})

    # 3. Wait OTP
    otp = None
    for _ in range(30):
        time.sleep(3)
        r = requests.get(f"{MAIL}/attendi/{email}",
            params={"mittente": "davinci", "codice": 1, "semplice": 1, "timeout": 10000})
        if r.status_code == 200:
            m = re.search(r"\\b(\\d{6})\\b", r.text)
            if m:
                otp = m.group(1)
                break
    if not otp: raise RuntimeError("OTP timeout")

    # 4. Verify OTP
    requests.post(f"{API}/email-verification-verify-code",
                  headers={"content-type": "application/json"},
                  json={"email": email, "code": otp})

    # 5. Re-login per token aggiornato
    d2 = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}",
        headers=H_FB,
        json={"returnSecureToken": True, "email": email,
              "password": pw, "clientType": "CLIENT_TYPE_WEB"},
    ).json()
    return d2["idToken"], d2["refreshToken"]


def get_uid(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["user_id"]


def list_models():
    return requests.get(f"{CMS}/image-models", headers=HEADERS).json()["data"]


def generate(prompt, model="FLUX_2_TURBO", dimension="1:1", token=None,
             reference_url=None):
    """Genera immagine e ritorna URLs."""
    if not token:
        token, _ = signup()

    uid = get_uid(token)
    ah = {**HEADERS, "content-type": "application/json",
          "x-platform": "web", "x-token": token}

    payload = {
        "prompt": prompt, "model": model,
        "dimension": dimension, "artStyleId": 0, "imageCount": 1,
    }
    if reference_url:
        payload["referenceImages"] = [reference_url]
        payload["referenceImage"] = reference_url

    # Submit
    r = requests.post(f"{API}/process/txt-image", json=payload, headers=ah)
    data = r.json()
    pid = data.get("processId") or (data.get("data") or [{}])[0].get("processId")
    if not pid: raise RuntimeError(f"No PID: {data}")

    # Poll Firestore
    url = f"{FS}/users/{uid}/processes/{pid}"
    for _ in range(150):
        time.sleep(2)
        r = requests.get(url, headers={"authorization": f"Bearer {token}"})
        if r.status_code != 200: continue
        fields = r.json().get("fields", {})
        status = (fields.get("status", {}).get("stringValue") or "").upper()
        if status in ("COMPLETED", "SUCCESS", "DONE"):
            # Estrai URL immagini
            urls = []
            for key in ("outputs", "images", "results"):
                arr = fields.get(key, {}).get("arrayValue", {}).get("values", [])
                for item in arr:
                    v = item.get("stringValue", "")
                    if v.startswith("http"): urls.append(v)
            return urls
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"Failed: {status}")
    raise TimeoutError("Polling timeout")


# ══ ESEMPIO USO ══
if __name__ == "__main__":
    # Signup nuovo account (o riusa token esistente)
    token, refresh = signup()
    print("Token ottenuto")

    # Genera
    urls = generate(
        prompt="Epic anime scene of Goku fighting a red dragon",
        model="FLUX_2_TURBO",
        dimension="16:9",
        token=token,
    )
    for u in urls:
        print("Immagine:", u)
''', language="python")


    # ═══ 5. INTEGRAZIONE COMPLETA ═══
    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div class="api-block">
        <div class="api-title">
            <span style="font-size: 18px; font-weight: 700;">Pipeline completa · Tutto insieme</span>
        </div>
        <div class="api-desc">
            Esempio end-to-end che combina <strong>upload riferimento + enhance AI + generazione</strong>.
            Copia questo script per replicare il 100% delle funzionalità di Nitro nel tuo codice.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.code('''"""
NITRO PIPELINE COMPLETA
Requisiti: pip install requests
"""
import requests, re, time, base64, json, random, string

# ══ CONFIG ══
FB_KEY = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs"
FILES = "https://808files.elmarciun.workers.dev"
LLM   = "https://elmarcito-nvidia.hf.space/v1/chat"
MAIL  = "https://mail808.elmarciun.workers.dev"
API   = "https://wl-api-web-prod.davinci.ai"
FS    = "https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents"

HEADERS = {
    "origin": "https://davinci.ai", "referer": "https://davinci.ai/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0",
}

# ══ 1. UPLOAD REFERENCE IMAGE ══
def upload(file_path):
    token = requests.post(f"{FILES}/api/token").json()["token"]
    with open(file_path, "rb") as f:
        u = requests.post("https://upload.gofile.io/uploadfile",
            data={"token": token}, files={"file": f}).json()["data"]
    r = requests.post(f"{FILES}/api/register", json={
        "token": token, "id": u["id"],
        "server": u.get("servers", ["store1"])[0],
        "filename": u["name"], "folder_id": u["parentFolder"],
        "folder_code": u.get("parentFolderCode"),
        "download_page": u["downloadPage"],
        "size": u["size"], "mimetype": u.get("mimetype", "image/jpeg")
    }).json()
    return r["stream"]

# ══ 2. ENHANCE PROMPT CON AI ══
def enhance(prompt_it, has_reference=False):
    system = """Sei un esperto di prompt per AI generative di immagini.
Traduci in inglese, aggiungi dettagli cinematografici, mantieni TUTTI i soggetti.
Rispondi SOLO con il prompt inglese finale."""
    if has_reference:
        system += "\\nUsa 'this person' o 'this face' per riferirti all'immagine allegata."
    r = requests.post(LLM, json={
        "message": prompt_it,
        "model": "meta/llama-3.3-70b-instruct",
        "system": system,
    }, timeout=60).json()
    for k in ("response", "message", "content", "text"):
        if r.get(k): return r[k].strip().strip('"')
    return prompt_it

# ══ 3. SIGNUP DAVINCI (25 crediti gratis) ══
def signup():
    email = requests.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1").text.strip()
    pw = "".join(random.choices(string.ascii_letters+string.digits, k=14)) + "!"
    h_fb = {**HEADERS, "content-type": "application/json",
            "x-firebase-gmpid": "1:378221804375:web:32bf22971597e5ef92dc12",
            "x-client-version": "Chrome/JsCore/11.10.0/FirebaseCore-web"}
    requests.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}",
        headers=h_fb, json={"returnSecureToken": True, "email": email,
        "password": pw, "clientType": "CLIENT_TYPE_WEB"}).json()
    requests.post(f"{API}/email-verification-send",
        headers={"content-type":"application/json"}, json={"email": email})
    otp = None
    for _ in range(30):
        time.sleep(3)
        r = requests.get(f"{MAIL}/attendi/{email}",
            params={"mittente":"davinci","codice":1,"semplice":1,"timeout":10000})
        m = re.search(r"\\b(\\d{6})\\b", r.text)
        if m: otp = m.group(1); break
    requests.post(f"{API}/email-verification-verify-code",
        headers={"content-type":"application/json"}, json={"email": email, "code": otp})
    d = requests.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}",
        headers=h_fb, json={"returnSecureToken": True, "email": email,
        "password": pw, "clientType": "CLIENT_TYPE_WEB"}).json()
    return d["idToken"]

# ══ 4. GENERA IMMAGINE ══
def generate(prompt, model="NANO_BANANA_PRO", dim="16:9",
             token=None, reference_url=None):
    if not token: token = signup()
    uid = json.loads(base64.urlsafe_b64decode(
        token.split(".")[1] + "=="))["user_id"]
    ah = {**HEADERS, "content-type": "application/json",
          "x-platform": "web", "x-token": token}
    payload = {"prompt": prompt, "model": model, "dimension": dim,
               "artStyleId": 0, "imageCount": 1}
    if reference_url:
        payload["referenceImages"] = [reference_url]
        payload["referenceImage"] = reference_url
    r = requests.post(f"{API}/process/txt-image", json=payload, headers=ah).json()
    pid = r.get("processId") or (r.get("data") or [{}])[0].get("processId")
    for _ in range(150):
        time.sleep(2)
        rr = requests.get(f"{FS}/users/{uid}/processes/{pid}",
            headers={"authorization": f"Bearer {token}"})
        if rr.status_code != 200: continue
        f = rr.json().get("fields", {})
        s = (f.get("status", {}).get("stringValue") or "").upper()
        if s in ("COMPLETED","SUCCESS","DONE"):
            urls = []
            for k in ("outputs","images","results"):
                for item in f.get(k, {}).get("arrayValue", {}).get("values", []):
                    v = item.get("stringValue", "")
                    if v.startswith("http"): urls.append(v)
            return urls
        if s in ("FAILED","ERROR"): raise RuntimeError(f"Failed: {s}")
    raise TimeoutError()

# ══════ USO ══════
if __name__ == "__main__":
    # 1. Upload foto di riferimento
    ref_url = upload("mia_foto.jpg")
    print("Riferimento caricato:", ref_url)

    # 2. Migliora il prompt con AI
    enhanced = enhance("metti il mio viso su uno yacht a mykonos", has_reference=True)
    print("Prompt migliorato:", enhanced)

    # 3. Genera immagine
    token = signup()
    urls = generate(enhanced, model="NANO_BANANA_PRO", dim="16:9",
                    token=token, reference_url=ref_url)
    for u in urls:
        print("Immagine generata:", u)
''', language="python")

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="text-align: center; padding: 20px; color: var(--text-3); font-size: 12px;">
        Nitro Pipeline · powered by <code>808files</code> · <code>mail808</code> · <code>nvidia-nim</code> · docs by @elmarciun
    </div>
    """, unsafe_allow_html=True)
