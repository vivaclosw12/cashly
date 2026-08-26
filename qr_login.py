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

# Railway harus headless.
HEADLESS = True

QR_DIR = Path("/tmp/cashly_qr")
QR_DIR.mkdir(parents=True, exist_ok=True)


class QRLoginTimeout(Exception):
    pass


async def run_qr_login(job_id: str, job_store: dict):
    """
    Open official Shopee QR login in Playwright.

    Flow:
    - load official Shopee QR page
    - save a screenshot for Admin UI
    - keep browser alive while admin scans
    - detect redirect/login success
    - store authenticated browser session encrypted

    Does not bypass CAPTCHA/OTP and does not extract QR payload.
    """

    qr_path = QR_DIR / f"{job_id}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            locale="id-ID",
            viewport={
                "width": 1280,
                "height": 900,
            },
        )

        page = await context.new_page()

        job_store[job_id]["status"] = "opening"

        await page.goto(
            QR_LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(2500)

        # Screenshot official Shopee page.
        # We are not decoding or intercepting the QR contents.
        await page.screenshot(
            path=str(qr_path),
            full_page=False,
        )

        job_store[job_id]["status"] = "waiting_scan"
        job_store[job_id]["qr_ready"] = True

        started = asyncio.get_running_loop().time()

        while asyncio.get_running_loop().time() - started < TIMEOUT:
            await page.wait_for_timeout(1500)

            current_url = page.url.lower()

            # Successful next= redirect.
            if (
                "affiliate.shopee.co.id" in current_url
                and "/buyer/login" not in current_url
            ):
                job_store[job_id]["status"] = "confirming"
                break

            # Refresh screenshot because QR may expire/change.
            try:
                await page.screenshot(
                    path=str(qr_path),
                    full_page=False,
                )
            except Exception:
                pass

        else:
            await browser.close()

            try:
                qr_path.unlink()
            except Exception:
                pass

            raise QRLoginTimeout(
                "QR login tidak selesai sebelum batas waktu."
            )

        # Verify that the authenticated session can access Affiliate.
        try:
            await page.goto(
                "https://affiliate.shopee.co.id/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        if "buyer/login" in page.url.lower():
            await browser.close()
            raise RuntimeError(
                "Shopee kembali meminta login. Session belum berhasil dibuat."
            )

        state = await context.storage_state()

        # Existing session_store.py encrypts this state.
        save_state(
            state,
            {
                "login_method": "qr",
                "verified_url": page.url,
            },
        )

        job_store[job_id]["status"] = "connected"

        try:
            qr_path.unlink()
        except Exception:
            pass

        await browser.close()

        return {
            "ok": True,
            "verified_url": page.url,
        }


def get_qr_path(job_id: str):
    path = QR_DIR / f"{job_id}.png"

    if not path.exists():
        return None

    return path
