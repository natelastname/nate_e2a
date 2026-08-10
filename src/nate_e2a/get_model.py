#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-06-25T18:37:14-04:00

@author: nate
"""
from pathlib import Path

import requests
from loguru import logger
from piper.voice import PiperVoice
from platformdirs import user_cache_dir
from tqdm import tqdm

DEFAULT_VOICE = "en_GB-alan-medium"
PIPER_VOICE_RELEASE = "v1.0.0"
PIPER_VOICE_ROOT = "https://huggingface.co/rhasspy/piper-voices/resolve"


def voice_base_url(voice: str) -> str:
    """Return the download URL stem for a standard Piper voice ID."""
    try:
        locale, remainder = voice.split("-", 1)
        speaker, quality = remainder.rsplit("-", 1)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Piper voice {voice!r}; expected e.g. 'en_US-joe-medium'"
        ) from exc

    if "_" not in locale or not speaker or not quality:
        raise ValueError(
            f"Invalid Piper voice {voice!r}; expected e.g. 'en_US-joe-medium'"
        )

    language = locale.split("_", 1)[0]
    return (
        f"{PIPER_VOICE_ROOT}/{PIPER_VOICE_RELEASE}/"
        f"{language}/{locale}/{speaker}/{quality}/{voice}"
    )


def get_model(outfile_name: str, download_url: str) -> Path:
    model_dir = Path(user_cache_dir("nate_e2a")) / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / outfile_name

    if model_path.exists():
        logger.info("Using cached model at {}", model_path)
        return model_path

    logger.info("Downloading '{}'...", outfile_name)
    with requests.get(download_url, stream=True) as response:
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        with model_path.open("wb") as output, tqdm(
            desc=outfile_name,
            total=total_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for chunk in response.iter_content(chunk_size=8192):
                output.write(chunk)
                bar.update(len(chunk))

    return model_path


def ensure_model_weights(voice: str = DEFAULT_VOICE) -> Path:
    base_url = voice_base_url(voice)
    model_name = f"{voice}.onnx"
    model_path = get_model(model_name, f"{base_url}.onnx?download=true")
    get_model(f"{model_name}.json", f"{base_url}.onnx.json?download=true")
    return model_path


def load_piper_voice(voice: str = DEFAULT_VOICE) -> PiperVoice:
    logger.debug("Loading voice {}...", voice)
    return PiperVoice.load(ensure_model_weights(voice))
