# -*- coding: utf-8 -*-
"""
Created on 2025-12-19T15:08:24-05:00

@author: nate
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import mutagen.mp3
from loguru import logger
from mutagen.id3 import ID3, SYLT, Encoding


@dataclass(frozen=True)
class TrackMeta:
    artist: str
    title: str
    album: str
    track: int
    description: str


def _run(cmd: list[str]) -> None:
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def write_sylt(mp3_path: Path, lyrics: list[tuple[str, int]]) -> None:
    """
    lyrics: list of (text, timestamp_ms)
    """
    mp3 = mutagen.mp3.MP3(mp3_path)
    if mp3.tags is None:
        mp3.tags = mutagen.id3.ID3()

    mp3.save(v1=0, v2_version=3)

    audio = ID3(mp3_path)
    frame = SYLT(encoding=Encoding.UTF8, lang="eng", format=2, type=1, text=lyrics)
    audio.add(frame)
    audio.save(v2_version=3)


def format_lrc_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - (minutes * 60)
    hundredths = int((secs - int(secs)) * 100)
    return f"[{minutes:02d}:{int(secs):02d}.{hundredths:02d}]"


def sylt_to_lrc(mp3_path: Path, title: str, artist: str) -> Path:
    lrc_path = mp3_path.with_suffix(".lrc")
    audio = ID3(mp3_path)
    sylt_frames = audio.getall("SYLT")

    with lrc_path.open("w", encoding="utf-8") as f:
        f.write(f"[ti: {title}]\n")
        f.write(f"[ar: {artist}]\n\n")
        for sylt in sylt_frames:
            for text, timestamp_ms in sylt.text:
                ts = format_lrc_timestamp(timestamp_ms / 1000.0)
                f.write(f"{ts} {text}\n")

    return lrc_path


def set_id3v2_tags_with_id3v2_cli(mp3_path: Path, meta: TrackMeta) -> None:
    # Keep your original behavior (id3v2 CLI). Eventually replace with mutagen-only.
    _run(
        [
            "id3v2",
            "--artist",
            meta.artist,
            "--track",
            str(meta.track),
            "--album",
            meta.album,
            "--comment",
            meta.description,
            "--song",
            meta.title,
            mp3_path.as_posix(),
        ]
    )


def write_sylt(mp3_path: Path, lyrics: list[tuple[str, int]]) -> None:
    """
    lyrics: list of (text, timestamp_ms)
    """
    mp3 = mutagen.mp3.MP3(mp3_path)
    if mp3.tags is None:
        mp3.tags = mutagen.id3.ID3()

    # Force ID3v2.3 (matches your original)
    mp3.save(v1=0, v2_version=3)

    audio = ID3(mp3_path)
    frame = SYLT(encoding=Encoding.UTF8, lang="eng", format=2, type=1, text=lyrics)
    audio.add(frame)
    audio.save(v2_version=3)


def sylt_to_lrc(mp3_path: Path, title: str, artist: str) -> Path:
    lrc_path = mp3_path.with_suffix(".lrc")
    audio = ID3(mp3_path)
    sylt_frames = audio.getall("SYLT")

    with lrc_path.open("w", encoding="utf-8") as f:
        f.write(f"[ti: {title}]\n")
        f.write(f"[ar: {artist}]\n\n")

        for sylt in sylt_frames:
            for text, timestamp_ms in sylt.text:
                ts = format_lrc_timestamp(timestamp_ms / 1000.0)
                f.write(f"{ts} {text}\n")

    return lrc_path
