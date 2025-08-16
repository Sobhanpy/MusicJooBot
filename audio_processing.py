from future import annotations

import os
import re
import tempfile
import subprocess
from typing import Optional, Tuple

from pydub import AudioSegment
import librosa
import numpy as np
import imageio_ffmpeg as ioff

FFMPEG_BIN = ioff.get_ffmpeg_exe()  # portable ffmpeg path

def _run_ffmpeg_cmd(args: list[str]) -> None:
    """Run ffmpeg with given args using the portable binary."""
    cmd = [FFMPEG_BIN] + args
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def is_url(text: str) -> bool:
    return bool(re.match(r'https?://', text.strip(), re.IGNORECASE))

def extract_audio_from_file(in_path: str, out_wav: Optional[str] = None, sr: int = 44100) -> str:
    """
    Convert any audio/video file to mono WAV for processing.
    """
    if out_wav is None:
        out_wav = in_path + ".wav"
    _run_ffmpeg_cmd([
        "-y", "-i", in_path, "-ac", "1", "-ar", str(sr), out_wav
    ])
    return out_wav

def extract_audio_from_url(url: str, out_wav: Optional[str] = None, sr: int = 44100) -> str:
    """
    Download media via yt-dlp and convert to mono WAV.
    """
    import yt_dlp

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download best audio
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "dl.%(ext)s"),
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "postprocessors": []
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the downloaded file
        files = [f for f in os.listdir(tmpdir) if f.startswith("dl.")]
        if not files:
            raise RuntimeError("Download failed or returned no files.")
        in_path = os.path.join(tmpdir, files[0])

        if out_wav is None:
            out_wav = os.path.join(tmpdir, "audio.wav")

        _run_ffmpeg_cmd([
            "-y", "-i", in_path, "-ac", "1", "-ar", str(sr), out_wav
        ])
        # Copy to a persistent temp file (yt-dlp tmp will be cleaned)
        final_fd, final_path = tempfile.mkstemp(suffix=".wav")
        os.close(final_fd)
        _run_ffmpeg_cmd(["-y", "-i", out_wav, final_path])
        return final_path

def load_wav_mono(path: str, sr: int = 44100) -> Tuple[np.ndarray, int]:
    """Load mono wav to numpy array."""
    y, srate = librosa.load(path, sr=sr, mono=True)
    return y, srate

def quick_embed(y: np.ndarray, sr: int) -> np.ndarray:
    """
    Produce a compact embedding from audio using log-mel spectrogram.
    This is NOT Chromaprint, but can be used for quick heuristics/fallbacks.
    """
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=64, n_fft=2048, hop_length=512)
    logS = librosa.power_to_db(S + 1e-10)
    v = logS.mean(axis=1)
    v = (v - v.mean()) / (v.std() + 1e-8)
    return v.astype(np.float32)