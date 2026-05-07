import hmac
import hashlib

def verify_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
