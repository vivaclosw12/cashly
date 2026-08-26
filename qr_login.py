import os
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright
from session_store import save_state

QR_LOGIN_URL = os.getenv(
    "QR_LOGIN_URL",
    "https://shopee.co.id/buyer/login/qr?next=https%3A%2F%2Faffiliate.shopee.co.id%2F"
)

TIMEOUT = int(os.getenv("QR_LOGIN_TIMEOUT", "180"))

QR_DIR = Path("/tmp/cashly_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


class QRLoginTimeout(Exception):
    pass


def log(message):
    print(f"[QR] {message}", flush=True)


async def run_qr_login(job_id: str, job_store: dict):
    qr_path = QR_DIR / f"{job_id}.png"

    log(f"Job started: {job_id}")

    try:
        log("Starting Playwright")

        async with async_playwright() as p:

            job_store[job_id]["status"] = "opening"

            log("Launching Chromium")

            browser = await asyncio.wait_for(
                p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                ),
                timeout=30,
            )

            log("Chromium launched")

            context = await browser.new_context(
                locale="id-ID",
                viewport={
                    "width": 1280,
                    "height": 900,
                },
            )

            page = await context.new_page()

            log("Opening Shopee QR page")

            await asyncio.wait_for(
                page.goto(
                    QR_LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=45000,
                ),
                timeout=50,
            )

            log(f"Shopee page loaded: {page.url}")

            await page.wait_for_timeout(2500)

            log("Taking QR screenshot")

            await page.screenshot(
                path=str(qr_path),
                full_page=False,
            )

            log(f"QR screenshot saved: {qr_path}")

            job_store[job_id]["status"] = "waiting_scan"
            job_store[job_id]["qr_ready"] = True

            started = asyncio.get_running_loop().time()

            while (
                asyncio.get_running_loop().time() - started
                < TIMEOUT
            ):
                await page.wait_for_timeout(1500)

                current_url = page.url.lower()

                if (
                    "affiliate.shopee.co.id" in current_url
                    and "/buyer/login" not in current_url
                ):
                    log("QR scan detected")
                    job_store[job_id]["status"] = "confirming"
                    break

                # refresh screenshot in case QR changes
                try:
                    await page.screenshot(
                        path=str(qr_path),
                        full_page=False,
                    )
                except Exception as screenshot_error:
                    log(
                        f"Screenshot refresh warning: "
                        f"{screenshot_error}"
                    )

            else:
                log("QR login timeout")

                await browser.close()

                try:
                    qr_path.unlink()
                except Exception:
                    pass

                raise QRLoginTimeout(
                    "QR login tidak selesai sebelum timeout."
                )

            log("Verifying Affiliate session")

            try:
                await page.goto(
                    "https://affiliate.shopee.co.id/",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                await page.wait_for_timeout(1800)

            except Exception as verify_error:
                log(
                    f"Affiliate verify navigation warning: "
                    f"{verify_error}"
                )

            log(f"Verify URL: {page.url}")

            if "buyer/login" in page.url.lower():
                await browser.close()

                raise RuntimeError(
                    "Shopee meminta login ulang. "
                    "Session belum berhasil dibuat."
                )

            log("Saving encrypted session")

            state = await context.storage_state()

            save_state(
                state,
                {
                    "login_method": "qr",
                    "verified_url": page.url,
                },
            )

            job_store[job_id]["status"] = "connected"

            log("Shopee session connected")

            try:
                qr_path.unlink()
            except Exception:
                pass

            await browser.close()

            return {
                "ok": True,
                "verified_url": page.url,
            }

    except Exception as e:
        log(
            f"FAILED: {type(e).__name__}: {e}"
        )
        raise


def get_qr_path(job_id: str):
    path = QR_DIR / f"{job_id}.png"

    if not path.exists():
        return None

    return path
