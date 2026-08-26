
import re
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, unquote
import httpx

DROP={"affiliate_id","sub_id","sub_id1","sub_id2","sub_id3","sub_id4","sub_id5",
"utm_source","utm_medium","utm_campaign","utm_content","utm_term","smtt","sp_atk",
"xptdk","uls_trackid","share_channel_code","channel","deep_and_web"}

def extract_url(text):
    m=re.search(r'https?://[^\s<>"\']+',text or "")
    if not m: raise ValueError("URL tidak ditemukan.")
    return m.group(0).rstrip(".,);]")

def is_shopee(host):
    host=(host or "").lower().split(":")[0]
    return host=="shopee.co.id" or host.endswith(".shopee.co.id")

async def resolve_shopee(url):
    if not is_shopee(urlparse(url).hostname): raise ValueError("Hanya link Shopee Indonesia yang didukung.")
    try:
        async with httpx.AsyncClient(follow_redirects=True,timeout=15,headers={"User-Agent":"Mozilla/5.0"}) as c:
            r=await c.get(url)
            final=str(r.url)
            if is_shopee(urlparse(final).hostname): return final
    except Exception: pass
    return url

def clean_shopee(url):
    p=urlparse(url)
    if not is_shopee(p.hostname): raise ValueError("Destination bukan Shopee.")
    params=dict(parse_qsl(p.query,keep_blank_values=True))
    if p.path.endswith("/an_redir") and params.get("origin_link"):
        op=urlparse(unquote(params["origin_link"]))
        if is_shopee(op.hostname): p=op
    pairs=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k.lower() not in DROP]
    return urlunparse(p._replace(scheme="https",query=urlencode(pairs,doseq=True),fragment=""))
