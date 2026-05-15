import os
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse, Response
import requests as rq
from urllib.parse import urljoin, urlparse
from supabase import create_client

# --- APP INIT ---
app = FastAPI(title="Zazu MVP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- CONFIG ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://eqintnfuyquhscxwudzr.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVxaW50bmZ1eXF1aHNjeHd1ZHpyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1MzE4NTQsImV4cCI6MjA5NDEwNzg1NH0.rW7IJ3G7BkuLi1YnB_Q1W4y2ghi-UwKEzoo23oFSe70")

# --- ROUTES ---

@app.get("/health")
def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/api/user/{user_id}")
def get_user(user_id: int):
    return {
        "user_id": user_id,
        "telegram_username": "zazu_user",
        "telegram_first_name": "Tester",
        "balance_kobo": 10000,
        "maintenance_paid_until": None,
        "voice_registered": False
    }

@app.get("/api/channels")
def get_channels():
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = client.table("channel_catalog").select("channel_id, name, category, logo_url").eq("is_active", True).execute()
        return {"channels": res.data}
    except Exception as e:
        return {"channels": [], "error": str(e)}

@app.get("/api/stream/{channel_id}")
async def stream_channel(channel_id: str, segment: str = None):
    """
    Full HLS proxy with nested path resolution.
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

    if ".m3u8" in content_type or ".m3u" in content_type or target_url.endswith(".m3u8") or target_url.endswith(".m3u"):
        try:
            text = content.decode("utf-8")
            new_lines = []
            for line in text.splitlines():
                sline = line.strip()
                if sline and not sline.startswith("#"):
                    absolute_uri = urljoin(target_url, sline)
                    relative_to_master = absolute_uri.replace(hls_url.rstrip("/") + "/", "")
                    if relative_to_master == absolute_uri:
                        new_lines.append(absolute_uri)
                    else:
                        new_url = f"/api/stream/{channel_id}?segment={relative_to_master}"
                        new_lines.append(new_url)
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
