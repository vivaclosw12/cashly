import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://shopee.co.id/buyer/login/qr?"

OUTPUT = Path("/tmp/shopee_qr_probe.png")


def log(message):
    print(
        f"[QR-PROBE] {message}",
        flush=True,
    )


async def main():

    log("Starting Playwright")

    async with async_playwright() as p:

        # ================================================
        # BROWSER INFO
        # ================================================

        log(
            f"Default executable: "
            f"{p.chromium.executable_path}"
        )

        # ================================================
        # LAUNCH
        # ================================================

        log(
            "Launching Chromium new-headless..."
        )

        try:

            browser = await asyncio.wait_for(

                p.chromium.launch(

                    headless=True,

                    # Playwright Chromium channel
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

        except Exception as error:

            log(
                "LAUNCH FAILED: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            return

        log("Chromium launched")

        # ================================================
        # CONTEXT
        # ================================================

        context = await browser.new_context(

            locale="id-ID",

            viewport={
                "width": 1280,
                "height": 900,
            },

        )

        page = await context.new_page()

        # ================================================
        # PAGE EVENTS
        # ================================================

        page.on(
            "console",
            lambda msg:
                log(
                    f"BROWSER CONSOLE "
                    f"[{msg.type}]: "
                    f"{msg.text}"
                )
        )

        page.on(
            "pageerror",
            lambda error:
                log(
                    f"PAGE ERROR: {error}"
                )
        )

        page.on(
            "requestfailed",
            lambda request:
                log(
                    "REQUEST FAILED: "
                    f"{request.url} "
                    f"| "
                    f"{request.failure}"
                )
        )

        # ================================================
        # NAVIGATION
        # ================================================

        log(
            f"Opening: {URL}"
        )

        response = None

        try:

            response = await page.goto(

                URL,

                # Jangan tunggu semua JS selesai.
                wait_until="commit",

                timeout=20000,

            )

            if response:

                log(
                    "Navigation HTTP status: "
                    f"{response.status}"
                )

            else:

                log(
                    "Navigation returned "
                    "no response object"
                )

        except Exception as error:

            log(
                "NAVIGATION WARNING: "
                f"{type(error).__name__}: "
                f"{error}"
            )

        # ================================================
        # BASIC PAGE STATE
        # ================================================

        log(
            f"Current URL: {page.url}"
        )

        try:

            title = await page.title()

            log(
                f"Title: {title!r}"
            )

        except Exception as error:

            log(
                "TITLE ERROR: "
                f"{error}"
            )

        # ================================================
        # WAIT FOR SHOPEE JS
        # ================================================

        log(
            "Waiting 8 seconds for page render..."
        )

        await page.wait_for_timeout(
            8000
        )

        # ================================================
        # DOM DIAGNOSTICS
        # ================================================

        try:

            body_text = await page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            preview = (
                body_text[:1000]
                .replace("\n", " | ")
            )

            log(
                "BODY PREVIEW: "
                f"{preview}"
            )

        except Exception as error:

            log(
                "BODY READ ERROR: "
                f"{type(error).__name__}: "
                f"{error}"
            )

        # ================================================
        # ELEMENT COUNTS
        # ================================================

        selectors = [
            "canvas",
            "img",
            "svg",
            "iframe",
            "input",
            "button",
        ]

        for selector in selectors:

            try:

                count = await page.locator(
                    selector
                ).count()

                log(
                    f"{selector}: {count}"
                )

            except Exception as error:

                log(
                    f"{selector} COUNT ERROR: "
                    f"{error}"
                )

        # ================================================
        # VISIBLE CANVAS
        # ================================================

        try:

            canvases = page.locator(
                "canvas"
            )

            canvas_count = await canvases.count()

            for i in range(canvas_count):

                canvas = canvases.nth(i)

                try:

                    visible = await canvas.is_visible()

                    box = await canvas.bounding_box()

                    log(
                        f"CANVAS #{i}: "
                        f"visible={visible} "
                        f"box={box}"
                    )

                except Exception as error:

                    log(
                        f"CANVAS #{i} ERROR: "
                        f"{error}"
                    )

        except Exception as error:

            log(
                f"CANVAS INSPECTION ERROR: "
                f"{error}"
            )

        # ================================================
        # VISIBLE IMAGES
        # ================================================

        try:

            images = page.locator(
                "img"
            )

            image_count = await images.count()

            for i in range(
                min(image_count, 30)
            ):

                image = images.nth(i)

                try:

                    visible = await image.is_visible()

                    box = await image.bounding_box()

                    src = await image.get_attribute(
                        "src"
                    )

                    log(
                        f"IMG #{i}: "
                        f"visible={visible} "
                        f"box={box} "
                        f"src={str(src)[:150]}"
                    )

                except Exception as error:

                    log(
                        f"IMG #{i} ERROR: "
                        f"{error}"
                    )

        except Exception as error:

            log(
                f"IMAGE INSPECTION ERROR: "
                f"{error}"
            )

        # ================================================
        # SCREENSHOT
        # ================================================

        log(
            "Taking full-page screenshot..."
        )

        try:

            await page.screenshot(

                path=str(OUTPUT),

                full_page=True,

            )

            log(
                f"SCREENSHOT SAVED: "
                f"{OUTPUT}"
            )

        except Exception as error:

            log(
                "SCREENSHOT FAILED: "
                f"{type(error).__name__}: "
                f"{error}"
            )

        # ================================================
        # FINAL STATE
        # ================================================

        log(
            f"FINAL URL: {page.url}"
        )

        log(
            "Probe completed"
        )

        await browser.close()


if __name__ == "__main__":

    asyncio.run(
        main()
    )
