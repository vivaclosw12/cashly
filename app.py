
import os,secrets,asyncio
from decimal import Decimal
from urllib.parse import urlencode
from fastapi import FastAPI,Request,Form,HTTPException,UploadFile,File
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()
from db import SessionLocal,User,Merchant,Click,Conversion,Ledger,Withdrawal
from resolver import extract_url,resolve_shopee,clean_shopee
from session_store import configured,delete_state,info
from qr_login import run_qr_login,QRLoginTimeout
from auth import hash_password,verify_password,create_token,user_id_from_request
from importer import import_report

APP_NAME=os.getenv("APP_NAME","Cashly")
AFF_ID=os.getenv("SHOPEE_AFFILIATE_ID","").strip()
ADMIN_TOKEN=os.getenv("ADMIN_TOKEN","")
USER_SHARE=Decimal(os.getenv("USER_SHARE_PERCENT","80"))
MIN_WITHDRAWAL=Decimal(os.getenv("MIN_WITHDRAWAL","50000"))

app=FastAPI(title=f"{APP_NAME} Cashback Platform")
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")
qr_jobs={};qr_lock=asyncio.Lock()

def rupiah(x):
    try:return "Rp{:,.0f}".format(float(x)).replace(",",".")
    except:return "Rp0"

def current_user(request):
    uid=user_id_from_request(request)
    if not uid:return None
    with SessionLocal() as db:return db.query(User).filter(User.id==uid,User.is_active==True).first()

def wallet(db,user_id):
    entries=db.query(Ledger).filter(Ledger.user_id==user_id).all()
    bal=sum((Decimal(str(x.amount)) for x in entries),Decimal("0"))
    pending=db.query(Conversion).join(Click,Click.click_id==Conversion.click_id).filter(Click.user_id==user_id,Conversion.status=="pending").all()
    pending_amt=sum((Decimal(str(x.cashback_amount)) for x in pending),Decimal("0"))
    lifetime=db.query(Conversion).join(Click,Click.click_id==Conversion.click_id).filter(Click.user_id==user_id,Conversion.status=="confirmed").all()
    lifetime_amt=sum((Decimal(str(x.cashback_amount)) for x in lifetime),Decimal("0"))
    reserved=sum((Decimal(str(x.amount)) for x in db.query(Withdrawal).filter(Withdrawal.user_id==user_id,Withdrawal.status.in_(["pending","processing"])).all()),Decimal("0"))
    return bal-reserved,pending_amt,lifetime_amt,reserved

@app.get("/",response_class=HTMLResponse)
async def home(request:Request):
    user=current_user(request)
    with SessionLocal() as db:
        merchants=db.query(Merchant).filter(Merchant.status=="active").all()
        if user:
            available,pending,lifetime,reserved=wallet(db,user.id)
            recent=db.query(Conversion).join(Click,Click.click_id==Conversion.click_id).filter(Click.user_id==user.id).order_by(Conversion.id.desc()).limit(10).all()
        else:
            available=pending=lifetime=reserved=Decimal("0");recent=[]
        return templates.TemplateResponse("index.html",{"request":request,"app_name":APP_NAME,"user":user,"merchants":merchants,
            "balance":rupiah(available),"pending":rupiah(pending),"lifetime":rupiah(lifetime),"recent":recent,"rupiah":rupiah})

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request):return templates.TemplateResponse("auth.html",{"request":request,"mode":"login","app_name":APP_NAME})
@app.get("/register",response_class=HTMLResponse)
def reg_page(request:Request):return templates.TemplateResponse("auth.html",{"request":request,"mode":"register","app_name":APP_NAME})

