"""davinci.ai image gen NITRO — all-in-one + tutti i 25 modelli"""
from __future__ import annotations
import asyncio, base64, json, os, random, re, string, sys, time, threading
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from curl_cffi.requests import AsyncSession

try: import winloop; asyncio.set_event_loop_policy(winloop.EventLoopPolicy()); _LOOP="winloop"
except ImportError:
    try: import uvloop; asyncio.set_event_loop_policy(uvloop.EventLoopPolicy()); _LOOP="uvloop"
    except ImportError: _LOOP="asyncio"
try: import orjson; _loads=orjson.loads; _dumpsb=orjson.dumps
except ImportError:
    import json as _json; _loads=_json.loads; _dumpsb=lambda o:_json.dumps(o,indent=2,ensure_ascii=False).encode()

# ═══════════ CONFIG ═══════════
FB_KEY,FB_GMPID = "AIzaSyACc5e0U4DUwjdve3X4Odyjb8CNcL37Qgs", "1:378221804375:web:32bf22971597e5ef92dc12"
FB_SU  = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FB_KEY}"
FB_LK  = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FB_KEY}"
FB_SI  = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FB_KEY}"
FB_TOK = f"https://securetoken.googleapis.com/v1/token?key={FB_KEY}"
DV_API,DV_CMS = "https://wl-api-web-prod.davinci.ai", "https://wl-cms-web-prod.davinci.ai"
DV_PAY = "https://payment.davinci.ai/api/v1/auth"
FS_BASE = "https://firestore.googleapis.com/v1/projects/davinciweb-b8892/databases/(default)/documents"
MAIL   = "https://mail808.elmarciun.workers.dev"

SD = Path(__file__).parent.resolve()
ACCS_FILE = next((p for p in [SD.parent/"davinci_accounts.json", SD/"davinci_accounts.json",
                              Path.cwd()/"davinci_accounts.json"] if p.exists()),
                 SD.parent/"davinci_accounts.json")
MODELS_CACHE = SD/"image-models.json"
OUT_DIR = SD/"generated_images"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
H_BASE = {"accept":"*/*","accept-language":"it,it-IT;q=0.9,en;q=0.8","accept-encoding":"gzip, deflate",
          "origin":"https://davinci.ai","referer":"https://davinci.ai/","user-agent":UA}
H_JSON = {"content-type":"application/json"}
H_FB   = {**H_JSON,"x-client-version":"Chrome/JsCore/11.10.0/FirebaseCore-web","x-firebase-gmpid":FB_GMPID}

DIM_ALIAS = {"1:1":["1:1","square","square_hd"],"16:9":["16:9","landscape_16_9","landscape"],
             "9:16":["9:16","portrait_16_9","portrait"],"4:3":["4:3","landscape_4_3"],
             "3:4":["3:4","portrait_4_3"],"21:9":["21:9"],"4:5":["4:5"],"5:4":["5:4"],
             "2:3":["2:3"],"3:2":["3:2"],"auto":["auto"]}
_OTP_RE = re.compile(r"\b(\d{6})\b")
_PWC    = string.ascii_letters + string.digits + "!@#$%"
file_lock = threading.Lock()

# ═══════════ UI ═══════════
if sys.platform == "win32": os.system("")
RESET = "\033[0m"
def rgb(r,g,b): return f"\033[38;2;{int(r)};{int(g)};{int(b)}m"
def lerp(a,b,t): return a+(b-a)*t

def grad(text, c1, c2):
    if not text: return ""
    out = ""; n = len(text)
    for i,ch in enumerate(text):
        t = i/max(1,n-1)
        out += rgb(lerp(c1[0],c2[0],t), lerp(c1[1],c2[1],t), lerp(c1[2],c2[2],t)) + ch
    return out+RESET

def grad_bar(ratio, w=44, c1=(255,100,100), c2=(100,255,150)):
    exact = ratio*w; full = int(exact); frac = exact-full
    subs = [" ","▏","▎","▍","▌","▋","▊","▉","█"]; si = int(frac*8); bar = ""
    for i in range(full):
        t = i/max(1,w-1)
        bar += rgb(lerp(c1[0],c2[0],t), lerp(c1[1],c2[1],t), lerp(c1[2],c2[2],t)) + "█"
    if full < w:
        t = full/max(1,w-1)
        bar += rgb(lerp(c1[0],c2[0],t), lerp(c1[1],c2[1],t), lerp(c1[2],c2[2],t)) + subs[si]
        bar += rgb(60,60,60) + "░"*(w-full-1)
    return bar+RESET

SPIN = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

class UI:
    def __init__(self): self.lock=threading.Lock(); self.last=0; self.si=0
    def clear(self):
        if self.last>0: sys.stdout.write(f"\033[{self.last}A\033[J"); sys.stdout.flush()
    def render(self,lines):
        with self.lock: self.clear(); print("\n".join(lines)); self.last=len(lines)
    def perm(self,text):
        with self.lock: self.clear(); print(text); self.last=0
    def spinner(self): s=SPIN[self.si%len(SPIN)]; self.si+=1; return s
ui = UI()

def banner():
    t = "  🎨  DAVINCI.ai IMAGE GEN  🎨  "
    print(grad("╔"+"═"*len(t)+"╗", (255,100,255), (0,255,255)))
    print(grad("║"+t+"║", (255,100,255), (0,255,255)))
    print(grad("╚"+"═"*len(t)+"╝", (255,100,255), (0,255,255)))

def fmt_time(s):
    s=int(s); m,s=divmod(s,60); h,m=divmod(m,60)
    if h: return f"{h}h{m:02d}m{s:02d}s"
    if m: return f"{m}m{s:02d}s"
    return f"{s}s"

# ═══════════ HTTP ═══════════
async def _post(s,url,body,headers,ok=(200,201),raw_body=False):
    r = await s.post(url, data=body if raw_body else None, json=None if raw_body else body, headers=headers)
    if r.status_code not in ok: raise RuntimeError(f"POST {url}→{r.status_code}: {r.text[:250]}")
    try: return r.json() if r.text else {}
    except: return {"_raw":r.text}

async def _get(s,url,headers,params=None):
    r = await s.get(url,headers=headers,params=params)
    try: return r.status_code, (r.json() if r.text else {})
    except: return r.status_code, {"_raw":r.text}

