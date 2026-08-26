import os
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright
from session_store import save_state


# =========================================================
# CONFIG
# =========================================================

QR_LOGIN_URL = os.getenv(
    "QR_LOGIN_URL",
    "https://shopee.co.id/buyer/login/qr?"
)

AFFILIATE_URL = (
    "https://affiliate.shopee.co.id/"
)

TIMEOUT = int(
    os.getenv(
        "QR_LOGIN_TIMEOUT",
        "180"
    )
)

QR_DIR = Path(
    "/tmp/cashly_qr"
)

QR_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# =========================================================
# EXCEPTIONS
# =========================================================

class QRLoginTimeout(Exception):
    pass


# =========================================================
# LOGGING
# =========================================================

def log(message: str):
    print(
        f"[QR] {message}",
        flush=True
    )


# =========================================================
# QR LOGIN
# =========================================================

async def run_qr_login(
    job_id: str,
    job_store: dict
):

    qr_path = (
        QR_DIR
        / f"{job_id}.png"
    )

    browser = None

    log(
        f"Job started: {job_id}"
    )

    try:

        # -------------------------------------------------
        # PLAYWRIGHT
        # -------------------------------------------------

        log(
            "Starting Playwright"
        )

        async with async_playwright() as p:

            job_store[job_id][
                "status"
            ] = "opening"

            chromium_path = (
                p.chromium.executable_path
            )

            log(
                "Chromium executable: "
                f"{chromium_path}"
            )

            # -------------------------------------------------
            # LAUNCH CHROMIUM
            # -------------------------------------------------

            log(
                "Launching Chromium"
            )

            browser = await asyncio.wait_for(

                p.chromium.launch(

                    headless=True,

                    chromium_sandbox=False,

                    executable_path=
                        chromium_path,

                    args=[

                        "--no-sandbox",

                        "--disable-setuid-sandbox",

                        "--disable-dev-shm-usage",

                        "--disable-gpu",

                        "--disable-software-rasterizer",

                        "--no-zygote",

                        "--single-process",

                    ],

                ),

                timeout=30,

            )

            log(
                "Chromium launched"
            )

            # -------------------------------------------------
            # BROWSER CONTEXT
            # -------------------------------------------------

            context = await browser.new_context(

                locale="id-ID",

                viewport={
                    "width": 1280,
                    "height": 900,
                },

                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0.0.0 "
                    "Safari/537.36"
                ),

            )

            page = await context.new_page()

            # -------------------------------------------------
            # OPEN SHOPEE
            # -------------------------------------------------

            log(
                "Opening Shopee QR page"
            )

            try:

                response = await page.goto(

                    QR_LOGIN_URL,

                    # IMPORTANT:
                    # jangan tunggu semua JS Shopee selesai
                    wait_until="commit",

                    timeout=20000,

                )

                if response:

                    log(
                        "Shopee HTTP status: "
                        f"{response.status}"
                    )

                else:

                    log(
                        "Shopee navigation returned "
                        "no HTTP response object"
                    )

            except Exception as nav_error:

                log(
                    "Shopee navigation warning: "
                    f"{type(nav_error).__name__}: "
                    f"{nav_error}"
                )

            # -------------------------------------------------
            # CURRENT PAGE
            # -------------------------------------------------

            log(
                "Current Shopee URL: "
                f"{page.url}"
            )

            # beri halaman waktu render QR
            await page.wait_for_timeout(
                5000
            )

            # -------------------------------------------------
            # SCREENSHOT
            # -------------------------------------------------

            log(
                "Taking QR screenshot"
            )

            await page.screenshot(

                path=str(
                    qr_path
                ),

                full_page=True,

            )

            log(
                "QR screenshot saved: "
                f"{qr_path}"
            )

            # frontend sekarang boleh mengambil screenshot
            job_store[job_id][
                "status"
            ] = "waiting_scan"

            job_store[job_id][
                "qr_ready"
            ] = True

            # -------------------------------------------------
            # WAIT FOR QR LOGIN
            # -------------------------------------------------

            log(
                "Waiting for QR scan"
            )

            started = (
                asyncio
                .get_running_loop()
                .time()
            )

            while (
                asyncio
                .get_running_loop()
                .time()
                - started
                < TIMEOUT
            ):

                await page.wait_for_timeout(
                    1500
                )

                current_url = (
                    page.url
                    or ""
                ).lower()

                # ---------------------------------------------
                # LOGIN DETECTION
                # ---------------------------------------------

                if (
                    "affiliate.shopee.co.id"
                    in current_url
                    and
                    "/buyer/login"
                    not in current_url
                ):

                    log(
                        "QR scan detected"
                    )

                    job_store[job_id][
                        "status"
                    ] = "confirming"

                    break

                # ---------------------------------------------
                # REFRESH SCREENSHOT
                # ---------------------------------------------

                try:

                    await page.screenshot(

                        path=str(
                            qr_path
                        ),

                        full_page=True,

                    )

                except Exception as screenshot_error:

                    log(
                        "Screenshot refresh warning: "
                        f"{type(screenshot_error).__name__}: "
                        f"{screenshot_error}"
                    )

            else:

                log(
                    "QR login timeout"
                )

                try:

                    if browser:

                        await browser.close()

                except Exception:
                    pass

                try:

                    qr_path.unlink()

                except Exception:
                    pass

                raise QRLoginTimeout(
                    "QR login tidak selesai "
                    "sebelum timeout."
                )

            # -------------------------------------------------
            # VERIFY AFFILIATE LOGIN
            # -------------------------------------------------

            log(
                "Verifying Affiliate session"
            )

            try:

                verify_response = await page.goto(

                    AFFILIATE_URL,

                    wait_until="commit",

                    timeout=20000,

                )

                if verify_response:

                    log(
                        "Affiliate HTTP status: "
                        f"{verify_response.status}"
                    )

                await page.wait_for_timeout(
                    2500
                )

            except Exception as verify_error:

                log(
                    "Affiliate verify warning: "
                    f"{type(verify_error).__name__}: "
                    f"{verify_error}"
                )

            # -------------------------------------------------
            # VERIFY URL
            # -------------------------------------------------

            verify_url = (
                page.url
                or ""
            )

            log(
                "Verify URL: "
                f"{verify_url}"
            )

            if (
                "buyer/login"
                in verify_url.lower()
            ):

                raise RuntimeError(
                    "Shopee meminta login ulang. "
                    "Session belum berhasil dibuat."
                )

            # -------------------------------------------------
            # SAVE SESSION
            # -------------------------------------------------

            log(
                "Saving encrypted session"
            )

            state = await (
                context.storage_state()
            )

            save_state(

                state,

                {
                    "login_method":
                        "qr",

                    "verified_url":
                        verify_url,
                },

            )

            # -------------------------------------------------
            # CONNECTED
            # -------------------------------------------------

            job_store[job_id][
                "status"
            ] = "connected"

            job_store[job_id][
                "qr_ready"
            ] = False

            log(
                "Shopee session connected"
            )

            # -------------------------------------------------
            # CLEAN QR FILE
            # -------------------------------------------------

            try:

                qr_path.unlink()

            except Exception:
                pass

            # -------------------------------------------------
            # CLOSE BROWSER
            # -------------------------------------------------

            try:

                await browser.close()

            except Exception:
                pass

            return {

                "ok":
                    True,

                "verified_url":
                    verify_url,

            }

    # =====================================================
    # ASYNC TIMEOUT
    # =====================================================

    except asyncio.TimeoutError:

        log(
            "FAILED: Chromium launch "
            "operation timed out"
        )

        try:

            if browser:

                await browser.close()

        except Exception:
            pass

        raise RuntimeError(
            "Chromium launch timeout "
            "di Railway."
        )

    # =====================================================
    # QR TIMEOUT
    # =====================================================

    except QRLoginTimeout:

        raise

    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as error:

        log(
            "FAILED: "
            f"{type(error).__name__}: "
            f"{error}"
        )

        try:

            if browser:

                await browser.close()

        except Exception:
            pass

        raise


# =========================================================
# GET QR SCREENSHOT
# =========================================================

def get_qr_path(
    job_id: str
):

    path = (
        QR_DIR
        / f"{job_id}.png"
    )

    if not path.exists():

        return None

    return path
