import os
import secrets
import asyncio
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import (
    FastAPI,
    Request,
    Form,
    HTTPException,
    UploadFile,
    File,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    FileResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from db import (
    SessionLocal,
    User,
    Merchant,
    Click,
    Conversion,
    Ledger,
    Withdrawal,
)

from resolver import (
    extract_url,
    resolve_shopee,
    clean_shopee,
)

from session_store import (
    configured,
    delete_state,
    info,
)

from qr_login import (
    run_qr_login,
    QRLoginTimeout,
    get_qr_path,
)

from auth import (
    hash_password,
    verify_password,
    create_token,
    user_id_from_request,
)

from importer import import_report


APP_NAME = os.getenv(
    "APP_NAME",
    "Cashly",
)

AFF_ID = os.getenv(
    "SHOPEE_AFFILIATE_ID",
    "",
).strip()

ADMIN_TOKEN = os.getenv(
    "ADMIN_TOKEN",
    "",
)

USER_SHARE = Decimal(
    os.getenv(
        "USER_SHARE_PERCENT",
        "80",
    )
)

MIN_WITHDRAWAL = Decimal(
    os.getenv(
        "MIN_WITHDRAWAL",
        "50000",
    )
)


app = FastAPI(
    title=f"{APP_NAME} Cashback Platform"
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

templates = Jinja2Templates(
    directory="templates"
)


# =========================================================
# QR JOBS
# =========================================================

qr_jobs = {}

qr_lock = asyncio.Lock()


# =========================================================
# HELPERS
# =========================================================

def rupiah(value):
    try:
        return (
            "Rp{:,.0f}"
            .format(float(value))
            .replace(",", ".")
        )
    except Exception:
        return "Rp0"


def current_user(
    request: Request,
):
    user_id = user_id_from_request(
        request
    )

    if not user_id:
        return None

    with SessionLocal() as db:

        return (
            db.query(User)
            .filter(
                User.id == user_id,
                User.is_active == True,
            )
            .first()
        )


def wallet(
    db,
    user_id: int,
):

    entries = (
        db.query(Ledger)
        .filter(
            Ledger.user_id == user_id
        )
        .all()
    )

    ledger_balance = sum(
        (
            Decimal(str(entry.amount))
            for entry in entries
        ),
        Decimal("0"),
    )


    pending_cashbacks = (
        db.query(Conversion)
        .join(
            Click,
            Click.click_id
            == Conversion.click_id,
        )
        .filter(
            Click.user_id == user_id,
            Conversion.status
            == "pending",
        )
        .all()
    )

    pending_amount = sum(
        (
            Decimal(
                str(
                    conversion.cashback_amount
                )
            )
            for conversion
            in pending_cashbacks
        ),
        Decimal("0"),
    )


    confirmed_cashbacks = (
        db.query(Conversion)
        .join(
            Click,
            Click.click_id
            == Conversion.click_id,
        )
        .filter(
            Click.user_id == user_id,
            Conversion.status
            == "confirmed",
        )
        .all()
    )

    lifetime_amount = sum(
        (
            Decimal(
                str(
                    conversion.cashback_amount
                )
            )
            for conversion
            in confirmed_cashbacks
        ),
        Decimal("0"),
    )


    reserved_withdrawals = (
        db.query(Withdrawal)
        .filter(
            Withdrawal.user_id == user_id,
            Withdrawal.status.in_(
                [
                    "pending",
                    "processing",
                ]
            ),
        )
        .all()
    )

    reserved_amount = sum(
        (
            Decimal(
                str(withdrawal.amount)
            )
            for withdrawal
            in reserved_withdrawals
        ),
        Decimal("0"),
    )


    available = (
        ledger_balance
        - reserved_amount
    )


    return (
        available,
        pending_amount,
        lifetime_amount,
        reserved_amount,
    )


def check_admin(
    token: str,
):

    if (
        not ADMIN_TOKEN
        or token != ADMIN_TOKEN
    ):

        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


# =========================================================
# HOME
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def home(
    request: Request,
):

    user = current_user(
        request
    )

    with SessionLocal() as db:

        merchants = (
            db.query(Merchant)
            .filter(
                Merchant.status
                == "active"
            )
            .all()
        )

        if user:

            (
                available,
                pending,
                lifetime,
                reserved,
            ) = wallet(
                db,
                user.id,
            )

            recent = (
                db.query(Conversion)
                .join(
                    Click,
                    Click.click_id
                    == Conversion.click_id,
                )
                .filter(
                    Click.user_id
                    == user.id
                )
                .order_by(
                    Conversion.id.desc()
                )
                .limit(10)
                .all()
            )

        else:

            available = Decimal("0")
            pending = Decimal("0")
            lifetime = Decimal("0")
            reserved = Decimal("0")
            recent = []


        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "app_name": APP_NAME,
                "user": user,
                "merchants": merchants,
                "balance": rupiah(
                    available
                ),
                "pending": rupiah(
                    pending
                ),
                "lifetime": rupiah(
                    lifetime
                ),
                "recent": recent,
                "rupiah": rupiah,
            },
        )