# ═══════════ 808MAIL ═══════════
async def gen_email(s):
    for _ in range(3):
        try:
            r = await s.get(f"{MAIL}/genera?tipi=dotGmail&semplice=1", timeout=6)
            if r.status_code==200 and "@" in r.text: return r.text.strip()
        except: await asyncio.sleep(0.2)
    return None

async def wait_otp(s, email, total=90):
    deadline = time.monotonic()+total
    while time.monotonic()<deadline:
        try:
            r = await s.get(f"{MAIL}/attendi/{email}",
                params={"mittente":"davinci","codice":1,"semplice":1,"timeout":15000}, timeout=18)
            if r.status_code==200 and r.text.strip():
                m = _OTP_RE.search(r.text)
                if m: return m.group(1)
            r2 = await s.get(f"{MAIL}/inbox/{email}", timeout=5)
            if r2.status_code==200:
                try:
                    d = r2.json()
                    msgs = d if isinstance(d,list) else (d.get("dato") or d.get("messages") or [])
                    for msg in (msgs or [])[:5]:
                        if not isinstance(msg,dict): continue
                        mid = msg.get("id")
                        if not mid: continue
                        r3 = await s.get(f"{MAIL}/leggi/{email}/{mid}?semplice=1", timeout=5)
                        if r3.status_code==200:
                            m = _OTP_RE.search(r3.text)
                            if m: return m.group(1)
                except: pass
        except: pass
        await asyncio.sleep(1.0)
    return None

def rand_pw(n=14):
    c = [random.choice(string.ascii_lowercase), random.choice(string.ascii_uppercase),
         random.choice(string.digits), random.choice("!@#$%")]
    c += random.choices(_PWC, k=n-4); random.shuffle(c); return "".join(c)

