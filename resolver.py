import re

from urllib.parse import (
    urlparse,
    parse_qsl,
    urlencode,
    urlunparse,
    unquote,
)

import httpx


# =========================================================
# TRACKING PARAMETERS TO REMOVE
# =========================================================

DROP = {
    "affiliate_id",
    "sub_id",
    "sub_id1",
    "sub_id2",
    "sub_id3",
    "sub_id4",
    "sub_id5",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "smtt",
    "sp_atk",
    "xptdk",
    "uls_trackid",
    "share_channel_code",
    "channel",
    "deep_and_web",
}


# =========================================================
# EXTRACT URL
# =========================================================

def extract_url(text: str) -> str:

    match = re.search(
        r'https?://[^\s<>"\']+',
        text or "",
    )

    if not match:
        raise ValueError(
            "URL tidak ditemukan."
        )

    return match.group(0).rstrip(
        ".,);]"
    )


# =========================================================
# SHOPEE DOMAIN CHECK
# =========================================================

def is_shopee(host: str) -> bool:

    host = (
        host
        or ""
    ).lower().split(":")[0]

    return (
        host == "shopee.co.id"
        or host.endswith(
            ".shopee.co.id"
        )
    )


# =========================================================
# RESOLVE SHOPEE SHORT LINK
# =========================================================

async def resolve_shopee(
    url: str,
) -> str:

    parsed = urlparse(
        url
    )

    if not is_shopee(
        parsed.hostname
    ):
        raise ValueError(
            "Hanya link Shopee Indonesia "
            "yang didukung."
        )

    try:

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15,

            headers={
                "User-Agent":
                    "Mozilla/5.0",
            },

        ) as client:

            response = await client.get(
                url
            )

            final_url = str(
                response.url
            )

            final_parsed = urlparse(
                final_url
            )

            if is_shopee(
                final_parsed.hostname
            ):
                return final_url

    except Exception:
        pass

    return url


# =========================================================
# CLEAN SHOPEE URL
# =========================================================

def clean_shopee(
    url: str,
) -> str:

    parsed = urlparse(
        url
    )

    if not is_shopee(
        parsed.hostname
    ):
        raise ValueError(
            "Destination bukan Shopee."
        )

    params = dict(
        parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
    )

    # -----------------------------------------------------
    # EXISTING AFFILIATE REDIRECT
    # -----------------------------------------------------

    if (
        parsed.path.endswith(
            "/an_redir"
        )
        and params.get(
            "origin_link"
        )
    ):

        origin = urlparse(
            unquote(
                params[
                    "origin_link"
                ]
            )
        )

        if is_shopee(
            origin.hostname
        ):
            parsed = origin

    # -----------------------------------------------------
    # REMOVE OLD TRACKING
    # -----------------------------------------------------

    clean_params = [
        (key, value)

        for key, value
        in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        if key.lower()
        not in DROP
    ]

    # -----------------------------------------------------
    # BUILD CLEAN URL
    # -----------------------------------------------------

    return urlunparse(
        parsed._replace(
            scheme="https",

            query=urlencode(
                clean_params,
                doseq=True,
            ),

            fragment="",
        )
    )
