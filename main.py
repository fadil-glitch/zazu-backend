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
