@app.get("/api/stream/{channel_id}")
async def stream_channel(channel_id: str, segment: str = None):
    """
    Full HLS proxy with nested path resolution.
    Handles master playlists, variant playlists, and .ts segments correctly.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = client.table("channel_catalog").select("hls_url").eq("channel_id", channel_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Channel not found")
    hls_url = res.data["hls_url"]

    if segment:
        # Build the full URL by resolving relative to the master URL
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

    # Rewrite if it's any kind of playlist (master or variant)
    if ".m3u8" in content_type or ".m3u" in content_type or target_url.endswith(".m3u8") or target_url.endswith(".m3u"):
        try:
            text = content.decode("utf-8")
            new_lines = []
            for line in text.splitlines():
                sline = line.strip()
                if sline and not sline.startswith("#"):
                    # Resolve this URI relative to the CURRENT playlist's location (target_url)
                    absolute_uri = urljoin(target_url, sline)
                    # Now encode it relative to the master URL so the proxy can fetch it
                    relative_to_master = absolute_uri.replace(hls_url.rstrip("/") + "/", "")
                    if relative_to_master == absolute_uri:
                        # If the segment is on a different domain, pass it through directly
                        # (or we could proxy it, but that adds complexity)
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