# =========================================================
# AUTH
# =========================================================

@app.get(
    "/login",
    response_class=HTMLResponse,
)
def login_page(
    request: Request,
):

    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "login",
            "app_name": APP_NAME,
        },
    )


@app.get(
    "/register",
    response_class=HTMLResponse,
)
def register_page(
    request: Request,
):

    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register",
            "app_name": APP_NAME,
        },
    )


@app.post(
    "/register"
)
def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):

    email = (
        email
        .strip()
        .lower()
    )

    name = name.strip()


    if len(name) < 2:

        return RedirectResponse(
            "/register?error=Invalid+name",
            status_code=303,
        )


    if len(password) < 8:

        return RedirectResponse(
            "/register?error=Password+minimum+8+characters",
            status_code=303,
        )


    with SessionLocal() as db:

        existing = (
            db.query(User)
            .filter(
                User.email == email
            )
            .first()
        )

        if existing:

            return RedirectResponse(
                "/login?error=Email+already+registered",
                status_code=303,
            )


        user = User(
            name=name,
            email=email,
            password_hash=hash_password(
                password
            ),
        )

        db.add(
            user
        )

        db.commit()

        db.refresh(
            user
        )


        token = create_token(
            user.id
        )


    response = RedirectResponse(
        "/",
        status_code=303,
    )

    response.set_cookie(
        "cashly_session",
        token,
        httponly=True,
        samesite="lax",
        max_age=2592000,
    )

    return response


@app.post(
    "/login"
)
def login(
    email: str = Form(...),
    password: str = Form(...),
):

    email = (
        email
        .strip()
        .lower()
    )


    with SessionLocal() as db:

        user = (
            db.query(User)
            .filter(
                User.email == email
            )
            .first()
        )


        if (
            not user
            or not verify_password(
                password,
                user.password_hash,
            )
        ):

            return RedirectResponse(
                "/login?error=Invalid+credentials",
                status_code=303,
            )


        token = create_token(
            user.id
        )


    response = RedirectResponse(
        "/",
        status_code=303,
    )

    response.set_cookie(
        "cashly_session",
        token,
        httponly=True,
        samesite="lax",
        max_age=2592000,
    )

    return response


@app.get(
    "/logout"
)
def logout():

    response = RedirectResponse(
        "/",
        status_code=303,
    )

    response.delete_cookie(
        "cashly_session"
    )

    return response


# =========================================================
# WALLET
# =========================================================