@app.post("/register")
def register(name:str=Form(...),email:str=Form(...),password:str=Form(...)):
    email=email.strip().lower()
    if len(password)<8:return RedirectResponse("/register?error=Password+minimum+8+characters",303)
    with SessionLocal() as db:
        if db.query(User).filter(User.email==email).first():return RedirectResponse("/login?error=Email+already+registered",303)
        u=User(name=name.strip(),email=email,password_hash=hash_password(password));db.add(u);db.commit();db.refresh(u)
        token=create_token(u.id)
    r=RedirectResponse("/",303);r.set_cookie("cashly_session",token,httponly=True,samesite="lax",max_age=2592000);return r

@app.post("/login")
def login(email:str=Form(...),password:str=Form(...)):
    with SessionLocal() as db:
        u=db.query(User).filter(User.email==email.strip().lower()).first()
        if not u or not verify_password(password,u.password_hash):return RedirectResponse("/login?error=Invalid+credentials",303)
        token=create_token(u.id)
    r=RedirectResponse("/",303);r.set_cookie("cashly_session",token,httponly=True,samesite="lax",max_age=2592000);return r

@app.get("/logout")
def logout():
    r=RedirectResponse("/",303);r.delete_cookie("cashly_session");return r

@app.get("/wallet",response_class=HTMLResponse)
def wallet_page(request:Request):
    user=current_user(request)
    if not user:return RedirectResponse("/login",303)
    with SessionLocal() as db:
        available,pending,lifetime,reserved=wallet(db,user.id)
        ledger=db.query(Ledger).filter(Ledger.user_id==user.id).order_by(Ledger.id.desc()).limit(100).all()
        withdrawals=db.query(Withdrawal).filter(Withdrawal.user_id==user.id).order_by(Withdrawal.id.desc()).limit(30).all()
        return templates.TemplateResponse("wallet.html",{"request":request,"user":user,"app_name":APP_NAME,"available":rupiah(available),
            "pending":rupiah(pending),"lifetime":rupiah(lifetime),"reserved":rupiah(reserved),"ledger":ledger,"withdrawals":withdrawals,"rupiah":rupiah,"minimum":rupiah(MIN_WITHDRAWAL)})

@app.post("/wallet/withdraw")
def withdraw(request:Request,amount:float=Form(...),destination:str=Form(...)):
    user=current_user(request)
    if not user:return RedirectResponse("/login",303)
    amt=Decimal(str(amount))
    with SessionLocal() as db:
        available,_,_,_=wallet(db,user.id)
        if amt<MIN_WITHDRAWAL or amt>available:return RedirectResponse("/wallet?error=Invalid+withdrawal+amount",303)
        db.add(Withdrawal(user_id=user.id,amount=amt,destination=destination.strip(),status="pending"));db.commit()
    return RedirectResponse("/wallet?success=Withdrawal+submitted",303)

@app.post("/api/convert")
async def convert(request:Request,url:str=Form(...)):
    user=current_user(request)
    if not user:return JSONResponse({"ok":False,"error":"Login required"},401)
    if not AFF_ID:return JSONResponse({"ok":False,"error":"Affiliate ID not configured"},400)
    with SessionLocal() as db:
        merchant=db.query(Merchant).filter(Merchant.slug=="shopee").first()
        try:
            inp=extract_url(url);resolved=await resolve_shopee(inp);clean=clean_shopee(resolved)
            click_id="CLK_"+secrets.token_urlsafe(10)
            sub_id=f"u{user.id}-{click_id}-web"
            aff="https://s.shopee.co.id/an_redir?"+urlencode({"origin_link":clean,"affiliate_id":AFF_ID,"sub_id":sub_id})
            db.add(Click(click_id=click_id,user_id=user.id,merchant_id=merchant.id,source_url=inp,clean_url=clean,affiliate_url=aff,sub_id=sub_id));db.commit()
            return {"ok":True,"click_id":click_id,"sub_id":sub_id,"affiliate_url":aff}
        except Exception as e:return JSONResponse({"ok":False,"error":str(e)},400)

def check_admin(token):
    if not ADMIN_TOKEN or token!=ADMIN_TOKEN:raise HTTPException(401,"Unauthorized")

