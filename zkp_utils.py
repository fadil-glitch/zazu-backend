import hashlib
import json
import secrets
from datetime import datetime, timedelta

def generate_salt(length: int = 32) -> str:
    """Generate cryptographically secure salt for ZKP hashing."""
    return secrets.token_hex(length)

def generate_zkp_hash(provider_response: dict, salt: str, user_id: int) -> str:
    """Generate SHA-256 hash of zero-knowledge proof. NEVER store raw identity data."""
    safe_fields = {
        'verified', 'confidence', 'timestamp', 'provider',
        'verification_level', 'country_code', 'expiry_days'
    }
    sanitized = {k: v for k, v in provider_response.items() if k in safe_fields}

    payload = {
        **sanitized,
        'user_id': user_id,
        'salt': salt,
        'generated_at': datetime.utcnow().isoformat()
    }

    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

def verify_zkp_hash(zkp_hash: str, provider_response: dict, salt: str, user_id: int) -> bool:
    """Verify a ZKP hash matches the expected proof."""
    expected = generate_zkp_hash(provider_response, salt, user_id)
    return hashlib.compare_digest(zkp_hash, expected)

def calculate_expiry(verification_level: str, country_code: str) -> datetime:
    """Calculate proof expiry based on verification level and country regulations."""
    expiry_map = {
        ('NG', 'basic'): 365,
        ('NG', 'enhanced'): 365,
        ('NG', 'premium'): 1095,
        ('*', 'basic'): 365,
        ('*', 'enhanced'): 730,
        ('*', 'premium'): 1095,
    }
    days = expiry_map.get((country_code, verification_level), expiry_map[('*', 'basic')])
    return datetime.utcnow() + timedelta(days=days)
