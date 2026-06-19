#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2024-12-08T10:28:47-05:00

@author: nate
"""
import datetime as dt
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import mutagen
import mutagen.id3
import mutagen.mp3
import pymupdf
from loguru import logger
from mutagen.id3 import ID3, SYLT, Encoding
from piper.voice import PiperVoice
from platformdirs import user_cache_dir

from .greedy_splitter import GreedySentenceSplitter, GreedySplitConfig
from .types import TTSTrack, page_char, pg_char, sentence_char

logger.remove()
logger.add(sys.stdout, level="INFO")

# NOTE:
# We intentionally convert EPUB (and other ebook formats) to PDF before
# extracting text. Although slower than parsing HTML/XHTML directly, this
# approach leverages Calibre's mature rendering engine to resolve book
# structure, CSS, navigation, footnotes, and malformed ebook content into a
# single rendered document. Extracting text from the rendered PDF via MuPDF
# generally produces more reliable reading order and cleaner output for TTS
# and LLM ingestion than direct HTML text extraction.

def pymupdf_to_text(infile: str | Path) -> str:
    """Convert a pdf to text using PyMuPDF."""
    with pymupdf.open(infile) as doc:
        return "\n".join(page.get_text() for page in doc)

def ebookconvert_to_text(infile: str | Path, tempdir: str | Path | None = None) -> str:
    infile = Path(infile)

    with tempfile.TemporaryDirectory(prefix="e2a.", dir=tempdir) as workdir:
        workdir = Path(workdir)
        pdf_path = workdir / "input.pdf"

        if infile.suffix.lower() != ".pdf":
            subprocess.run(
                ["ebook-convert", str(infile), str(pdf_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            infile = pdf_path

        return pymupdf_to_text(infile)

######################################################################
# Audio
######################################################################

def format_timestamp(seconds: float) -> str:
    """Convert seconds (float) to LRC timestamp format [mm:ss.xx]."""
    minutes = int(seconds // 60)
    secs = seconds - (minutes*60)

    rem = int((secs - int(secs))*100)
    secs = int(secs)
    ts0 = f"[{minutes:02d}:{secs:02d}.{rem:02d}]"
    return ts0

def sylt_to_lrc(title: str, artist: str, mp3_file):
    lrc_file, _ = os.path.splitext(mp3_file)
    lrc_file = lrc_file + ".lrc"
    # Load MP3 and read ID3 tags
    audio = ID3(mp3_file)
    sylt_frames = audio.getall("SYLT")
    # Open LRC file for writing
    with open(lrc_file, 'w', encoding='utf-8') as f:
        # Optional: Add LRC metadata (title, artist, etc.)
        f.write(f"[ti: {title}]\n")
        f.write(f"[ar: {artist}]\n")
        f.write("\n")
        for sylt in sylt_frames:
            for text, timestamp in sylt.text:
                lrc_time = format_timestamp(timestamp/1000)
                line = f"{lrc_time} {text}\n"
                f.write(line)
    return

def concat_audio_wave(audio_clip_paths, output_path):
    data = []
    for clip in audio_clip_paths:
        w = wave.open(clip, "rb")
        data.append([w.getparams(), w.readframes(w.getnframes())])
        w.close()
    output = wave.open(output_path, "wb")
    output.setparams(data[0][0])
    for i in range(len(data)):
        output.writeframes(data[i][1])
    output.close()

def get_wav_duration(file_path):
    with wave.open(file_path, 'rb') as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        duration = frames / float(rate)
    return duration

######################################################################
# MP3 book keeping
######################################################################



def set_metadata_tag(mp3_path: str | Path, meta: dict) -> None:
    mp3_path = Path(mp3_path)
    subprocess.run(
        [
            "id3v2",
            "--artist", str(meta["artist"]),
            "--track", str(meta["track"]),
            "--album", str(meta["album"]),
            "--comment", str(meta["description"]),
            "--song", str(meta["title"]),
            str(mp3_path),
        ],
        check=True,
    )



def perform_tts(
    text: str,
    outfile: str | Path,
    tempdir: str | Path,
    voice: PiperVoice,
) -> Path:
    outfile = Path(outfile)
    tempdir = Path(tempdir)
    tempdir.mkdir(parents=True, exist_ok=True)
    raw_text_path = tempdir / "outfile_raw.txt"
    raw_wav_path = tempdir / "outfile_raw.wav"
    raw_text_path.write_text(text, encoding="utf-8")
    logger.debug("Synthesizing...")
    with wave.open(str(raw_wav_path), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    logger.debug("Running ffmpeg...")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(raw_wav_path),
            "-ab", "64k",
            str(outfile),
        ],
        check=True,
    )
    return outfile


def _perform_tts(text: str, outfile: str | Path, voice: PiperVoice) -> Path:
    out_path = Path(outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("Synthesizing TTS → {}", out_path)

    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", None)
    sample_rate = sample_rate or getattr(voice, "sample_rate", 22050)

    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        voice.synthesize_wav(text, wav_file)

    logger.debug("TTS done → {}", out_path)
    return out_path


def generate_with_sylt(
    text: str,
    outfile: str | Path,
    tempdir: str | Path,
) -> Path:
    logger.info("Running...")
    outfile = Path(outfile)
    stem_path = outfile.with_suffix("")
    tmp_wav_1 = stem_path.with_suffix(".tmp1.wav")
    tmp_wav_2 = stem_path.with_suffix(".tmp2.wav")

    tmp_wav_1.unlink(missing_ok=True)
    tmp_wav_2.unlink(missing_ok=True)

    lyrics: list[tuple[str, int]] = []
    curr_time = 0
    voice = get_piper_voice()
    splitter_conf = GreedySplitConfig(
        max_len=320,
        target_len=260,
        min_len=50,
        allow_early_cut_tier_index=0,
    )
    splitter = GreedySentenceSplitter(splitter_conf)
    sentences = splitter.split(text.replace("\n", " "))
    for sentence in sentences:
        print(sentence)
        with tempfile.TemporaryDirectory() as sent_tempdir:
            sent_tempdir = Path(sent_tempdir)
            sent_wav = sent_tempdir / "sent0.wav"
            perform_tts(sentence, sent_wav, sent_tempdir, voice)
            if not sent_wav.is_file():
                print("skipped")
                continue
            duration_ms = int(get_wav_duration(sent_wav) * 1000)
            lyrics.append((sentence, curr_time))
            curr_time += duration_ms
            if tmp_wav_1.is_file():
                concat_audio_wave([tmp_wav_1, sent_wav], tmp_wav_2)
                tmp_wav_2.replace(tmp_wav_1)
            else:
                concat_audio_wave([sent_wav], tmp_wav_1)

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(tmp_wav_1),
            "-ab", "64k",
            str(outfile),
        ],
        check=True,
    )
    mp3 = mutagen.mp3.MP3(outfile)
    if mp3.tags is None:
        mp3.tags = mutagen.id3.ID3()
    mp3.save(v1=0, v2_version=3)
    audio = ID3(outfile)
    audio.add(
        SYLT(
            encoding=Encoding.UTF8,
            lang="eng",
            format=2,
            type=1,
            text=lyrics,
        )
    )
    audio.save(v2_version=3)
    return outfile