# ═══════════ SIGNUP ═══════════
async def signup_one(stats=None):
    async with AsyncSession(impersonate="chrome120", timeout=30) as s:
        s.headers.update(H_BASE)
        email = await gen_email(s)
        if not email: raise RuntimeError("no email")
        password = rand_pw()

        d = await _post(s, FB_SU, {"returnSecureToken":True,"email":email,
                                    "password":password,"clientType":"CLIENT_TYPE_WEB"}, H_FB)
        id_token, refresh_token, local_id = d["idToken"], d["refreshToken"], d["localId"]
        stats and stats.__setitem__('registered', stats.get('registered',0)+1)

        await asyncio.gather(
            _post(s, f"{DV_API}/email-verification-send", {"email":email}, H_JSON),
            _post(s, FB_LK, {"idToken":id_token}, H_FB),
            return_exceptions=True)
        stats and stats.__setitem__('sent', stats.get('sent',0)+1)

        code = await wait_otp(s, email)
        if not code: raise RuntimeError("OTP timeout")
        stats and stats.__setitem__('otp_received', stats.get('otp_received',0)+1)

        v = await _post(s, f"{DV_API}/email-verification-verify-code",
                        {"email":email,"code":code}, H_JSON)
        if not v.get("data",{}).get("verified"): raise RuntimeError("OTP KO")

        d2 = await _post(s, FB_SI, {"returnSecureToken":True,"email":email,
                                     "password":password,"clientType":"CLIENT_TYPE_WEB"}, H_FB)
        id_token, refresh_token = d2["idToken"], d2["refreshToken"]
        ah = {**H_JSON,"x-platform":"web","x-token":id_token}

        await asyncio.gather(
            _post(s, FB_LK, {"idToken":id_token}, H_FB),
            _get(s, f"{DV_API}/user/credit", ah),
            _get(s, f"{DV_API}/get-user-profile", ah),
            _post(s, f"{DV_PAY}/create-user", {"email":email}, ah),
            return_exceptions=True)

        return {"email":email, "password":password, "local_id":local_id,
                "id_token":id_token, "refresh_token":refresh_token, "credits":25,
                "created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

async def signup_bulk(n, concurrency=5, stats=None):
    sem = asyncio.Semaphore(concurrency)
    async def one(i):
        async with sem:
            try: return await signup_one(stats=stats)
            except Exception as e:
                stats and stats.__setitem__('failed', stats.get('failed',0)+1)
                return None
    results = await asyncio.gather(*(one(i) for i in range(n)))
    new = [a for a in results if a]
    if new:
        accs = load_accs(); accs.extend(new); await save_accs(accs)
    return new

# ═══════════ MODELS ═══════════
_MODELS: Optional[list] = None
async def fetch_models(force=False):
    global _MODELS
    if _MODELS and not force: return _MODELS
    if MODELS_CACHE.exists() and not force:
        try: d=_loads(MODELS_CACHE.read_bytes()); _MODELS=d.get("data",d) if isinstance(d,dict) else d; return _MODELS
        except: pass
    async with AsyncSession(impersonate="chrome120",timeout=15) as s:
        r=await s.get(f"{DV_CMS}/image-models",headers=H_BASE)
        if r.status_code!=200: raise RuntimeError(f"models KO: {r.status_code}")
        d=r.json(); MODELS_CACHE.write_bytes(_dumpsb(d))
        _MODELS=d.get("data",d) if isinstance(d,dict) else d
        return _MODELS

_n = lambda s: re.sub(r"[^a-z0-9]","",(s or "").lower())
def _mk(m): return m.get("key","")
def _mn(m): return m.get("modelName") or m.get("name","")
def _mp(m): return m.get("param","")
def _mc(m):
    try: return int(m.get("creditSpend") or m.get("cost") or 0)
    except: return 0
def _mdims(m): return [d.get("dimensionKey","") for d in (m.get("dimensions") or []) if d.get("dimensionKey")]
def _mocl(m): 
    v = m.get("outputCountLimit")
    return int(v) if v else None

def find_model(models, q):
    qn = _n(q)
    if not qn: return None
    for m in models:
        if any(_n(c)==qn for c in [_mk(m),_mn(m),_mp(m)]): return m
    for m in models:
        for c in [_mk(m),_mn(m),_mp(m)]:
            cn=_n(c)
            if cn and (qn in cn or cn in qn): return m
    return None

def resolve_dim(m, ud):
    dims = _mdims(m)
    if not dims: return ud
    if ud in dims: return ud
    ui = ud.lower().replace("x",":")
    for c in DIM_ALIAS.get(ui,[]):
        if c in dims: return c
    return dims[0]

# ═══════════ RESULT ═══════════
@dataclass(slots=True)
class ImageResult:
    process_id:str=""; prompt:str=""; model:str=""; dimension:str=""; status:str=""
    urls:list[str]=field(default_factory=list); credits_used:int=0; duration_s:float=0.0
    account_email:str=""; error:str=""; raw:dict=field(default_factory=dict)

# ═══════════ ACCOUNTS ═══════════
def load_accs():
    if not ACCS_FILE.exists(): return []
    try: return _loads(ACCS_FILE.read_bytes())
    except: return []

_save_lock = asyncio.Lock()
async def save_accs(a):
    async with _save_lock:
        ACCS_FILE.parent.mkdir(exist_ok=True,parents=True)
        tmp = ACCS_FILE.with_suffix(".tmp")
        tmp.write_bytes(_dumpsb(a)); os.replace(tmp, ACCS_FILE)

# ═══════════ TOKEN ═══════════
async def refresh_tok(rt):
    async with AsyncSession(impersonate="chrome120",timeout=15) as s:
        r = await s.post(FB_TOK, data=f"grant_type=refresh_token&refresh_token={rt}",
            headers={"content-type":"application/x-www-form-urlencoded",
                     "x-firebase-gmpid":FB_GMPID,
                     "x-client-version":"Chrome/JsCore/11.10.0/FirebaseCore-web"})
        if r.status_code!=200: raise RuntimeError(f"refresh KO: {r.status_code}")
        d=r.json(); return d["id_token"], d["refresh_token"]

def _jwt(tok, f="exp"):
    try:
        p=tok.split(".")[1]; p+="="*(-len(p)%4)
        return json.loads(base64.urlsafe_b64decode(p)).get(f)
    except: return None
def _expired(tok, safety=60):
    e=_jwt(tok,"exp"); return not e or time.time()>=(e-safety)
def _uid(tok): return _jwt(tok,"user_id") or _jwt(tok,"sub") or ""
def _email(tok): return _jwt(tok,"email") or ""

# ═══════════ RESPONSE PARSING ═══════════
def _pid(r):
    if isinstance(r,str) and len(r)>8: return r
    if isinstance(r,list):
        if r:
            f=r[0]
            if isinstance(f,str): return f
            if isinstance(f,dict):
                for k in ("processId","process_id","id","jobId","job_id","taskId","uuid"):
                    if f.get(k): return str(f[k])
    if isinstance(r,dict):
        for k in ("processId","process_id","id","jobId","job_id","taskId","uuid"):
            if r.get(k): return str(r[k])
        for w in ("data","result","response"):
            if r.get(w):
                p=_pid(r[w])
                if p: return p
    return ""

def _fs_val(v):
    if v is None: return None
    for k,fn in [("stringValue",str),("integerValue",int),("doubleValue",float),
                 ("booleanValue",bool),("timestampValue",str)]:
        if k in v: return fn(v[k]) if fn!=bool else v[k]
    if "nullValue" in v: return None
    if "arrayValue" in v: return [_fs_val(x) for x in v["arrayValue"].get("values",[])]
    if "mapValue" in v: return {k:_fs_val(x) for k,x in v["mapValue"].get("fields",{}).items()}
    return v
def _fs_doc(f): return {k:_fs_val(v) for k,v in (f or {}).items()}

def _urls(doc):
    urls=[]
    def _extract_recursive(o):
        if isinstance(o, str) and o.startswith("http") and any(o.lower().endswith(e) for e in [".png",".jpg",".jpeg",".webp",".gif"]) or (isinstance(o,str) and o.startswith("http") and "storage.googleapis" in o):
            urls.append(o)
        elif isinstance(o, list):
            for it in o: _extract_recursive(it)
        elif isinstance(o, dict):
            for k in ("url","imageUrl","image_url","src","downloadUrl","publicUrl","assetUrl","outputUrl"):
                if isinstance(o.get(k), str) and o[k].startswith("http"): urls.append(o[k])
            for v in o.values(): _extract_recursive(v)
    for k in ("outputs","output","images","results","urls","imageUrls","outputImages","assets","data"):
        v = doc.get(k)
        if v: _extract_recursive(v)
    seen=set(); return [u for u in urls if not (u in seen or seen.add(u))]

# ═══════════ CREDITS ═══════════
async def check_credits(tok):
    try:
        async with AsyncSession(impersonate="chrome120",timeout=8) as s:
            s.headers.update(H_BASE)
            st,body = await _get(s,f"{DV_API}/user/credit",{"x-platform":"web","x-token":tok})
            if st!=200: return 0
            d = body.get("data",body) if isinstance(body,dict) else body
            if isinstance(d,dict):
                return int(d.get("credit") or d.get("balance") or d.get("amount") or 0)
            return int(d) if isinstance(d,(int,float)) else 0
    except: return 0

async def _ensure_tok(acc):
    tok = acc.get("id_token",""); ref = acc.get("refresh_token","")
    if _expired(tok) and ref:
        tok, ref = await refresh_tok(ref)
        acc["id_token"]=tok; acc["refresh_token"]=ref
    return tok

async def scan_credits(accs, concurrency=30):
    sem = asyncio.Semaphore(concurrency)
    async def one(i,a):
        async with sem:
            try:
                tok = await _ensure_tok(a)
                return i, await check_credits(tok), None
            except Exception as e:
                return i, 0, str(e)[:50]
    return await asyncio.gather(*(one(i,a) for i,a in enumerate(accs)))

async def pick_account(need_cr=25, on_status=None):
    accs = load_accs()
    if not accs:
        on_status and on_status("db_empty")
        await signup_bulk(1, concurrency=1); accs = load_accs()

    on_status and on_status("scanning", total=len(accs))
    r = await scan_credits(accs)
    await save_accs(accs)
    valid = sorted([(i,cr) for i,cr,_ in r if cr>=need_cr], key=lambda x:-x[1])
    on_status and on_status("scanned", total=len(accs), valid=len(valid))

    if valid:
        i, cr = valid[0]; acc = accs[i]; acc["_credits"]=cr
        return acc

    on_status and on_status("signup_new")
    new = await signup_bulk(1, concurrency=1)
    if not new: raise RuntimeError("Signup fallito")
    a = new[0]; a["_credits"]=25
    return a

async def pick_accounts_bulk(count, need_cr=25, stats=None):
    accs = load_accs()
    if not accs:
        stats and stats.__setitem__('phase', 'signup_initial')
        await signup_bulk(count, concurrency=min(5,count), stats=stats)
        accs = load_accs()

    stats and stats.__setitem__('phase', 'scanning')
    r = await scan_credits(accs)
    await save_accs(accs)
    valid = [(i,cr) for i,cr,_ in r if cr>=need_cr]

    while len(valid) < count:
        need = count - len(valid)
        stats and stats.__setitem__('phase', f'signup_{need}')
        new = await signup_bulk(need, concurrency=min(5,need), stats=stats)
        if not new: raise RuntimeError("Signup KO")
        accs = load_accs()
        new_idxs = list(range(len(accs)-len(new), len(accs)))
        rn = await scan_credits([accs[i] for i in new_idxs])
        for j,cr,_ in rn:
            actual_i = new_idxs[j]
            if cr>=need_cr: valid.append((actual_i,cr))

    picked = []
    for i,cr in valid[:count]:
        accs[i]["_credits"]=cr
        picked.append(accs[i])
    return picked

# ═══════════ POLLING ═══════════
async def _poll(s, tok, uid, pid, timeout=300, interval=2.0, on_status=None):
    url = f"{FS_BASE}/users/{uid}/processes/{pid}"
    hdr = {"authorization":f"Bearer {tok}"}
    deadline = time.monotonic()+timeout
    last=""
    while time.monotonic()<deadline:
        try:
            r = await s.get(url,headers=hdr)
            if r.status_code==200:
                doc = r.json()
                d = _fs_doc(doc.get("fields",{}) if isinstance(doc,dict) else {})
                st = (d.get("status") or "").upper()
                if st != last:
                    last = st
                    on_status and on_status(st)
                if st in ("COMPLETED","SUCCESS","DONE","FINISHED"): return d
                if st in ("FAILED","ERROR","CANCELLED","REJECTED"):
                    err_msg = (d.get("error") or d.get("errorMessage") or d.get("message")
                               or d.get("failureReason") or d.get("reason") or "")
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message") or err_msg.get("description") or str(err_msg)
                    raise RuntimeError(f"Gen {st}: {err_msg}" if err_msg else f"Gen {st}")
            elif r.status_code==401: raise RuntimeError("401 token scaduto")
        except RuntimeError: raise
        except: pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"pid {pid} timeout (last:{last})")

