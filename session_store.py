
import os, json
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken

SESSION_FILE=os.getenv("SESSION_FILE","./data/shopee_session.enc")
KEY=os.getenv("SESSION_ENCRYPTION_KEY","").encode()
META_FILE=SESSION_FILE+".meta.json"

def configured():
    return bool(KEY and os.path.exists(SESSION_FILE))

def save_state(state, meta=None):
    if not KEY:
        raise RuntimeError("SESSION_ENCRYPTION_KEY belum di-set")
    os.makedirs(os.path.dirname(SESSION_FILE) or ".", exist_ok=True)
    token=Fernet(KEY).encrypt(json.dumps(state).encode())
    with open(SESSION_FILE,"wb") as f:
        f.write(token)
    metadata = {
        "connected": True,
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "login_method": "qr",
    }
    if meta:
        metadata.update(meta)
    with open(META_FILE,"w",encoding="utf-8") as f:
        json.dump(metadata,f,indent=2)

def load_state():
    if not configured():
        raise RuntimeError("Session belum tersedia")
    try:
        raw=Fernet(KEY).decrypt(open(SESSION_FILE,"rb").read())
        return json.loads(raw.decode())
    except InvalidToken:
        raise RuntimeError("SESSION_ENCRYPTION_KEY tidak cocok dengan session file")

def delete_state():
    for p in (SESSION_FILE,META_FILE):
        if os.path.exists(p):
            os.remove(p)

def info():
    meta={}
    if os.path.exists(META_FILE):
        try:
            meta=json.load(open(META_FILE,"r",encoding="utf-8"))
        except Exception:
            meta={}
    return {
        "configured": configured(),
        "path": SESSION_FILE,
        "login_method": meta.get("login_method"),
        "connected_at": meta.get("connected_at"),
        "account_hint": meta.get("account_hint"),
    }
