import os
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright
from session_store import save_state


QR_LOGIN_URL = os.getenv(
    "QR_LOGIN_URL",
    "https://shopee.co.id/buyer/login/qr?"
)

AFFILIATE_URL = "https://affiliate.shopee.co.id/"

TIMEOUT = int(
    os.getenv("QR_LOGIN_TIMEOUT", "180")
)

QR_DIR = Path("/tmp/cashly_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


class QRLoginTimeout(Exception):
    pass


def set_stage(job_store, job_id, stage):
    job_store[job_id]["stage"] = stage
    print(f"[QR] {stage}", flush=True)


async def run_qr_login(job_id: str, job_store: dict):

    qr_path = QR_DIR / f"{job_id}.png"

    browser = None

    job_store[job_id]["qr_ready"] = False
    job_store[job_id]["stage"] = "job_started"

    try:

        # =============================================
        # PLAYWRIGHT
        # =============================================

        set_stage(
            job_store,
            job_id,
            "starting_playwright"
        )

        async with async_playwright() as p:

            job_store[job_id]["status"] = "opening"

            chromium_path = p.chromium.executable_path

            job_store[job_id]["chromium_path"] = (
                chromium_path
            )

            # =============================================
            # CHROMIUM
            # =============================================

            set_stage(
                job_store,
                job_id,
                "launching_chromium"
            )

            browser = await asyncio.wait_for(

                p.chromium.launch(

                    headless=True,

                    chromium_sandbox=False,

                    executable_path=chromium_path,

                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-software-rasterizer",
                        "--no-zygote",
                    ],

                ),

                timeout=30,

            )

            set_stage(
                job_store,
                job_id,
                "chromium_launched"
            )

            # =============================================
            # CONTEXT
            # =============================================

            context = await browser.new_context(

                locale="id-ID",

                viewport={
                    "width": 1280,
                    "height": 900,
                },

            )

            page = await context.new_page()

            # =============================================
            # SHOPEE
            # =============================================

            set_stage(
                job_store,
                job_id,
                "opening_shopee"
            )

            try:

                response = await page.goto(

                    QR_LOGIN_URL,

                    wait_until="commit",

                    timeout=15000,

                )

                if response:
                    job_store[job_id]["http_status"] = (
                        response.status
                    )

            except Exception as e:

                # Jangan langsung gagal.
                # Kita tetap coba screenshot halaman yang ada.
                job_store[job_id]["navigation_warning"] = (
                    f"{type(e).__name__}: {e}"
                )

            job_store[job_id]["current_url"] = page.url

            set_stage(
                job_store,
                job_id,
                "waiting_page_render"
            )

            await page.wait_for_timeout(5000)

            # =============================================
            # SCREENSHOT
            # =============================================

            set_stage(
                job_store,
                job_id,
                "taking_screenshot"
            )

            await page.screenshot(

                path=str(qr_path),

                full_page=True,

            )

            if not qr_path.exists():

                raise RuntimeError(
                    "Screenshot file tidak berhasil dibuat."
                )

            job_store[job_id]["qr_ready"] = True
            job_store[job_id]["status"] = "waiting_scan"

            set_stage(
                job_store,
                job_id,
                "qr_ready"
            )

            # =============================================
            # WAIT LOGIN
            # =============================================

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

                await page.wait_for_timeout(1500)

                job_store[job_id]["current_url"] = (
                    page.url
                )

                current_url = (
                    page.url or ""
                ).lower()

                # Kalau login selesai dan masuk affiliate
                if (
                    "affiliate.shopee.co.id"
                    in current_url
                    and
                    "/buyer/login"
                    not in current_url
                ):

                    job_store[job_id]["status"] = (
                        "confirming"
                    )

                    set_stage(
                        job_store,
                        job_id,
                        "login_detected"
                    )

                    break

                # Update screenshot QR
                try:

                    await page.screenshot(
                        path=str(qr_path),
                        full_page=True,
                    )

                except Exception as e:

                    job_store[job_id][
                        "screenshot_warning"
                    ] = str(e)

            else:

                raise QRLoginTimeout(
                    "QR login expired."
                )

            # =============================================
            # VERIFY AFFILIATE
            # =============================================

            set_stage(
                job_store,
                job_id,
                "verifying_affiliate"
            )

            try:

                await page.goto(

                    AFFILIATE_URL,

                    wait_until="commit",

                    timeout=15000,

                )

                await page.wait_for_timeout(
                    2000
                )

            except Exception as e:

                job_store[job_id][
                    "verify_warning"
                ] = str(e)

            verify_url = page.url or ""

            job_store[job_id][
                "verified_url"
            ] = verify_url

            if "buyer/login" in verify_url.lower():

                raise RuntimeError(
                    "Shopee session belum authenticated."
                )

            # =============================================
            # SAVE SESSION
            # =============================================

            set_stage(
                job_store,
                job_id,
                "saving_session"
            )

            state = await context.storage_state()

            save_state(

                state,

                {
                    "login_method": "qr",
                    "verified_url": verify_url,
                },

            )

            job_store[job_id]["status"] = "connected"
            job_store[job_id]["qr_ready"] = False

            set_stage(
                job_store,
                job_id,
                "connected"
            )

            try:
                qr_path.unlink()
            except Exception:
                pass

            await browser.close()

            return {
                "ok": True,
                "verified_url": verify_url,
            }

    except QRLoginTimeout:

        job_store[job_id]["stage"] = (
            "qr_timeout"
        )

        raise

    except asyncio.TimeoutError:

        job_store[job_id]["stage"] = (
            "operation_timeout"
        )

        raise RuntimeError(
            "Browser operation timeout."
        )

    except Exception as e:

        job_store[job_id]["stage"] = (
            "failed"
        )

        job_store[job_id]["worker_error"] = (
            f"{type(e).__name__}: {e}"
        )

        try:
            if browser:
                await browser.close()
        except Exception:
            pass

        raise


def get_qr_path(job_id: str):

    path = QR_DIR / f"{job_id}.png"

    if not path.exists():
        return None

    return path
