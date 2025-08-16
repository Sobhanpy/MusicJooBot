from future import annotations

import base64
import logging
from typing import Dict, Any, Optional, List

import requests

log = logging.getLogger("musicjoo.providers")

# ------------------------- MusicBrainz & Cover Art -------------------------

def mb_search_recordings(query: str, user_agent: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search MusicBrainz recordings by free text (title/artist).
    NOTE: MusicBrainz does not index full lyrics; use this for title/artist.
    """
    url = "https://musicbrainz.org/ws/2/recording"
    params = {"query": query, "fmt": "json", "limit": str(limit)}
    headers = {"User-Agent": user_agent}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("recordings", [])

def mb_lookup_recording(mbid: str, user_agent: str) -> Dict[str, Any]:
    """Lookup a MusicBrainz recording by MBID and expand releases to get album info."""
    url = f"https://musicbrainz.org/ws/2/recording/{mbid}"
    params = {"fmt": "json", "inc": "releases+artists"}
    headers = {"User-Agent": user_agent}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def cover_art_from_release(release_mbid: str) -> Optional[str]:
    """
    Get cover art URL (front) from Cover Art Archive for a given release MBID.
    Returns direct image URL if available, else None.
    """
    url = f"https://coverartarchive.org/release/{release_mbid}/front"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return url
    except Exception:
        pass
    return None

# ------------------------------- AcoustID ----------------------------------

def acoustid_lookup(fp: str, duration: int, api_key: str) -> List[Dict[str, Any]]:
    """
    Query AcoustID with Chromaprint fingerprint.
    Returns a list of results with MusicBrainz recording IDs.
    """
    url = "https://api.acoustid.org/v2/lookup"
    data = {
        "client": api_key,
        "meta": "recordings+releasegroups+releases+tracks+compress",
        "duration": str(duration),
        "fingerprint": fp
    }
    r = requests.post(url, data=data, timeout=20)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != "ok":
        return []
    return js.get("results", [])

# -------------------------------- Spotify ----------------------------------

def spotify_client_credentials_token(client_id: str, client_secret: str) -> Optional[str]:
    """
    Get an app-only access token (Client Credentials flow).
    """
    if not client_id or not client_secret:
        return None
    token_url = "https://accounts.spotify.com/api/token"
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    data = {"grant_type": "client_credentials"}
    r = requests.post(token_url, headers=headers, data=data, timeout=15)
    if r.status_code != 200:
        log.warning("Spotify token failed: %s %s", r.status_code, r.text[:200])
        return None
    return r.json().get("access_token")

def spotify_search_track(q: str, token: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Search tracks on Spotify by free text."""
    url = "https://api.spotify.com/v1/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": q, "type": "track", "limit": str(limit)}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("tracks", {}).get("items", [])

def spotify_track_link_and_preview(item: Dict[str, Any]) -> Dict[str, Optional[str]]:
"""Extract Spotify external link, preview URL, cover, artists, title."""
    link = item.get("external_urls", {}).get("spotify")
    preview = item.get("preview_url")
    cover = None
    images = item.get("album", {}).get("images") or []
    if images:
        cover = images[0].get("url")
    artists = ", ".join([a.get("name", "") for a in item.get("artists", []) if a.get("name")])
    title = item.get("name")
    return {"link": link, "preview": preview, "cover": cover, "artists": artists, "title": title}

# -------------------------------- Lyrics (best-effort) ---------------------

def lyrics_best_effort(artist: str, title: str) -> Optional[str]:
    """
    Try to fetch lyrics excerpt using a free public source (lyrics.ovh).
    This often works for popular tracks; returns up to ~500 chars excerpt.
    """
    if not artist or not title:
        return None
    try:
        url = f"https://api.lyrics.ovh/v1/{artist}/{title}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        txt = (r.json() or {}).get("lyrics")
        if not txt:
            return None
        # Trim to a small excerpt to stay fair-use
        excerpt = txt.strip().splitlines()
        out = []
        for line in excerpt:
            if line.strip():
                out.append(line.strip())
            if sum(len(x) for x in out) > 500:
                break
        return "\n".join(out)
    except Exception:
        return None