
import os
from datetime import datetime,timedelta,timezone
from passlib.context import CryptContext
from jose import jwt,JWTError
from fastapi import Request

SECRET=os.getenv("SECRET_KEY","dev-secret-change-me")
ALGO="HS256"
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")

def hash_password(v): return pwd.hash(v)
def verify_password(v,h): return pwd.verify(v,h)

def create_token(user_id:int):
    payload={"sub":str(user_id),"exp":datetime.now(timezone.utc)+timedelta(days=30)}
    return jwt.encode(payload,SECRET,algorithm=ALGO)

def user_id_from_request(request:Request):
    token=request.cookies.get("cashly_session")
    if not token:return None
    try:return int(jwt.decode(token,SECRET,algorithms=[ALGO])["sub"])
    except Exception:return None
