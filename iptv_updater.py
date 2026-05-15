import requests
import re
from datetime import datetime
from supabase import create_client
import config

SUPABASE_URL = config.SUPABASE_URL
SUPABASE_KEY = config.SUPABASE_KEY
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_ng_m3u():
    url = "https://iptv-org.github.io/iptv/countries/ng.m3u"
    resp = requests.get(url, timeout=30)
    return resp.text

def parse_m3u(content):
    channels = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            info = lines[i]
            name = re.search(r',(.+)', info).group(1) if ',' in info else "Unknown"
            logo = re.search(r'tvg-logo="([^"]*)"', info)
            logo_url = logo.group(1) if logo else ""
            i += 1
            if i < len(lines) and not lines[i].startswith("#"):
                url = lines[i].strip()
                channels.append({"name": name, "hls_url": url, "logo_url": logo_url})
        i += 1
    return channels

def update_database(channels):
    supabase.table("channel_catalog").update({"is_active": False}).eq("is_active", True).execute()
    for ch in channels:
        supabase.table("channel_catalog").upsert({
            "name": ch["name"],
            "hls_url": ch["hls_url"],
            "logo_url": ch["logo_url"],
            "category": "IPTV",
            "is_active": True,
            "updated_at": datetime.utcnow().isoformat()
        }, on_conflict="name").execute()

if __name__ == "__main__":
    content = fetch_ng_m3u()
    channels = parse_m3u(content)
    update_database(channels)
    print(f"Updated {len(channels)} channels.")
