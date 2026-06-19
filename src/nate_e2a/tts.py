# -*- coding: utf-8 -*-
"""
Created on 2025-12-19T15:07:42-05:00

@author: nate
"""
from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True)
class TTSConfig:
    model_name: str = "en_GB-alan-medium.onnx"
    bitrate_kbps: int = 64

def _run(cmd: list[str]) -> None:
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

def wav_duration_ms(path: Path) -> int:
    with wave.open(path.as_posix(), "rb") as f:
        frames = f.getnframes()
        rate = f.getframerate()
    seconds = frames / float(rate)
    return int(seconds * 1000)

def synthesize_wav(text: str, wav_path: Path, voice: PiperVoice) -> Path:
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", None)
    if sample_rate is None:
        sample_rate = getattr(voice, "sample_rate", 22050)

    with wave.open(wav_path.as_posix(), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        voice.synthesize(text, wf)

    return wav_path

def concat_wavs(wavs: list[Path], out_wav: Path) -> Path:
    if not wavs:
        raise ValueError("No wavs to concatenate")

    out_wav.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(wavs[0].as_posix(), "rb") as w0:
        params = w0.getparams()

    with wave.open(out_wav.as_posix(), "wb") as out:
        out.setparams(params)
        for wav in wavs:
            with wave.open(wav.as_posix(), "rb") as w:
                params2 = w.getparams()
                if params.nchannels != params2.nchannels or params.sampwidth != params2.sampwidth or params.framerate != params2.framerate:
                    raise ValueError(f"WAV params mismatch: {wav}")
                out.writeframes(w.readframes(w.getnframes()))

    return out_wav

def encode_mp3(wav_path: Path, mp3_path: Path, bitrate_kbps: int = 64) -> Path:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    _run([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        wav_path.as_posix(),
        "-ab",
        f"{bitrate_kbps}k",
        mp3_path.as_posix(),
    ])
    return mp3_path

def synthesize_mp3(text: str, mp3_path: Path, voice: PiperVoice, bitrate_kbps: int = 64) -> Path:
    wav_path = mp3_path.with_suffix(".wav")
    synthesize_wav(text, wav_path, voice)
    encode_mp3(wav_path, mp3_path, bitrate_kbps=bitrate_kbps)
    if wav_path.exists():
        wav_path.unlink()
    return mp3_path