@app.get(
    "/wallet",
    response_class=HTMLResponse,
)
def wallet_page(
    request: Request,
):

    user = current_user(
        request
    )

    if not user:

        return RedirectResponse(
            "/login",
            status_code=303,
        )


    with SessionLocal() as db:

        (
            available,
            pending,
            lifetime,
            reserved,
        ) = wallet(
            db,
            user.id,
        )


        ledger = (
            db.query(Ledger)
            .filter(
                Ledger.user_id
                == user.id
            )
            .order_by(
                Ledger.id.desc()
            )
            .limit(100)
            .all()
        )


        withdrawals = (
            db.query(Withdrawal)
            .filter(
                Withdrawal.user_id
                == user.id
            )
            .order_by(
                Withdrawal.id.desc()
            )
            .limit(30)
            .all()
        )


        return templates.TemplateResponse(
            "wallet.html",
            {
                "request": request,
                "user": user,
                "app_name": APP_NAME,
                "available": rupiah(
                    available
                ),
                "pending": rupiah(
                    pending
                ),
                "lifetime": rupiah(
                    lifetime
                ),
                "reserved": rupiah(
                    reserved
                ),
                "ledger": ledger,
                "withdrawals":
                    withdrawals,
                "rupiah": rupiah,
                "minimum": rupiah(
                    MIN_WITHDRAWAL
                ),
            },
        )


@app.post(
    "/wallet/withdraw"
)
def withdraw(
    request: Request,
    amount: float = Form(...),
    destination: str = Form(...),
):

    user = current_user(
        request
    )

    if not user:

        return RedirectResponse(
            "/login",
            status_code=303,
        )


    amount_decimal = Decimal(
        str(amount)
    )


    with SessionLocal() as db:

        (
            available,
            _,
            _,
            _,
        ) = wallet(
            db,
            user.id,
        )


        if (
            amount_decimal
            < MIN_WITHDRAWAL
        ):

            return RedirectResponse(
                "/wallet?error=Minimum+withdrawal+not+reached",
                status_code=303,
            )


        if (
            amount_decimal
            > available
        ):

            return RedirectResponse(
                "/wallet?error=Insufficient+balance",
                status_code=303,
            )


        withdrawal = Withdrawal(
            user_id=user.id,
            amount=amount_decimal,
            destination=(
                destination.strip()
            ),
            status="pending",
        )

        db.add(
            withdrawal
        )

        db.commit()


    return RedirectResponse(
        "/wallet?success=Withdrawal+submitted",
        status_code=303,
    )


# =========================================================
# SHOPEE CONVERTER
# =========================================================

@app.post(
    "/api/convert"
)
async def convert(
    request: Request,
    url: str = Form(...),
):

    user = current_user(
        request
    )

    if not user:

        return JSONResponse(
            {
                "ok": False,
                "error": "Login required",
            },
            status_code=401,
        )


    if not AFF_ID:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "SHOPEE_AFFILIATE_ID belum dikonfigurasi",
            },
            status_code=400,
        )


    with SessionLocal() as db:

        merchant = (
            db.query(Merchant)
            .filter(
                Merchant.slug
                == "shopee"
            )
            .first()
        )


        if not merchant:

            return JSONResponse(
                {
                    "ok": False,
                    "error":
                        "Shopee merchant configuration missing",
                },
                status_code=500,
            )


        try:

            input_url = extract_url(
                url
            )


            resolved_url = await resolve_shopee(
                input_url
            )


            clean_url = clean_shopee(
                resolved_url
            )


            click_id = (
                "CLK_"
                + secrets.token_urlsafe(
                    10
                )
            )


            sub_id = (
                f"u{user.id}-"
                f"{click_id}-"
                "web"
            )


            affiliate_url = (
                "https://s.shopee.co.id/"
                "an_redir?"
                + urlencode(
                    {
                        "origin_link":
                            clean_url,
                        "affiliate_id":
                            AFF_ID,
                        "sub_id":
                            sub_id,
                    }
                )
            )


            click = Click(
                click_id=click_id,
                user_id=user.id,
                merchant_id=
                    merchant.id,
                source_url=
                    input_url,
                clean_url=
                    clean_url,
                affiliate_url=
                    affiliate_url,
                sub_id=sub_id,
            )


            db.add(
                click
            )

            db.commit()


            return {
                "ok": True,
                "click_id":
                    click_id,
                "sub_id":
                    sub_id,
                "clean_url":
                    clean_url,
                "affiliate_url":
                    affiliate_url,
            }


        except Exception as error:

            return JSONResponse(
                {
                    "ok": False,
                    "error":
                        str(error),
                },
                status_code=400,
            )


