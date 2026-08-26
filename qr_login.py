
import os, asyncio, re
from playwright.async_api import async_playwright
from session_store import save_state

QR_LOGIN_URL=os.getenv(
    "QR_LOGIN_URL",
    "https://shopee.co.id/buyer/login/qr?next=https%3A%2F%2Faffiliate.shopee.co.id%2F"
)
TIMEOUT=int(os.getenv("QR_LOGIN_TIMEOUT","180"))
HEADLESS=os.getenv("HEADLESS","false").lower()=="true"

class QRLoginTimeout(Exception):
    pass

async def run_qr_login():
    """
    Opens the official Shopee QR login page.
    The admin scans the QR in Shopee. No QR content, password, OTP,
    or CAPTCHA is intercepted by the app.
    """
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=HEADLESS)
        context=await browser.new_context(
            locale="id-ID",
            viewport={"width": 1280, "height": 900},
        )
        page=await context.new_page()
        await page.goto(QR_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

        start=asyncio.get_event_loop().time()
        connected=False
        while asyncio.get_event_loop().time()-start < TIMEOUT:
            await page.wait_for_timeout(1200)
            url=page.url.lower()
            if "affiliate.shopee.co.id" in url and "/buyer/login" not in url:
                connected=True
                break

            # Sometimes the successful Shopee login lands on a normal Shopee page
            # before the affiliate redirect completes.
            try:
                body=await page.locator("body").inner_text(timeout=3000)
            except Exception:
                body=""
            if "affiliate.shopee.co.id" in body.lower() and "scan" not in body.lower():
                connected=True
                break

        if not connected:
            await browser.close()
            raise QRLoginTimeout("QR login tidak selesai sebelum timeout.")

        # Navigate to affiliate home to verify the session.
        try:
            await page.goto("https://affiliate.shopee.co.id/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        state=await context.storage_state()

        account_hint=None
        try:
            body=await page.locator("body").inner_text(timeout=5000)
            # Keep only a non-sensitive display hint if visible.
            m=re.search(r'([A-Za-z0-9._-]{3,30})', body)
            if m:
                account_hint=m.group(1)[:30]
        except Exception:
            pass

        save_state(state, {
            "account_hint": account_hint,
            "verified_url": page.url,
        })
        await browser.close()
        return {
            "ok": True,
            "verified_url": page.url,
            "account_hint": account_hint,
        }