# ═══════════ GENERATE (universale, adatta payload per modello) ═══════════
def _build_payload(m: dict, prompt: str, dim: str, count: int, art_style_id: int,
                   ref_urls: list[str] = None) -> dict:
    """Costruisce payload adattato al modello specifico."""
    mid = _mk(m)
    payload = {
        "prompt": prompt,
        "model": mid,
        "dimension": dim,
        "artStyleId": art_style_id,
    }
    # imageCount: rispetta il limite del modello
    max_count = _mocl(m)
    if max_count:
        payload["imageCount"] = min(count, max_count)
    else:
        payload["imageCount"] = count

    # reference images (se il modello le supporta)
    if ref_urls and m.get("referenceImage"):
        limit = m.get("referenceImageLimit") or 1
        ref_urls = ref_urls[:limit]
        payload["referenceImages"] = ref_urls
        payload["referenceImage"] = ref_urls[0]

    # CFG (solo QWEN)
    if m.get("cfg"):
        payload["cfg"] = 4.0  # default sicuro

    # Seed (se supportato)
    if m.get("seed"):
        payload["seed"] = random.randint(1, 10**9)

    # Negative prompt (se supportato)
    if m.get("negativePrompt"):
        payload["negativePrompt"] = ""

    return payload

def _pick_endpoint(m: dict, has_ref: bool = False) -> str:
    """Sceglie endpoint corretto per il modello."""
    # Se ha reference image, prova img-image, ma tutti i modelli funzionano anche con txt-image
    # se referenceImages è nel payload
    return f"{DV_API}/process/txt-image"

async def generate_image(id_token, prompt, model="NANO_BANANA_2", dimension="1:1",
                         art_style_id=0, image_count=1, reference_image_urls=None,
                         refresh_token="", timeout=300, on_status=None) -> ImageResult:
    if _expired(id_token):
        if not refresh_token: raise RuntimeError("token scaduto, no refresh_token")
        id_token, refresh_token = await refresh_tok(refresh_token)

    models = await fetch_models()
    m = find_model(models, model)
    if not m: raise RuntimeError(f"model '{model}' KO")
    mid, dim, cost = _mk(m), resolve_dim(m,dimension), _mc(m)
    uid, email = _uid(id_token), _email(id_token)

    t0 = time.perf_counter()
    async with AsyncSession(impersonate="chrome120",timeout=30) as s:
        s.headers.update(H_BASE)
        ah = {**H_JSON,"x-platform":"web","x-token":id_token}
        payload = _build_payload(m, prompt, dim, image_count, art_style_id,
                                  ref_urls=reference_image_urls)
        endpoint = _pick_endpoint(m, has_ref=bool(reference_image_urls))

        resp = await _post(s, endpoint, payload, ah)
        pid = _pid(resp)
        if not pid: raise RuntimeError(f"pid non trovato: {resp}")
        on_status and on_status("submitted", pid=pid)
        doc = await _poll(s, id_token, uid, pid, timeout, on_status=on_status)

    dur = time.perf_counter()-t0
    urls = _urls(doc)
    return ImageResult(process_id=pid, prompt=prompt, model=mid, dimension=dim,
                       status=doc.get("status","COMPLETED"), urls=urls,
                       credits_used=cost, duration_s=dur, account_email=email, raw=doc)

async def _download(url, path):
    try:
        async with AsyncSession(impersonate="chrome120",timeout=120) as s:
            r = await s.get(url)
            if r.status_code==200: path.write_bytes(r.content); return True
    except: pass
    return False

