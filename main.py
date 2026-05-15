import os
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, Response
import requests as rq
from urllib.parse import urljoin
from supabase import create_client

app = FastAPI(title="Zazu MVP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://eqintnfuyquhscxwudzr.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVxaW50bmZ1eXF1aHNjeHd1ZHpyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1MzE4NTQsImV4cCI6MjA5NDEwNzg1NH0.rW7IJ3G7BkuLi1YnB_Q1W4y2ghi-UwKEzoo23oFSe70")

# ---------- API ROUTES ----------
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
        res = client.table("channel_catalog").select("channel_id, name, category, logo_url, hls_url").eq("is_active", True).execute()
        channels = []
        for ch in res.data:
            fmt = "mp4" if ch["hls_url"].endswith(".mp4") else "hls"
            channels.append({
                "channel_id": ch["channel_id"],
                "name": ch["name"],
                "category": ch.get("category", ""),
                "logo_url": ch.get("logo_url", ""),
                "format": fmt
            })
        return {"channels": channels}
    except Exception as e:
        return {"channels": [], "error": str(e)}

@app.get("/api/stream/{channel_id}")
async def stream_channel(channel_id: str, segment: str = None):
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = client.table("channel_catalog").select("hls_url").eq("channel_id", channel_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Channel not found")
    hls_url = res.data["hls_url"]

    if hls_url.endswith(".mp4"):
        try:
            r = rq.get(hls_url, headers={"User-Agent": "ZazuTV/1.0"}, stream=True)
            if r.status_code != 200:
                raise HTTPException(502, "Upstream MP4 unavailable")
            return StreamingResponse(
                r.iter_content(chunk_size=1024*1024),
                status_code=200,
                media_type="video/mp4",
                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
            )
        except rq.RequestException:
            raise HTTPException(502, "Upstream MP4 unreachable")

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
                        new_lines.append(f"/api/stream/{channel_id}?segment={relative_to_master}")
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

# ---------- MINI APP (served directly by Render) ----------
MINI_APP_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Zazu Media</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<style>
body { margin:0; background:#0a0a0f; color:#fff; font-family:system-ui; padding:16px; }
h2 { text-align:center; }
.bal { font-size:42px; font-weight:800; text-align:center; margin:20px 0; color:#00cec9; }
button { width:100%; padding:14px; margin:8px 0; border:none; border-radius:12px; font-size:16px; font-weight:600; cursor:pointer; }
.primary { background:#6c5ce7; color:#fff; }
.text-btn { background:none; color:#00cec9; }
.hidden { display: none !important; }
.player-box { position:relative; width:100%; aspect-ratio:16/9; background:#000; border-radius:12px; overflow:hidden; margin:16px 0; }
video { width:100%; height:100%; object-fit:contain; display:block; background:black; }
.watermark { position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none; font-family:monospace; font-size:14px; color:rgba(255,255,255,0.25); white-space:nowrap; animation:drift 22s linear infinite; z-index:10; }
@keyframes drift { 0%{transform:translate(-100%,-100%)} 25%{transform:translate(0,0)} 50%{transform:translate(100%,100%)} 75%{transform:translate(0,200%)} 100%{transform:translate(-100%,100%)} }
.info { text-align:center; font-size:13px; opacity:0.7; margin-bottom:8px; }
#channel-list { margin-top:8px; }
.section-title { text-align:center; margin-top:24px; margin-bottom:8px; font-weight:bold; opacity:0.8; }
</style>
</head>
<body>
<div id="wallet-screen">
  <h2>💰 Your Wallet</h2>
  <div class="bal">₦<span id="bal-val">0.00</span></div>
  <div class="section-title">Live Channels</div>
  <div id="channel-list"><p style="text-align:center;opacity:0.6;">Loading channels...</p></div>
</div>
<div id="player-screen" class="hidden">
  <div class="player-box">
    <video id="vid" controls playsinline disablepictureinpicture controlsList="nodownload"></video>
    <div id="wm" class="watermark"></div>
  </div>
  <p class="info">Forensic watermark active</p>
  <button class="text-btn" onclick="closePlayer()">← Back to Wallet</button>
</div>
<script>
const tg = window.Telegram.WebApp;
tg.expand(); tg.enableClosingConfirmation();
const API = window.location.origin;

function loadWallet(){
  const balEl = document.getElementById('bal-val');
  balEl.textContent = "0.00";
  const u = tg.initDataUnsafe?.user;
  if(!u) return;
  fetch(API + '/api/user/' + u.id + '?t=' + Date.now())
    .then(r => r.ok ? r.json() : null)
    .then(data => { if(data && data.balance_kobo) balEl.textContent = (data.balance_kobo/100).toFixed(2); })
    .catch(() => {});
}
function loadChannels(){
  const container = document.getElementById('channel-list');
  fetch(API + '/api/channels?t=' + Date.now())
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      const channels = (data && data.channels) || [];
      container.innerHTML = '';
      if(!channels.length){ container.innerHTML = '<p style="text-align:center;opacity:0.6;">No channels yet.</p>'; return; }
      channels.forEach(ch => {
        const btn = document.createElement('button');
        btn.className = 'primary';
        btn.textContent = '📺 ' + ch.name;
        const streamUrl = API + '/api/stream/' + ch.channel_id;
        if(ch.format === 'mp4'){
          btn.onclick = () => playMp4(streamUrl);
        } else {
          btn.onclick = () => playHls(streamUrl);
        }
        container.appendChild(btn);
      });
    })
    .catch(() => { container.innerHTML = '<p style="text-align:center;opacity:0.6;">Failed to load channels.</p>'; });
}
let hls = null;
function show(id){
  document.getElementById('wallet-screen').classList.add('hidden');
  document.getElementById('player-screen').classList.add('hidden');
  document.getElementById(id).classList.remove('hidden');
}
function playMp4(url){
  show('player-screen');
  const vid = document.getElementById('vid');
  const wm = document.getElementById('wm');
  const updateWm = () => { wm.textContent = 'ZAZU:' + (tg.initDataUnsafe?.user?.id || 'unknown') + '|' + new Date().toLocaleTimeString() + ' '; };
  updateWm(); setInterval(updateWm, 1500);
  if(hls){ hls.destroy(); hls = null; }
  vid.src = url;
  vid.play().catch(() => {});
}
function playHls(url){
  show('player-screen');
  const vid = document.getElementById('vid');
  const wm = document.getElementById('wm');
  const updateWm = () => { wm.textContent = 'ZAZU:' + (tg.initDataUnsafe?.user?.id || 'unknown') + '|' + new Date().toLocaleTimeString() + ' '; };
  updateWm(); setInterval(updateWm, 1500);
  if(hls){ hls.destroy(); hls = null; }
  if(Hls.isSupported()){
    hls = new Hls({ enableWorker: true, lowLatencyMode: false });
    hls.loadSource(url);
    hls.attachMedia(vid);
    hls.on(Hls.Events.MANIFEST_PARSED, () => vid.play().catch(() => {}));
  } else if(vid.canPlayType('application/vnd.apple.mpegurl')){
    vid.src = url;
    vid.play().catch(() => {});
  }
}
function closePlayer(){
  if(hls){ hls.destroy(); hls = null; }
  const vid = document.getElementById('vid');
  vid.src = '';
  vid.removeAttribute('src');
  show('wallet-screen');
}
loadWallet();
loadChannels();
</script>
</body>
</html>
"""

@app.get("/mini-app", response_class=HTMLResponse)
def serve_mini_app():
    return HTMLResponse(content=MINI_APP_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
