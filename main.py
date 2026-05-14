import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config, db, africa_callback
import identity_service

app = FastAPI(title="Zazu MVP Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- TELEGRAM AUTH ---
def verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    try:
        params = dict(parse_qsl(init_data))
        received = params.pop("hash", "")
        if not received:
            return False
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

# --- EXISTING ROUTES ---
@app.get("/health")
def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/api/user/{user_id}")
def get_user_endpoint(user_id: int, auth: dict = Depends(get_user_from_auth)):
    if int(auth["id"]) != user_id:
        raise HTTPException(403, "User ID mismatch")
    user = db.get_user(user_id)
    if not user:
        db.create_user_if_new(user_id, auth.get("username", ""), auth.get("first_name", ""))
        user = db.get_user(user_id)
    return user

@app.post("/api/stream/purchase")
def purchase_stream(request: Request, auth: dict = Depends(get_user_from_auth)):
    user_id = int(auth["id"])
    data = request.json()
    idem = data.get("idempotency_key")
    if not idem:
        raise HTTPException(400, "Missing idempotency_key")
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

# ========== IDENTITY LAYER ENDPOINTS (Sprint 0) ==========

@app.get("/api/v2/identity/flags")
async def get_feature_flags():
    flags = {}
    for flag in ["ENABLE_ZKP", "ENABLE_NIN_LINK", "ENABLE_GLOBAL_EIDV", "ENABLE_TON_WALLET"]:
        flags[flag] = await identity_service.is_feature_enabled(flag)
    return {"features": flags}

@app.get("/api/v2/identity/status")
async def get_identity_status(auth: dict = Depends(get_user_from_auth)):
    user_id = int(auth["id"])
    if not await identity_service.is_feature_enabled("ENABLE_ZKP"):
        return {
            "status": "feature_in_beta",
            "message": "Identity verification is coming soon",
            "current_level": "unverified"
        }
    return await identity_service.check_identity_status(user_id)

@app.post("/api/v2/identity/verify/nin-link")
async def verify_nin_link_endpoint(request: Request, auth: dict = Depends(get_user_from_auth)):
    if not await identity_service.is_feature_enabled("ENABLE_ZKP"):
        raise HTTPException(423, "Identity verification is in beta - check back soon")
    user_id = int(auth["id"])
    data = await request.json()
    required = ["nin", "phone", "full_name"]
    if not all(k in data for k in required):
        raise HTTPException(400, f"Missing required fields: {required}")
    if len(data["nin"].strip()) != 11:
        raise HTTPException(400, "NIN must be 11 digits")
    result = await identity_service.verify_nin_link(
        user_id=user_id,
        nin=data["nin"].strip(),
        phone=data["phone"].strip(),
        full_name=data["full_name"].strip()
    )
    status_code = 200 if result["status"] == "verified" else (400 if result["status"] == "failed" else 423)
    return JSONResponse(status_code=status_code, content=result)

@app.post("/api/v2/identity/verify/global")
async def verify_global_eidv_endpoint(request: Request, auth: dict = Depends(get_user_from_auth)):
    if not await identity_service.is_feature_enabled("ENABLE_ZKP"):
        raise HTTPException(423, "Identity verification is in beta - check back soon")
    user_id = int(auth["id"])
    data = await request.json()
    provider = data.get("provider", "").lower()
    if provider not in ["onfido", "jumio"]:
        raise HTTPException(400, "Supported providers: onfido, jumio")
    document_data = data.get("document_data", {})
    if not document_data.get("type") or not document_data.get("country"):
        raise HTTPException(400, "document_data must include 'type' and 'country'")
    result = await identity_service.verify_global_eidv(
        user_id=user_id,
        provider=provider,
        document_data=document_data
    )
    status_code = 200 if result["status"] == "verified" else (400 if result["status"] == "failed" else 423)
    return JSONResponse(status_code=status_code, content=result)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
