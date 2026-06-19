# -*- coding: utf-8 -*-
"""
Created on 2025-12-19T15:11:37-05:00

@author: nate
"""
from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import ebook_to_audio as e2a
from ebook_to_audio.types import RunArgs, TTSTrack


def get_toc(args: RunArgs) -> Iterator[TTSTrack]:
    if str(args.infile).endswith("pdf"):
        yield from e2a.toc_pdf.get_toc_pdf(args)
        return
    yield from e2a.toc_epub.get_toc_epub(args)


def _strip_control_chars(text: str) -> str:
    for ch in (e2a.types.sentence_char, e2a.types.pg_char, e2a.types.page_char):
        text = text.replace(ch, "")
    return text

def synthesize_mp3_with_sylt(
    text: str,
    mp3_path: Path,
    *,
    voice: PiperVoice,
    bitrate_kbps: int = 64,
) -> Path:
    """
    Build an MP3 by synthesizing each sentence separately,
    concatenating WAVs, then embedding SYLT timestamps.
    """
    sentences = e2a.chunking.split_for_sylt(text)

    with tempfile.TemporaryDirectory(prefix="e2a.sylt.") as td:
        td_path = Path(td)

        wavs: list[Path] = []
        lyrics: list[tuple[str, int]] = []
        curr_ms = 0

        for i, sent in enumerate(sentences):
            sent = sent.strip()
            if not sent:
                continue
            print(sent)
            wav_path = td_path / f"sent_{i:06d}.wav"
            e2a.tts.synthesize_wav(sent, wav_path, voice)

            dur_ms = e2a.tts.wav_duration_ms(wav_path)
            lyrics.append((sent, curr_ms))
            curr_ms += dur_ms
            wavs.append(wav_path)

        if not wavs:
            raise ValueError("No audio produced")

        full_wav = td_path / "full.wav"
        e2a.tts.concat_wavs(wavs, full_wav)
        e2a.tts.encode_mp3(full_wav, mp3_path, bitrate_kbps=bitrate_kbps)

    e2a.metadata.write_sylt(mp3_path, lyrics)
    return mp3_path


def convert_text(
    chunk_gen: Iterable[TTSTrack],
    outpath: str | Path,
    artist: str,
    voice: e2a.tts.PiperVoice,
    *,
    no_metadata: bool = False,
    gen_lrc: bool = True,
    bitrate_kbps: int = 64,
) -> None:
    outdir = Path(outpath)
    outdir.mkdir(parents=True, exist_ok=True)

    out_text_parts: list[str] = []

    for item_num, track in enumerate(chunk_gen, start=1):
        text = _strip_control_chars(track.text)
        if text.strip() == "":
            continue

        z = f"{item_num:06d}"
        final_mp3 = outdir / f"{z}.mp3"

        # 🔸 PRINT TOC ITEM
        print()
        print("=" * 80)
        print(f"[{item_num:03d}] TOC ITEM: {track.title}")
        print("=" * 80)

        # 1) Synthesize MP3
        if gen_lrc:
            synthesize_mp3_with_sylt(track.text, final_mp3, voice=voice, bitrate_kbps=bitrate_kbps)
        else:
            e2a.tts.synthesize_mp3(text, final_mp3, voice, bitrate_kbps=bitrate_kbps)

        # 2) Metadata
        meta = e2a.metadata.TrackMeta(
            artist=artist,
            title=f"{z} {track.title}",
            album=artist,
            track=item_num,
            description=f"Created {dt.datetime.now().isoformat(timespec='minutes')}",
        )
        if not no_metadata:
            e2a.metadata.set_id3v2_tags_with_id3v2_cli(final_mp3, meta)

        if gen_lrc:
            e2a.metadata.sylt_to_lrc(final_mp3, title=meta.title, artist=meta.artist)

        out_text_parts.append(text + e2a.types.page_char + "\n")

    (outdir / "00-text.txt").write_text("".join(out_text_parts), encoding="utf-8")


