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


DEFAULT_VOICE = "alan"
VOICE_SPECS = {
    "alan": {
        "model_filename": "en_GB-alan-medium.onnx",
        "config_filename": "en_GB-alan-medium.onnx.json",
        "weights_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_GB/alan/medium/en_GB-alan-medium.onnx?download=true"
        ),
        "config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_GB/alan/medium/en_GB-alan-medium.onnx.json?download=true"
        ),
    },
    "joe": {
        "model_filename": "en_US-joe-medium.onnx",
        "config_filename": "en_US-joe-medium.onnx.json",
        "weights_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_US/joe/medium/en_US-joe-medium.onnx?download=true"
        ),
        "config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_US/joe/medium/en_US-joe-medium.onnx.json?download=true"
        ),
    },
}


def _voice_spec(voice: str) -> dict[str, str]:
    try:
        return VOICE_SPECS[voice]
    except KeyError as exc:
        available = ", ".join(sorted(VOICE_SPECS))
        raise ValueError(
            f"Unknown voice {voice!r}. Available voices: {available}"
        ) from exc


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
    spec = _voice_spec(voice)
    model_path = get_model(spec["model_filename"], spec["weights_url"])
    get_model(spec["config_filename"], spec["config_url"])
    return model_path


def load_piper_voice(voice: str = DEFAULT_VOICE) -> PiperVoice:
    logger.debug("Loading voice '{}'...", voice)
    return PiperVoice.load(ensure_model_weights(voice))
