from future import annotations
import os
from typing import Optional, Dict, Any, List, Tuple

from utils import get_env
from audio_processing import (
    is_url, extract_audio_from_file, extract_audio_from_url
)
from providers import (
    mb_search_recordings, mb_lookup_recording, cover_art_from_release,
    acoustid_lookup,
    spotify_client_credentials_token, spotify_search_track, spotify_track_link_and_preview,
    lyrics_best_effort
)

def _chromaprint_fingerprint(wav_path: str) -> Optional[Tuple[str, int]]:
    """
    Compute Chromaprint fingerprint using pyacoustid (requires fpcalc present in PATH).
    Returns (fingerprint_string, duration_seconds) or None.
    """
    try:
        import acoustid  # pyacoustid
        fp, duration = acoustid.fingerprint_file(wav_path)
        return fp, int(duration)
    except Exception:
        return None

def _spotify_token() -> Optional[str]:
    cid = get_env("SPOTIFY_CLIENT_ID", "")
    sec = get_env("SPOTIFY_CLIENT_SECRET", "")
    if not cid or not sec:
        return None
    return spotify_client_credentials_token(cid, sec)

def _enrich_spotify_and_cover(title: str, artists: str, cover_url: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Using Spotify, fetch (spotify_link, spotify_preview, cover_url_fallback).
    """
    link = preview = None
    token = _spotify_token()
    if token:
        items = spotify_search_track(f"{title} {artists}".strip(), token, limit=1)
        if items:
            sp = spotify_track_link_and_preview(items[0])
            link = sp["link"]
            preview = sp["preview"]
            cover_url = cover_url or sp["cover"]
            return link, preview, cover_url
    return link, preview, cover_url

def identify_from_audio_input(input_path_or_url: str, user_agent: str) -> Optional[Dict[str, Any]]:
    """
    Identify a song from a local file path or a URL.
    Returns dict: {title, artists, cover_url, mbid, spotify_link, spotify_preview, lyrics_excerpt}
    """
    # 1) Convert to WAV (mono) via ffmpeg
    if is_url(input_path_or_url):
        wav_path = extract_audio_from_url(input_path_or_url)
    else:
        wav_path = extract_audio_from_file(input_path_or_url)

    # 2) Fingerprint lookup via AcoustID (if configured)
    acoustid_key = get_env("ACOUSTID_API_KEY", "")
    if acoustid_key:
        fp_info = _chromaprint_fingerprint(wav_path)
        if fp_info:
            fp, dur = fp_info
            matches = acoustid_lookup(fp, dur, acoustid_key)
            if matches:
                top = sorted(matches, key=lambda x: x.get("score", 0), reverse=True)[0]
                recs = top.get("recordings") or []
                if recs:
                    rec = recs[0]
                    mbid = rec.get("id")
                    info = mb_lookup_recording(mbid, user_agent)
                    title = info.get("title")
                    artists = ", ".join(a.get("name", "") for a in info.get("artist-credit", []) if a.get("name"))
                    releases = info.get("releases") or []
                    cover_url = cover_art_from_release(releases[0]["id"]) if releases else None
                    sp_link, sp_prev, cover_url = _enrich_spotify_and_cover(title, artists, cover_url)
                    lyrics = lyrics_best_effort(artists.split(",")[0].strip() if artists else "", title or "")
                    return {
                        "title": title,
                        "artists": artists,
                        "cover_url": cover_url,
                        "mbid": mbid,
                        "spotify_link": sp_link,
                        "spotify_preview": sp_prev,
                        "lyrics_excerpt": lyrics
                    }

    # No result from AcoustID → return None; caller may try text search fallback elsewhere if needed
    return None
def identify_from_text(query: str, user_agent: str) -> Optional[Dict[str, Any]]:
    """
    Identify a song from text (title/artist or loose query) via MusicBrainz (+Spotify enrichment).
    Returns dict: {title, artists, cover_url, mbid, spotify_link, spotify_preview, lyrics_excerpt}
    """
    # 1) Try MusicBrainz recordings
    recordings = mb_search_recordings(query, user_agent, limit=5)
    pick = recordings[0] if recordings else None

    # 2) If nothing, try Spotify search and map back basic info
    if not pick:
        token = _spotify_token()
        if token:
            items = spotify_search_track(query, token, limit=1)
            if items:
                sp = spotify_track_link_and_preview(items[0])
                artists = sp["artists"] or ""
                title = sp["title"] or query
                lyrics = lyrics_best_effort(artists.split(",")[0].strip() if artists else "", title)
                return {
                    "title": title,
                    "artists": artists,
                    "cover_url": sp["cover"],
                    "mbid": None,
                    "spotify_link": sp["link"],
                    "spotify_preview": sp["preview"],
                    "lyrics_excerpt": lyrics
                }
        return None

    # 3) Build result from MB pick
    mbid = pick.get("id")
    title = pick.get("title")
    artists = ", ".join(a.get("name", "") for a in pick.get("artist-credit", []) if a.get("name")) or "Unknown"
    rels = pick.get("releases") or []
    cover_url = cover_art_from_release(rels[0]["id"]) if rels else None

    sp_link, sp_prev, cover_url = _enrich_spotify_and_cover(title or "", artists or "", cover_url)
    lyrics = lyrics_best_effort(artists.split(",")[0].strip() if artists else "", title or "")

    return {
        "title": title,
        "artists": artists,
        "cover_url": cover_url,
        "mbid": mbid,
        "spotify_link": sp_link,
        "spotify_preview": sp_prev,
        "lyrics_excerpt": lyrics
    }