# =========================================================
# ADMIN
# =========================================================

@app.get(
    "/admin",
    response_class=HTMLResponse,
)
async def admin(
    request: Request,
    token: str = "",
):

    check_admin(
        token
    )


    with SessionLocal() as db:

        users_count = (
            db.query(User)
            .count()
        )


        clicks_count = (
            db.query(Click)
            .count()
        )


        conversions = (
            db.query(Conversion)
            .order_by(
                Conversion.id.desc()
            )
            .limit(30)
            .all()
        )


        merchants = (
            db.query(Merchant)
            .all()
        )


        withdrawals = (
            db.query(Withdrawal)
            .order_by(
                Withdrawal.id.desc()
            )
            .limit(20)
            .all()
        )


        confirmed = (
            db.query(Conversion)
            .filter(
                Conversion.status
                == "confirmed"
            )
            .all()
        )


        total_commission = sum(
            (
                Decimal(
                    str(
                        conversion
                        .commission_amount
                    )
                )
                for conversion
                in confirmed
            ),
            Decimal("0"),
        )


        total_cashback = sum(
            (
                Decimal(
                    str(
                        conversion
                        .cashback_amount
                    )
                )
                for conversion
                in confirmed
            ),
            Decimal("0"),
        )


        total_revenue = sum(
            (
                Decimal(
                    str(
                        conversion
                        .platform_revenue
                    )
                )
                for conversion
                in confirmed
            ),
            Decimal("0"),
        )


        return templates.TemplateResponse(
            "admin.html",
            {
                "request":
                    request,

                "app_name":
                    APP_NAME,

                "token":
                    token,

                "users":
                    users_count,

                "clicks":
                    clicks_count,

                "conversions":
                    conversions,

                "merchants":
                    merchants,

                "withdrawals":
                    withdrawals,

                "session":
                    info(),

                "total_comm":
                    rupiah(
                        total_commission
                    ),

                "total_cashback":
                    rupiah(
                        total_cashback
                    ),

                "revenue":
                    rupiah(
                        total_revenue
                    ),

                "affiliate_id":
                    AFF_ID
                    or "Not configured",
            },
        )


# =========================================================
# REPORT IMPORT
# =========================================================

@app.post(
    "/admin/import-report"
)
async def admin_import_report(
    token: str = Form(...),
    file: UploadFile = File(...),
):

    check_admin(
        token
    )


    filename = (
        file.filename
        or ""
    )


    allowed = (
        filename
        .lower()
        .endswith(
            (
                ".csv",
                ".xlsx",
                ".xls",
            )
        )
    )


    if not allowed:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "Upload CSV/XLSX report.",
            },
            status_code=400,
        )


    raw = await file.read()


    result = import_report(
        raw,
        filename,
        USER_SHARE,
    )


    if not result.get(
        "ok"
    ):

        return JSONResponse(
            result,
            status_code=400,
        )


    return result


# =========================================================
# ADMIN WITHDRAWALS
# =========================================================

