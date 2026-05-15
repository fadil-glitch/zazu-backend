from fastapi.responses import RedirectResponse, StreamingResponse, Response
import requests as rq
from urllib.parse import urljoin, urlparse
import os
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

app = FastAPI(title="Zazu MVP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/api/user/{user_id}")
@app.get("/api/channels")
def get_channels():
    @app.get("/api/stream/{channel_id}")
async def stream_channel(channel_id: str, segment: str = None):
    """
    Full HLS proxy: serves master playlist or segment, rewriting URLs
    so the client only talks to your Render backend.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = client.table("channel_catalog").select("hls_url").eq("channel_id", channel_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Channel not found")
    hls_url = res.data["hls_url"]

    if segment:
        target_url = urljoin(hls_url, segment)
    else:
        target_url = hls_url

    try:
        upstream = rq.get(target_url, headers={"User-Agent": "ZazuTV/1.0"}, timeout=15)
        if upstream.status_code != 200:
            raise HTTPException(502, f"Upstream returned {upstream.status_code}")
    except rq.RequestException:
        raise HTTPException(502, "Upstream unreachable")

    content = upstream.content
    content_type = upstream.headers.get("Content-Type", "application/vnd.apple.mpegurl")

    if not segment and (target_url.endswith(".m3u8") or target_url.endswith(".m3u")):
        try:
            text = content.decode("utf-8")
            new_lines = []
            for line in text.splitlines():
                sline = line.strip()
                if sline and not sline.startswith("#"):
                    proxy_url = f"/api/stream/{channel_id}?segment={sline}"
                    new_lines.append(proxy_url)
                else:
                    new_lines.append(line)
            content = "\n".join(new_lines).encode("utf-8")
        except Exception:
            pass

    headers = {
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache"
    }
    return Response(content=content, status_code=upstream.status_code, headers=headers)
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = client.table("channel_catalog").select("name, hls_url, logo_url, category").eq("is_active", True).execute()
        return {"channels": res.data}
    except Exception as e:
        return {"channels": [], "error": str(e)}
def get_user(user_id: int):
    """Return a hardcoded wallet with 100 credits for any user (MVP)."""
    return {
        "user_id": user_id,
        "telegram_username": "zazu_user",
        "telegram_first_name": "Tester",
        "balance_kobo": 10000,
        "maintenance_paid_until": None,
        "voice_registered": False
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