# ═══════════ PUBLIC API ═══════════
def imgmodels(source: str = None) -> list[dict]:
    """
    Ritorna lista modelli. source: None=tutti | 'text'=txt2img | 'img'=supportano reference.
    Uso: from davinci_img_2 import imgmodels; print(imgmodels())
    """
    if not MODELS_CACHE.exists():
        asyncio.run(fetch_models())
    data = _loads(MODELS_CACHE.read_bytes())
    models = data.get("data", data) if isinstance(data, dict) else data

    def _slim(m):
        return {
            "key": _mk(m), "name": _mn(m), "param": _mp(m),
            "cost": _mc(m), "dimensions": _mdims(m),
            "supports_image_ref": bool(m.get("referenceImage")),
            "supports_character": bool(m.get("character")),
            "supports_object": bool(m.get("object")),
            "reference_limit": m.get("referenceImageLimit"),
            "max_output_count": _mocl(m),
            "output_time_s": m.get("outputTime"),
            "supports_cfg": bool(m.get("cfg")),
            "supports_seed": bool(m.get("seed")),
        }

    out = [_slim(m) for m in sorted(models, key=lambda x: x.get("order") or 999)]
    if source == "img": out = [m for m in out if m["supports_image_ref"]]
    return out

async def genimg(
    prompt: str,
    model: str = "NANO_BANANA_2",
    source: str = "text",  # "text" o "img"
    dimension: str = "1:1",
    count: int = 1,
    reference_image_url: str | list = None,
    art_style_id: int = 0,
    download: bool = True,
    output_dir: Path | str = None,
    verbose: bool = False,
) -> dict:
    """
    Genera 1+ immagini. Ritorna dict con success/urls/local_paths/error.
    Uso:
        from davinci_img_2 import genimg
        r = await genimg("un drago", model="GROK_IMAGINE", dimension="16:9")
    """
    out_dir = Path(output_dir) if output_dir else OUT_DIR
    models = await fetch_models()
    m = find_model(models, model)
    if not m:
        return {"success":False, "error":f"Model '{model}' non trovato",
                "urls":[], "local_paths":[], "process_id":"", "model":model,
                "dimension":dimension, "credits_used":0, "duration_s":0, "account_email":""}
    need = _mc(m)

    # ref urls normalize
    ref_urls = None
    if source == "img":
        if not reference_image_url:
            return {"success":False, "error":"source='img' richiede reference_image_url",
                    "urls":[], "local_paths":[], "process_id":"", "model":_mk(m),
                    "dimension":dimension, "credits_used":0, "duration_s":0, "account_email":""}
        if not m.get("referenceImage"):
            return {"success":False, "error":f"Modello {_mk(m)} non supporta reference image",
                    "urls":[], "local_paths":[], "process_id":"", "model":_mk(m),
                    "dimension":dimension, "credits_used":0, "duration_s":0, "account_email":""}
        ref_urls = [reference_image_url] if isinstance(reference_image_url, str) else list(reference_image_url)

    try:
        acc = await pick_account(need_cr=need)
    except Exception as e:
        return {"success":False, "error":f"pick_account KO: {e}",
                "urls":[], "local_paths":[], "process_id":"", "model":_mk(m),
                "dimension":dimension, "credits_used":0, "duration_s":0, "account_email":""}

    try:
        r = await generate_image(
            id_token=acc["id_token"], refresh_token=acc.get("refresh_token",""),
            prompt=prompt, model=_mk(m), dimension=dimension,
            art_style_id=art_style_id, image_count=count,
            reference_image_urls=ref_urls)
    except Exception as e:
        return {"success":False, "error":f"generate KO: {type(e).__name__}: {str(e)[:200]}",
                "urls":[], "local_paths":[], "process_id":"", "model":_mk(m),
                "dimension":dimension, "credits_used":need, "duration_s":0,
                "account_email":acc.get("email","")}

    local_paths = []
    if download and r.urls:
        out_dir.mkdir(exist_ok=True, parents=True)
        for j, url in enumerate(r.urls):
            safe = re.sub(r"[^\w-]","_", prompt[:40])
            fn = out_dir / f"{int(time.time())}_{safe}_{j}.png"
            if await _download(url, fn):
                local_paths.append(str(fn))

    return {
        "success": True, "urls": r.urls, "local_paths": local_paths,
        "process_id": r.process_id, "model": r.model, "dimension": r.dimension,
        "credits_used": r.credits_used, "duration_s": r.duration_s,
        "account_email": r.account_email, "status": r.status, "error": None,
    }

def genimg_sync(prompt: str, **kwargs) -> dict:
    """Wrapper sync di genimg() per script non-async."""
    return asyncio.run(genimg(prompt, **kwargs))

# ═══════════ LIVE UI RENDERER ═══════════
def live_render(n, stats, start, stop_ev, rate_hist):
    while not stop_ev.is_set():
        try:
            el = time.time()-start
            su = stats.get('success',0); fa = stats.get('failed',0)
            reg = stats.get('registered',0); sent = stats.get('sent',0)
            otp = stats.get('otp_received',0); phase = stats.get('phase','running')
            ratio = min(1.0, su/n) if n>0 else 0
            now = time.time(); rate_hist.append((now,su))
            while rate_hist and now-rate_hist[0][0]>5: rate_hist.pop(0)
            rate = ((rate_hist[-1][1]-rate_hist[0][1])/(rate_hist[-1][0]-rate_hist[0][0])
                    if len(rate_hist)>=2 and rate_hist[-1][0]>rate_hist[0][0] else 0)
            avg = su/el if el>0 else 0
            eta = (n-su)/rate if rate>0.001 else 0

            spin = grad(ui.spinner(), (100,255,200), (255,200,100))
            bar = grad_bar(ratio, 44)
            pct = grad(f"{ratio*100:6.2f}%", (255,200,100), (100,255,200))
            l1 = f"  {spin}  {bar}  {pct}"
            l2 = ("  " + grad("✓",(0,255,100),(100,255,200)) + f" {su}/{n}   " +
                  grad("✗",(255,80,80),(255,150,100)) + f" {fa}   " +
                  grad(f"⚡ {rate:5.2f}/s",(255,200,50),(255,100,200)) + "   " +
                  grad(f"μ {avg:5.2f}/s",(150,200,255),(200,150,255)))
            l3 = ("  " + grad(f"📝 reg:{reg}",(255,200,100),(255,100,100)) + "  " +
                  grad(f"📤 sent:{sent}",(255,150,255),(150,100,255)) + "  " +
                  grad(f"📬 mail:{otp}",(100,200,255),(200,150,255)) + "  " +
                  grad(f"⚙ {phase}",(200,200,150),(150,200,255)))
            l4 = ("  " + grad(f"⏱ {fmt_time(el)}",(100,200,255),(150,150,255)) + "  " +
                  grad(f"ETA {fmt_time(eta)}" if eta>0 else "ETA --",(200,150,255),(255,100,200)))
            ui.render(["",l1,l2,l3,l4,""])
            time.sleep(0.1)
        except: time.sleep(0.2)