@app.get("/admin",response_class=HTMLResponse)
async def admin(request:Request,token:str=""):
    check_admin(token)
    with SessionLocal() as db:
        users=db.query(User).count();clicks=db.query(Click).count()
        conversions=db.query(Conversion).order_by(Conversion.id.desc()).limit(30).all()
        merchants=db.query(Merchant).all();withdrawals=db.query(Withdrawal).order_by(Withdrawal.id.desc()).limit(20).all()
        confirmed=db.query(Conversion).filter(Conversion.status=="confirmed").all()
        total_comm=sum((Decimal(str(x.commission_amount)) for x in confirmed),Decimal("0"))
        total_cashback=sum((Decimal(str(x.cashback_amount)) for x in confirmed),Decimal("0"))
        revenue=sum((Decimal(str(x.platform_revenue)) for x in confirmed),Decimal("0"))
        return templates.TemplateResponse("admin.html",{"request":request,"app_name":APP_NAME,"token":token,"users":users,"clicks":clicks,
            "conversions":conversions,"merchants":merchants,"withdrawals":withdrawals,"session":info(),"total_comm":rupiah(total_comm),
            "total_cashback":rupiah(total_cashback),"revenue":rupiah(revenue),"affiliate_id":AFF_ID or "Not configured"})

@app.post("/admin/import-report")
async def admin_import_report(token:str=Form(...),file:UploadFile=File(...)):
    check_admin(token)
    raw=await file.read()
    result=import_report(raw,file.filename,USER_SHARE)
    if not result.get("ok"):
        return JSONResponse(result,400)
    return result

@app.post("/admin/withdrawals/{wid}/{action}")
def admin_withdrawal(wid:int,action:str,token:str=Form(...)):
    check_admin(token)
    if action not in ["approve","reject","processing"]:raise HTTPException(400,"Invalid action")
    with SessionLocal() as db:
        w=db.query(Withdrawal).filter(Withdrawal.id==wid).first()
        if not w:raise HTTPException(404,"Withdrawal not found")
        if action=="approve" and w.status!="approved":
            db.add(Ledger(user_id=w.user_id,entry_type="withdrawal_debit",amount=-Decimal(str(w.amount)),reference=f"WD-{w.id}",note="Withdrawal approved"))
            w.status="approved"
        elif action=="reject":w.status="rejected"
        else:w.status="processing"
        db.commit()
    return RedirectResponse(f"/admin?token={token}",303)

async def _qr_login_task(job_id):
    qr_jobs[job_id]={"status":"starting","error":None}
    try:
        async with qr_lock:
            qr_jobs[job_id]["status"]="waiting_scan";result=await run_qr_login()
            qr_jobs[job_id]={"status":"connected","error":None,"result":result}
    except QRLoginTimeout as e:qr_jobs[job_id]={"status":"timeout","error":str(e)}
    except Exception as e:qr_jobs[job_id]={"status":"failed","error":str(e)}

@app.post("/admin/affiliate/qr/start")
async def start_qr_login(token:str=Form(...)):
    check_admin(token);job_id=secrets.token_urlsafe(8);qr_jobs[job_id]={"status":"queued","error":None};asyncio.create_task(_qr_login_task(job_id));return {"ok":True,"job_id":job_id}
@app.get("/admin/affiliate/qr/status")
async def qr_status(token:str="",job_id:str=""):
    check_admin(token);job=qr_jobs.get(job_id)
    if not job:raise HTTPException(404,"QR login job not found")
    return {"ok":True,**job,"session":info()}
@app.post("/admin/session/delete")
async def delete_session(token:str=Form(...)):
    check_admin(token);delete_state();return RedirectResponse(f"/admin?token={token}",303)
@app.get("/health")
def health():return {"ok":True,"affiliate_id_configured":bool(AFF_ID),"session_configured":configured()}