@app.post(
    "/admin/withdrawals/{withdrawal_id}/{action}"
)
def admin_withdrawal(
    withdrawal_id: int,
    action: str,
    token: str = Form(...),
):

    check_admin(
        token
    )


    if action not in [
        "approve",
        "reject",
        "processing",
    ]:

        raise HTTPException(
            400,
            "Invalid action",
        )


    with SessionLocal() as db:

        withdrawal = (
            db.query(Withdrawal)
            .filter(
                Withdrawal.id
                == withdrawal_id
            )
            .first()
        )


        if not withdrawal:

            raise HTTPException(
                404,
                "Withdrawal not found",
            )


        if (
            action == "approve"
            and withdrawal.status
            != "approved"
        ):

            ledger_exists = (
                db.query(Ledger)
                .filter(
                    Ledger.reference
                    == f"WD-{withdrawal.id}",
                    Ledger.entry_type
                    == "withdrawal_debit",
                )
                .first()
            )


            if not ledger_exists:

                db.add(
                    Ledger(
                        user_id=
                            withdrawal.user_id,

                        entry_type=
                            "withdrawal_debit",

                        amount=
                            -Decimal(
                                str(
                                    withdrawal.amount
                                )
                            ),

                        reference=
                            f"WD-{withdrawal.id}",

                        note=
                            "Withdrawal approved",
                    )
                )


            withdrawal.status = (
                "approved"
            )


        elif (
            action
            == "reject"
        ):

            withdrawal.status = (
                "rejected"
            )


        elif (
            action
            == "processing"
        ):

            withdrawal.status = (
                "processing"
            )


        db.commit()


    return RedirectResponse(
        f"/admin?token={token}",
        status_code=303,
    )


# =========================================================
# QR LOGIN WORKER
# =========================================================

async def _qr_login_task(
    job_id: str,
):

    qr_jobs[job_id] = {
        "status":
            "queued",

        "error":
            None,

        "qr_ready":
            False,
    }


    try:

        async with qr_lock:

            result = await run_qr_login(
                job_id,
                qr_jobs,
            )


            qr_jobs[job_id] = {
                "status":
                    "connected",

                "error":
                    None,

                "qr_ready":
                    False,

                "result":
                    result,
            }


    except QRLoginTimeout as error:

        qr_jobs[job_id] = {
            "status":
                "timeout",

            "error":
                str(error),

            "qr_ready":
                False,
        }


    except Exception as error:

        qr_jobs[job_id] = {
            "status":
                "failed",

            "error":
                str(error),

            "qr_ready":
                False,
        }


# =========================================================
# QR START
# =========================================================

@app.post(
    "/admin/affiliate/qr/start"
)
async def start_qr_login(
    token: str = Form(...),
):

    check_admin(
        token
    )


    job_id = secrets.token_urlsafe(
        8
    )


    qr_jobs[job_id] = {
        "status":
            "queued",

        "error":
            None,

        "qr_ready":
            False,
    }


    asyncio.create_task(
        _qr_login_task(
            job_id
        )
    )


    return {
        "ok":
            True,

        "job_id":
            job_id,
    }


# =========================================================
# QR STATUS
# =========================================================

@app.get(
    "/admin/affiliate/qr/status"
)
async def qr_status(
    token: str = "",
    job_id: str = "",
):

    check_admin(
        token
    )


    job = qr_jobs.get(
        job_id
    )


    if not job:

        raise HTTPException(
            404,
            "QR login job not found",
        )


    return {
        "ok":
            True,

        **job,

        "session":
            info(),
    }


# =========================================================
# QR IMAGE
# =========================================================

@app.get(
    "/admin/affiliate/qr/image"
)
async def qr_image(
    token: str = "",
    job_id: str = "",
):

    check_admin(
        token
    )


    job = qr_jobs.get(
        job_id
    )


    if not job:

        raise HTTPException(
            404,
            "QR login job not found",
        )


    path = get_qr_path(
        job_id
    )


    if not path:

        raise HTTPException(
            404,
            "QR belum siap",
        )


    return FileResponse(
        str(path),
        media_type="image/png",
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate",

            "Pragma":
                "no-cache",

            "Expires":
                "0",
        },
    )


# =========================================================
# DISCONNECT SHOPEE SESSION
# =========================================================

@app.post(
    "/admin/session/delete"
)
async def delete_session(
    token: str = Form(...),
):

    check_admin(
        token
    )


    delete_state()


    return RedirectResponse(
        f"/admin?token={token}",
        status_code=303,
    )


# =========================================================
# HEALTH
# =========================================================

@app.get(
    "/health"
)
def health():

    return {
        "ok":
            True,

        "app":
            APP_NAME,

        "affiliate_id_configured":
            bool(AFF_ID),

        "session_configured":
            configured(),
    }
