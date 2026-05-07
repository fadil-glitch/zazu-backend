from supabase import create_client, Client
import config

client: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

def get_user(user_id: int):
    res = client.table("users").select("*").eq("user_id", user_id).maybe_single().execute()
    return res.data

def create_user_if_new(user_id: int, username: str = "", first_name: str = ""):
    if get_user(user_id):
        return False
    client.table("users").insert({
        "user_id": user_id,
        "telegram_username": username,
        "telegram_first_name": first_name,
        "balance_kobo": config.WELCOME_BONUS_KOBO,
        "voice_registered": False
    }).execute()
    return True

def deduct_credits(user_id: int, amount: int):
    user = get_user(user_id)
    if not user or user["balance_kobo"] < amount:
        return False
    client.table("users").update({"balance_kobo": user["balance_kobo"] - amount}).eq("user_id", user_id).execute()
    return True

def add_credits(user_id: int, amount: int):
    user = get_user(user_id)
    if not user:
        return False
    client.table("users").update({"balance_kobo": user["balance_kobo"] + amount}).eq("user_id", user_id).execute()
    return True
