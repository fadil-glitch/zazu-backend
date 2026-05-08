import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

import config, db, africa_callback

app = FastAPI(title="Zazu MVP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- TELEGRAM AUTH ---
def verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    try:
        params = dict(parse_qsl(init_data))
        received = params.pop("hash", "")
        if not received: return False
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = hashlib.sha256(bot_token.encode()).digest()
        expected = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)
    except Exception:
        return False

def get_user_from_auth(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Telegram auth")
    raw = auth.split(" ", 1)[1]
    if not verify_telegram_init_data(raw, config.BOT_TOKEN):
        raise HTTPException(401, "Invalid auth signature")
    params = dict(parse_qsl(raw))
    return json.loads(params.get("user", "{}"))

# --- VAT SPLIT ---
def calc_split(gross_kobo: int) -> dict:
    vat = int(Decimal(str(gross_kobo)) * Decimal("0.075").quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    net = gross_kobo - vat
    creator = int(Decimal(str(net)) * Decimal("0.60").quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    return {"gross_kobo": gross_kobo, "vat_kobo": vat, "net_kobo": net, "creator_kobo": creator, "platform_kobo": net - creator}

# --- ROUTES ---
@app.get("/health")
def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/api/user/{user_id}")
def get_user_endpoint(user_id: int, auth: dict = Depends(get_user_from_auth)):
    if int(auth["id"]) != user_id:
        raise HTTPException(403, "User ID mismatch")
    user = db.get_user(user_id)
    if not user: raise HTTPException(404, "User not found")
    return user

@app.post("/api/stream/purchase")
def purchase_stream(request: Request, auth: dict = Depends(get_user_from_auth)):
    user_id = int(auth["id"])
    data = request.json()
    idem = data.get("idempotency_key")
    if not idem: raise HTTPException(400, "Missing idempotency_key")
    
    existing = db.client.table("transactions").select("id").eq("idempotency_key", idem).maybe_single().execute()
    if existing.data:
        return {"success": True, "status": "duplicate"}

    if not db.deduct_credits(user_id, config.PREMIUM_COST_KOBO):
        raise HTTPException(402, "Insufficient balance")

    split = calc_split(config.PREMIUM_COST_KOBO)
    db.client.table("transactions").insert({
        "user_id": user_id, "type": "debit", "amount_kobo": config.PREMIUM_COST_KOBO,
        "description": "Stream purchase", "idempotency_key": idem, "metadata": split
    }).execute()
    return {"success": True, "breakdown": split}

@app.post("/api/sacrifice/topup")
def sacrifice_topup(request: Request, auth: dict = Depends(get_user_from_auth)):
    return {"status": "pending", "user_id": auth["id"], "msg": "Submitted for admin review"}

@app.post("/payment/callback")
def africa_webhook(request: Request):
    body_bytes = request.body()
    sig = request.headers.get("X-Africa-Signature")
    if not africa_callback.verify_signature(body_bytes, sig, config.WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid signature")
    form = request.form()
    return {"status": "received", "phone": form.get("phoneNumber")}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