# ═══════════ BULK ═══════════
async def generate_bulk(prompts, model="NANO_BANANA_2", dimension="1:1",
                        concurrency=5, download=True):
    banner()
    models = await fetch_models()
    m = find_model(models, model)
    if not m:
        print(grad(f"  [!] model '{model}' non trovato", (255,100,100), (255,200,100)))
        return
    need = _mc(m)
    imgs_per_acc = max(1, 25 // need)
    accs_needed = (len(prompts) + imgs_per_acc - 1) // imgs_per_acc

    print(grad(f"  📊 {len(prompts)} prompts × {need}cr → ~{accs_needed} account (max {imgs_per_acc} img/acc)",
               (150,200,255), (255,150,200)))
    print(grad(f"  🎨 model: {_mk(m)}  📐 dim: {dimension}  ⚡ conc: {concurrency}",
               (100,255,200), (255,200,100)))
    print(grad(f"  🚀 loop: {_LOOP}", (255,200,50), (255,100,200)))
    print()

    stats = {'success':0,'failed':0,'registered':0,'sent':0,'otp_received':0,'phase':'init'}
    rate_hist = []; start = time.time(); stop_ev = threading.Event()

    ui_t = threading.Thread(target=live_render, args=(len(prompts),stats,start,stop_ev,rate_hist), daemon=True)
    ui_t.start()

    try:
        accs = await pick_accounts_bulk(accs_needed, need_cr=need, stats=stats)
        stats['phase'] = 'generating'
        OUT_DIR.mkdir(exist_ok=True,parents=True)

        sem = asyncio.Semaphore(concurrency)
        results = [None]*len(prompts)

        async def one(i, prompt, acc):
            async with sem:
                try:
                    r = await generate_image(id_token=acc["id_token"],
                        refresh_token=acc.get("refresh_token",""),
                        prompt=prompt, model=_mk(m), dimension=dimension)
                    results[i]=r; stats['success'] = stats.get('success',0)+1
                    if download and r.urls:
                        for j,u in enumerate(r.urls):
                            safe = re.sub(r"[^\w-]","_",prompt[:40])
                            await _download(u, OUT_DIR/f"{i:04d}_{safe}_{j}.png")
                    icon = grad("  ✓ ",(0,255,100),(100,255,200))
                    id_str = grad(f"[{i+1:>4}]",(150,220,255),(200,150,255))
                    p_str = grad(prompt[:50],(255,255,255),(200,200,200))
                    t_str = grad(f"{r.duration_s:.1f}s",(255,200,100),(255,100,100))
                    u_str = grad(f"{len(r.urls)}img",(100,255,150),(0,200,100))
                    ui.perm(f"{icon}{id_str} {p_str}  {t_str}  {u_str}")
                except Exception as e:
                    stats['failed'] = stats.get('failed',0)+1
                    err = grad("  ✘ ",(255,100,100),(255,150,100))
                    id_str = grad(f"[{i+1:>4}]",(150,220,255),(200,150,255))
                    e_str = grad(f"{type(e).__name__}: {str(e)[:80]}",(255,150,150),(255,100,100))
                    ui.perm(f"{err}{id_str} {e_str}")

        await asyncio.gather(*(one(i,p,accs[i%len(accs)]) for i,p in enumerate(prompts)))
    finally:
        stop_ev.set(); time.sleep(0.3); ui.clear()

    el = time.time()-start
    print()
    print(grad("  ═══════════════════ RISULTATO ═══════════════════", (255,200,50), (255,100,200)))
    print()
    print(grad(f"  ✓ Successi:  {stats['success']}/{len(prompts)}", (0,255,100), (100,255,200)))
    print(grad(f"  ✗ Falliti:   {stats['failed']}", (255,100,100), (255,200,100)))
    print(grad(f"  📝 Signup:   {stats['registered']}", (255,200,100), (255,100,100)))
    print(grad(f"  📬 OTP:      {stats['otp_received']}", (100,200,255), (200,150,255)))
    print(grad(f"  ⏱ Tempo:     {fmt_time(el)}", (100,200,255), (200,150,255)))
    rate = stats['success']/el if el>0 else 0
    print(grad(f"  🚀 Rate:     {rate:.2f} img/s", (255,200,50), (255,100,200)))
    print(grad(f"  💾 Output:   {OUT_DIR}", (150,200,255), (255,150,200)))
    print()
    return [r for r in results if r]

# ═══════════ SINGLE ═══════════
async def generate_single(prompt, model="NANO_BANANA_2", dimension="1:1", count=1,
                          reference_image_urls=None):
    banner()
    models = await fetch_models()
    m = find_model(models, model)
    if not m:
        print(grad(f"  [!] model '{model}' non trovato", (255,100,100), (255,200,100)))
        avail = [_mk(x) for x in models[:8]]
        print(grad(f"  disponibili: {', '.join(avail)}...", (200,200,150), (150,200,255)))
        return
    need = _mc(m)
    print(grad(f"  🎨 {_mk(m)}  📐 {dimension}→{resolve_dim(m,dimension)}  💰 {need}cr",
               (100,255,200), (255,200,100)))
    print(grad(f"  💭 {prompt[:100]}", (200,200,255), (255,200,255)))
    if reference_image_urls:
        print(grad(f"  🖼  ref: {len(reference_image_urls)} img", (100,255,150), (0,200,100)))
    print()

    def on_status(phase, **kw):
        if phase == "db_empty":
            print(grad("  📭 nessun account, creo il primo…", (255,200,100), (255,100,200)))
        elif phase == "scanning":
            print(grad(f"  🔍 scan crediti su {kw.get('total',0)} account…", (100,200,255), (200,150,255)))
        elif phase == "scanned":
            v = kw.get('valid',0); t = kw.get('total',0)
            print(grad(f"  ✓ {v}/{t} account con ≥{need}cr", (0,255,100), (100,255,200)))
        elif phase == "signup_new":
            print(grad(f"  📝 tutti esauriti, signup nuovo…", (255,200,100), (255,100,100)))

    acc = await pick_account(need_cr=need, on_status=on_status)
    print(grad(f"  → {acc['email'][:40]}  💰{acc.get('_credits','?')}cr",
               (100,255,150), (0,200,100)))
    print()

    t0 = time.perf_counter()
    status_line = {"current":"SUBMITTING"}
    stop_ev = threading.Event()

    def status_render():
        while not stop_ev.is_set():
            spin = grad(ui.spinner(), (100,255,200), (255,200,100))
            el = time.perf_counter()-t0
            st = grad(status_line["current"], (255,200,100), (100,255,200))
            t_str = grad(f"{el:.1f}s", (200,200,255), (255,200,255))
            ui.render([f"  {spin}  {st}  {t_str}"])
            time.sleep(0.1)
    ui_t = threading.Thread(target=status_render, daemon=True); ui_t.start()

    try:
        def on_gen(phase, **kw): status_line["current"] = phase
        r = await generate_image(id_token=acc["id_token"],
            refresh_token=acc.get("refresh_token",""),
            prompt=prompt, model=_mk(m), dimension=dimension,
            image_count=count, reference_image_urls=reference_image_urls,
            on_status=on_gen)
    except Exception as e:
        stop_ev.set(); time.sleep(0.15); ui.clear()
        print()
        print(grad(f"  ✘ ERROR: {type(e).__name__}: {str(e)[:200]}",
                   (255,100,100), (255,200,100)))
        print()
        return None
    finally:
        stop_ev.set(); time.sleep(0.15); ui.clear()

    print()
    print(grad("  ═══════════════════ RESULT ═══════════════════", (255,200,50), (255,100,200)))
    print()
    print(grad(f"  ✓ status:  {r.status}", (0,255,100), (100,255,200)))
    print(grad(f"  🎨 model:   {r.model}  {r.dimension}", (100,255,200), (255,200,100)))
    print(grad(f"  💰 credit:  {r.credits_used}cr", (255,200,50), (255,100,200)))
    print(grad(f"  ⏱ time:    {r.duration_s:.1f}s", (100,200,255), (200,150,255)))
    print(grad(f"  🖼  images:  {len(r.urls)}", (100,255,150), (0,200,100)))
    print()
    for u in r.urls:
        print(grad(f"  → {u[:120]}", (150,200,255), (200,150,255)))
    if r.urls:
        OUT_DIR.mkdir(exist_ok=True,parents=True)
        for j,u in enumerate(r.urls):
            safe = re.sub(r"[^\w-]","_",prompt[:40])
            fn = OUT_DIR/f"single_{safe}_{j}.png"
            if await _download(u,fn):
                print(grad(f"  💾 {fn}", (0,255,150), (100,255,200)))
    print()
    return r

# ═══════════ CLI PARSER ═══════════
def _parse_flags(args):
    """Estrae flag: --model=X, model X, -m X, --dim=Y, --count=N, --ref=URL."""
    prompt_parts = []; kw = {}
    i = 0
    while i < len(args):
        a = args[i]
        # --key=value
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            kw[k.lower().replace("-","_")] = v
        # -k value / --key value / key value
        elif a.lower() in ("model","-m","--model") and i+1<len(args):
            i += 1; kw["model"] = args[i]
        elif a.lower() in ("dim","aspect","-d","--dim","--aspect") and i+1<len(args):
            i += 1; kw["dim"] = args[i]
        elif a.lower() in ("count","-c","--count","n") and i+1<len(args):
            i += 1; kw["count"] = int(args[i])
        elif a.lower() in ("ref","--ref","-r") and i+1<len(args):
            i += 1; kw.setdefault("ref",[]).append(args[i])
        else:
            prompt_parts.append(a)
        i += 1
    prompt = " ".join(prompt_parts)
    return prompt, kw

async def _cli():
    args = sys.argv[1:]; name = Path(__file__).name

    if not args or args[0] in ("-h","--help","help"):
        banner()
        print(grad(f"""
  {name} <prompt>                            single (default Nano Banana 2, 25cr)
  {name} <prompt> --model=GROK_IMAGINE       10cr = 2 img/acc
  {name} <prompt> model DAVINCI_ULTRA        stessa cosa senza --
  {name} <prompt> --dim=16:9 --count=1
  {name} <prompt> --model=NANO_BANANA --ref=https://img.url  img2img

  {name} bulk <file.txt>                     bulk
  {name} bulk <file.txt> 10 --model=FLUX_2_TURBO --dim=9:16

  {name} signup [N] [conc]   crea N account (default 1, conc=5)
  {name} models              lista modelli con costi
  {name} models img          solo modelli con reference image
  {name} credits             crediti disponibili per account
  {name} refresh-models      ricarica modelli da CMS
  {name} refresh-token       refresha JWT scaduti

  💚 Cheap (2+ img/acc):
    FLUX_2_TURBO / GPT_IMAGE_1 / QWEN  (9cr)
    GROK_IMAGINE                       (10cr)
    KONTEXT (Flux Pro)                 (11cr)
    FLUX_2                             (12cr)
    NANO_BANANA / SEEDREAM_45 / RECRAFT (13cr)

  💛 Medio (1 img/acc):
    GROK_IMAGINE_QUALITY   (14cr)
    SEEDREAM_5_LITE / DAVINCI_ULTRA / IDEOGRAM_V3/V4 / RECRAFT_V4_1 /
    KREA_V2_LARGE / MAI_IMAGE_2_5 / QWEN_IMAGE_2 / SEEDREAM (15cr)

  💜 Premium (1 img/acc):
    SEEDREAM_5_PRO / GPT_IMAGE_2 / QWEN_IMAGE_2_PRO / RECRAFT_V4_1_PRO (20cr)
    NANO_BANANA_2 / NANO_BANANA_PRO                                   (25cr)
""", (150,220,255), (255,200,150)))
        return

    cmd = args[0]

    if cmd == "signup":
        n = int(args[1]) if len(args)>1 else 1
        conc = int(args[2]) if len(args)>2 else min(5,n)
        banner()
        print(grad(f"  📝 creo {n} account (conc={conc})", (255,200,100), (100,255,200)))
        print()
        stats = {'success':0,'failed':0,'registered':0,'sent':0,'otp_received':0,'phase':'signup'}
        start = time.time(); stop_ev = threading.Event(); rate_hist = []
        ui_t = threading.Thread(target=live_render, args=(n,stats,start,stop_ev,rate_hist), daemon=True)
        ui_t.start()
        try:
            sem = asyncio.Semaphore(conc)
            async def one(i):
                async with sem:
                    try:
                        a = await signup_one(stats=stats)
                        stats['success']+=1
                        accs = load_accs(); accs.append(a); await save_accs(accs)
                        icon = grad("  ✓ ",(0,255,100),(100,255,200))
                        id_str = grad(f"[{i+1:>3}/{n}]",(150,220,255),(200,150,255))
                        e_str = grad(a['email'][:40],(255,255,255),(200,200,200))
                        ui.perm(f"{icon}{id_str} {e_str}")
                    except Exception as e:
                        stats['failed']+=1
                        err = grad("  ✘ ",(255,100,100),(255,150,100))
                        id_str = grad(f"[{i+1:>3}/{n}]",(150,220,255),(200,150,255))
                        e_str = grad(f"{type(e).__name__}: {str(e)[:60]}",(255,150,150),(255,100,100))
                        ui.perm(f"{err}{id_str} {e_str}")
            await asyncio.gather(*(one(i) for i in range(n)))
        finally:
            stop_ev.set(); time.sleep(0.3); ui.clear()
        el = time.time()-start
        print()
        print(grad(f"  ✔ {stats['success']}/{n} account creati in {fmt_time(el)}", (0,255,100), (100,255,200)))
        print(grad(f"  💾 {ACCS_FILE}", (150,200,255), (255,150,200)))
        print()
        return

    if cmd == "models":
        banner()
        filter_kind = args[1] if len(args)>1 else None
        models = await fetch_models()
        if filter_kind == "img":
            models = [m for m in models if m.get("referenceImage")]
        print(grad(f"  📋 {len(models)} MODELS" + (f" (con reference image)" if filter_kind=="img" else ""),
                   (255,200,100), (100,255,200)))
        print()
        for m in sorted(models, key=lambda x: x.get("order") or 999):
            k,n,c = _mk(m), _mn(m), _mc(m)
            dims = ",".join(_mdims(m)[:6])
            ref = "🖼" if m.get("referenceImage") else "  "
            color = (100,255,150) if c<=10 else (255,200,100) if c<=15 else (255,150,150)
            print(f"  {ref} " + grad(f"{k:<26}",(200,220,255),(150,200,255)) +
                  f" {n:<24} " + grad(f"({c:>3}cr)",*[color,color]) + f"  [{dims}]")
        print()
        return

    if cmd == "refresh-models":
        await fetch_models(force=True)
        print(grad("  ✓ modelli aggiornati", (0,255,100), (100,255,200)))
        return

    if cmd == "credits":
        banner()
        accs = load_accs()
        print(grad(f"  📊 scan crediti su {len(accs)} account…", (100,200,255), (200,150,255)))
        print()
        r = await scan_credits(accs)
        await save_accs(accs)
        total=0
        for i,cr,err in sorted(r, key=lambda x:-x[1]):
            mark_color = (0,255,100) if cr>=25 else (255,200,100) if cr>0 else (150,150,150)
            mark = grad("✓" if cr>=25 else "⚠" if cr>0 else "✗", *[mark_color]*2)
            e = accs[i].get('email','?')[:40]
            extra = grad(f"  ({err})", (255,150,150), (255,100,100)) if err else ""
            cr_str = grad(f"💰{cr:>4}cr", *[mark_color]*2)
            print(f"  {mark} [{i:>3}] " + grad(f"{e:40s}", (200,220,255), (255,220,220)) + f"  {cr_str}{extra}")
            total += cr
        print()
        print(grad(f"  💰 Totale: {total} cr", (255,200,50), (255,100,200)))
        for lbl, cost in [("NanoBanana Pro/2",25),("Ideogram/Seedream",15),
                          ("Nano Banana/Seedream 4.5",13),("Grok",10),
                          ("Flux Turbo/GPT1/Qwen",9)]:
            print(grad(f"     ~{total//cost:>4} img {lbl} ({cost}cr)", (150,200,255), (255,200,150)))
        print()
        return

    if cmd == "refresh-token":
        accs = load_accs()
        print(grad(f"  🔄 refresh {len(accs)} tokens…", (100,200,255), (255,150,200)))
        sem = asyncio.Semaphore(20)
        async def one(i, acc):
            async with sem:
                if not acc.get("refresh_token"): return False
                try:
                    tok,ref = await refresh_tok(acc["refresh_token"])
                    accs[i]["id_token"]=tok; accs[i]["refresh_token"]=ref
                    return True
                except: return False
        results = await asyncio.gather(*(one(i,a) for i,a in enumerate(accs)))
        await save_accs(accs)
        ok = sum(1 for r in results if r)
        print(grad(f"  ✓ {ok}/{len(accs)} tokens rinnovati", (0,255,100), (100,255,200)))
        return

    if cmd == "bulk":
        pf = Path(args[1])
        rest, kw = _parse_flags(args[2:])
        conc = 5
        for part in rest.split():
            if part.isdigit(): conc = int(part); break
        model = kw.get("model", "NANO_BANANA_2")
        dim = kw.get("dim", "1:1")
        prompts = [l.strip() for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()]
        await generate_bulk(prompts, model=model, dimension=dim, concurrency=conc)
        return

    # single
    prompt, kw = _parse_flags(args)
    if not prompt:
        print(grad("  [!] prompt vuoto", (255,100,100), (255,200,100))); return
    model = kw.get("model", "NANO_BANANA_2")
    dim = kw.get("dim", "1:1")
    count = int(kw.get("count", 1))
    refs = kw.get("ref")
    if refs and isinstance(refs, str): refs = [refs]
    await generate_single(prompt, model=model, dimension=dim, count=count,
                          reference_image_urls=refs)

if __name__ == "__main__":
    try: asyncio.run(_cli())
    except KeyboardInterrupt:
        ui.clear(); print(grad("\n[!] Interrotto", (255,100,100), (255,200,100)))