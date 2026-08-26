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

        async with async_playwright() as p:

            job_store[job_id]["status"] = "opening"

            set_stage(
                job_store,
                job_id,
                "launching_chromium"
            )

            browser = await asyncio.wait_for(

                p.chromium.launch(
                    headless=True,

                    # new headless Chromium mode
                    channel="chromium",

                    chromium_sandbox=False,

                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                ),

                timeout=30,
            )

            set_stage(
                job_store,
                job_id,
                "chromium_launched"
            )


            context = await browser.new_context(
                locale="id-ID",

                viewport={
                    "width": 1280,
                    "height": 900,
                },
            )

            page = await context.new_page()


            # -------------------------------------------
            # OPEN SHOPEE
            # -------------------------------------------

            set_stage(
                job_store,
                job_id,
                "opening_shopee"
            )

            try:

                response = await page.goto(
                    QR_LOGIN_URL,
                    wait_until="commit",
                    timeout=20000,
                )

                if response:
                    job_store[job_id]["http_status"] = (
                        response.status
                    )

            except Exception as nav_error:

                job_store[job_id]["navigation_warning"] = (
                    f"{type(nav_error).__name__}: "
                    f"{nav_error}"
                )


            job_store[job_id]["current_url"] = (
                page.url
            )


            set_stage(
                job_store,
                job_id,
                "waiting_render"
            )

            # beri JS Shopee waktu render
            await page.wait_for_timeout(
                8000
            )


            # -------------------------------------------
            # DIAGNOSTIC
            # -------------------------------------------

            try:

                title = await page.title()

                job_store[job_id]["page_title"] = (
                    title
                )

            except Exception:
                pass


            try:

                job_store[job_id]["canvas_count"] = (
                    await page.locator(
                        "canvas"
                    ).count()
                )

                job_store[job_id]["image_count"] = (
                    await page.locator(
                        "img"
                    ).count()
                )

            except Exception:
                pass


            # -------------------------------------------
            # SCREENSHOT
            # -------------------------------------------

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
                    "Screenshot tidak berhasil dibuat."
                )


            job_store[job_id]["qr_ready"] = True
            job_store[job_id]["status"] = "waiting_scan"


            set_stage(
                job_store,
                job_id,
                "qr_ready"
            )


            # -------------------------------------------
            # WAIT FOR LOGIN
            # -------------------------------------------

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
                )

                job_store[job_id]["current_url"] = (
                    current_url
                )


                if (
                    "affiliate.shopee.co.id"
                    in current_url.lower()
                    and
                    "/buyer/login"
                    not in current_url.lower()
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


                try:

                    await page.screenshot(
                        path=str(qr_path),
                        full_page=True,
                    )

                except Exception as screenshot_error:

                    job_store[job_id][
                        "screenshot_warning"
                    ] = str(
                        screenshot_error
                    )

            else:

                raise QRLoginTimeout(
                    "QR login expired."
                )


            # -------------------------------------------
            # VERIFY AFFILIATE
            # -------------------------------------------

            set_stage(
                job_store,
                job_id,
                "verifying_affiliate"
            )

            try:

                await page.goto(
                    AFFILIATE_URL,
                    wait_until="commit",
                    timeout=20000,
                )

                await page.wait_for_timeout(
                    2500
                )

            except Exception as verify_error:

                job_store[job_id][
                    "verify_warning"
                ] = str(
                    verify_error
                )


            verify_url = (
                page.url
                or ""
            )


            if (
                "/buyer/login"
                in verify_url.lower()
            ):

                raise RuntimeError(
                    "Shopee session belum authenticated."
                )


            # -------------------------------------------
            # SAVE SESSION
            # -------------------------------------------

            set_stage(
                job_store,
                job_id,
                "saving_session"
            )

            state = await context.storage_state()


            save_state(
                state,
                {
                    "login_method":
                        "qr",

                    "verified_url":
                        verify_url,
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
            "Chromium operation timeout."
        )


    except Exception as error:

        job_store[job_id]["stage"] = (
            "failed"
        )

        job_store[job_id]["worker_error"] = (
            f"{type(error).__name__}: "
            f"{error}"
        )


        try:
            if browser:
                await browser.close()

        except Exception:
            pass


        raise


def get_qr_path(job_id: str):

    path = (
        QR_DIR
        / f"{job_id}.png"
    )

    if not path.exists():
        return None

    return path
