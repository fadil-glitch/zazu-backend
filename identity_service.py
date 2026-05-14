import logging
import hashlib as hl
from datetime import datetime, timedelta
from typing import Dict, Any
from supabase import create_client, Client
import config
import zkp_utils

logger = logging.getLogger(__name__)
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

async def is_feature_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled."""
    try:
        res = supabase.table("feature_flags").select("enabled")\
            .eq("flag_name", flag_name).maybe_single().execute()
        return bool(res.data and res.data.get("enabled", False))
    except Exception as e:
        logger.error(f"Feature flag check failed: {e}")
        return False

async def get_user_verification_level(user_id: int) -> str:
    """Get user's highest active verification level."""
    try:
        res = supabase.table("identity_proofs").select("verification_level, expires_at")\
            .eq("user_id", user_id)\
            .gte("expires_at", datetime.utcnow().isoformat())\
            .order("verified_at", desc=True)\
            .limit(1).execute()
        if not res.data:
            return "unverified"
        proof = res.data[0]
        if datetime.fromisoformat(proof["expires_at"].replace("Z", "+00:00")) < datetime.utcnow():
            return "unverified"
        return proof["verification_level"]
    except Exception as e:
        logger.error(f"Verification level check failed: {e}")
        return "unverified"

async def verify_nin_link(user_id: int, nin: str, phone: str, full_name: str) -> Dict[str, Any]:
    """Nigerian NIN-Link verification (ZKP flow). MVP Stub."""
    if not await is_feature_enabled("ENABLE_NIN_LINK"):
        return {"status": "feature_disabled", "message": "NIN-Link verification is in beta"}

    mock_verification = {
        "verified": True,
        "confidence": 0.95,
        "name_match": 0.92,
        "phone_match": True,
        "timestamp": datetime.utcnow().isoformat(),
        "provider": "NIMC",
        "verification_level": "enhanced",
        "country_code": "NG",
        "expiry_days": 365
    }

    salt = zkp_utils.generate_salt()
    zkp_hash = zkp_utils.generate_zkp_hash(mock_verification, salt, user_id)

    try:
        proof_data = {
            "user_id": user_id,
            "proof_type": "nin_link",
            "zkp_hash": zkp_hash,
            "verification_level": mock_verification["verification_level"],
            "country_code": mock_verification["country_code"],
            "verified_at": datetime.utcnow().isoformat(),
            "expires_at": zkp_utils.calculate_expiry(
                mock_verification["verification_level"],
                mock_verification["country_code"]
            ).isoformat(),
            "metadata": {
                "name_match_score": mock_verification["name_match"],
                "phone_verified": mock_verification["phone_match"],
                "salt_hash": hl.sha256(salt.encode()).hexdigest()
            }
        }

        supabase.table("identity_proofs").upsert(
            proof_data, on_conflict="user_id,proof_type"
        ).execute()

        supabase.table("identity_events").insert({
            "user_id": user_id,
            "event_type": "nin_link_verification",
            "provider": "NIMC",
            "status": "verified",
            "zkp_hash": zkp_hash
        }).execute()

        return {
            "status": "verified",
            "verification_level": mock_verification["verification_level"],
            "expires_at": proof_data["expires_at"],
            "message": "Identity verified successfully"
        }
    except Exception as e:
        logger.error(f"NIN-Link verification failed: {e}")
        return {"status": "failed", "message": "Verification service temporarily unavailable"}

async def verify_global_eidv(user_id: int, provider: str, document_data: Dict[str, Any]) -> Dict[str, Any]:
    """Global eIDV verification with ZKP. MVP Stub."""
    if not await is_feature_enabled("ENABLE_GLOBAL_EIDV"):
        return {"status": "feature_disabled", "message": "Global eIDV is in beta"}

    if provider not in ["onfido", "jumio"]:
        return {"status": "error", "message": "Unsupported provider"}

    mock_verification = {
        "verified": True,
        "confidence": 0.98,
        "doc_type": document_data.get("type", "passport"),
        "country": document_data.get("country", "US"),
        "timestamp": datetime.utcnow().isoformat(),
        "provider": provider.upper(),
        "verification_level": "premium",
        "expiry_days": 730
    }

    salt = zkp_utils.generate_salt()
    zkp_hash = zkp_utils.generate_zkp_hash(mock_verification, salt, user_id)

    try:
        proof_data = {
            "user_id": user_id,
            "proof_type": provider.lower(),
            "zkp_hash": zkp_hash,
            "verification_level": mock_verification["verification_level"],
            "country_code": mock_verification["country"],
            "verified_at": datetime.utcnow().isoformat(),
            "expires_at": zkp_utils.calculate_expiry(
                mock_verification["verification_level"],
                mock_verification["country"]
            ).isoformat(),
            "metadata": {
                "doc_type": mock_verification["doc_type"],
                "confidence_score": mock_verification["confidence"],
                "salt_hash": hl.sha256(salt.encode()).hexdigest()
            }
        }

        supabase.table("identity_proofs").upsert(
            proof_data, on_conflict="user_id,proof_type"
        ).execute()

        supabase.table("identity_events").insert({
            "user_id": user_id,
            "event_type": f"{provider}_verification",
            "provider": provider.upper(),
            "status": "verified",
            "zkp_hash": zkp_hash
        }).execute()

        return {
            "status": "verified",
            "verification_level": mock_verification["verification_level"],
            "expires_at": proof_data["expires_at"],
            "message": "Identity verified successfully"
        }
    except Exception as e:
        logger.error(f"{provider.upper()} verification failed: {e}")
        return {"status": "failed", "message": "Verification service temporarily unavailable"}

async def check_identity_status(user_id: int) -> Dict[str, Any]:
    """Check user's identity verification status and capabilities."""
    level = await get_user_verification_level(user_id)

    proofs_res = supabase.table("identity_proofs").select("proof_type, verification_level, expires_at")\
        .eq("user_id", user_id)\
        .gte("expires_at", datetime.utcnow().isoformat())\
        .execute()

    active_proofs = [
        {"type": p["proof_type"], "level": p["verification_level"], "expires_at": p["expires_at"]}
        for p in (proofs_res.data or [])
    ]

    return {
        "user_id": user_id,
        "verification_level": level,
        "active_proofs": active_proofs,
        "capabilities": {
            "can_access_premium": level in ["enhanced", "premium"],
            "can_withdraw_high": level == "premium",
            "nin_link_available": await is_feature_enabled("ENABLE_NIN_LINK"),
            "global_eidv_available": await is_feature_enabled("ENABLE_GLOBAL_EIDV")
        }
    }
