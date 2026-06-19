#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2024-12-08T10:28:47-05:00

@author: nate
"""
import atexit
import datetime as dt
import os
import re
import shutil
import subprocess as sp
import sys
import tempfile
import wave
from pathlib import Path

import mutagen.mp3
from loguru import logger
from mutagen.id3 import ID3, SYLT, Encoding
from piper.voice import PiperVoice
from platformdirs import user_cache_dir

from .greedy_splitter import GreedySentenceSplitter, GreedySplitConfig

logger.remove()
logger.add(sys.stdout, level="INFO")

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

def subproc(cmd):
    result = sp.call(cmd.strip(), shell=True)
    return result

def make_temp_dir():
    """Create a temporary directory that is deleted upon program exit."""
    tempdir = tempfile.mkdtemp(prefix="e2a.", dir='/tmp')
    atexit.register(lambda: shutil.rmtree(tempdir))
    return tempdir

def ebookconvert_to_text(infile, tempdir=None):
    if not tempdir:
        tempdir = make_temp_dir()
    outfile = os.path.join(tempdir, 'output.txt')
    outfile_raw = os.path.join(tempdir, 'output_raw.txt')
    infile_pdf = os.path.join(tempdir, 'input.pdf')
    ######################################################################
    # Conversion to text
    ######################################################################
    if not infile.endswith('.pdf'):
        cmd = f"""
        ebook-convert "{infile}" "{infile_pdf}" > /dev/null 2>&1
        """
        result = subproc(cmd)
        if result > 0:
            raise Exception('Failed to convert fle to PDF.')
        infile = infile_pdf
    text = pdf_test(infile)
    return text

######################################################################
# MP3 book keeping
######################################################################

def set_metadata_tag(vid_path, meta):
    outpath0 = os.path.dirname(vid_path)
    vid_name = os.path.basename(vid_path)
    album = meta['album']
    artist = meta['artist']
    desc = meta['description']
    track = meta['track']
    title = meta['title']
    cmd = f"""
    id3v2 --artist '{artist}' --track '{track}' --album '{album}' --comment '{desc}' --song '{title}' '{vid_path}'
    """
    subproc(cmd)
    return

def get_piper_voice(model_name="en_GB-alan-medium.onnx"):
    logger.debug('Loading voice...')
    model_file_path = Path(user_cache_dir("ebook_to_audio"))
    model_file_path = model_file_path / "models" / model_name
    voice = PiperVoice.load(model_file_path)
    return voice

def perform_tts(text, outfile, tempdir, voice):
    outfile_text = os.path.join(tempdir, "outfile_raw.txt")
    with open(outfile_text, "w+") as fp:
        fp.write(text)
    outfile_wav_raw = os.path.join(tempdir, 'outfile_raw.aac')
    wav_file = wave.open(outfile_wav_raw, 'w')
    logger.debug('synthesizing...')
    audio = voice.synthesize(text, wav_file)
    logger.debug('Running ffmpeg...')
    cmd = f"""
    ffmpeg -hide_banner -loglevel error -y -i "{outfile_wav_raw}" -ab 64k "{outfile}"
    """
    subproc(cmd)
    return outfile

def _perform_tts(text: str, outfile: str | Path, voice: PiperVoice) -> Path:
    """
    Synthesize `text` using PiperVoice and write a WAV file to `outfile`.

    This uses the runtime Piper API:
    - synthesize_wav(text, wav_file)
    """
    out_path = Path(outfile)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("Synthesizing TTS → %s", out_path)

    # Pick a sample rate: use config.sample_rate if available, else fall back.
    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", None)
    if sample_rate is None:
        sample_rate = getattr(voice, "sample_rate", 22050)
    with wave.open(out_path.as_posix(), "wb") as wav_file:
        # 16-bit mono PCM — what Piper expects
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        # Let Piper write frames into this wave file
        voice.synthesize_wav(text, wav_file)
    logger.debug("TTS done → %s", out_path)
    return out_path

def generate_with_sylt(
        text,
        outfile,
        tempdir
):
    logger.info("Running...")
    lyrics = []
    curr_time = 0
    out_sents = []
    lines = re.split(f'\n+', text.strip())
    outfile_temp, _ = os.path.splitext(outfile)

    outfile_temp_1 = outfile_temp + ".tmp1.wav"
    if os.path.isfile(outfile_temp_1):
        os.unlink(outfile_temp_1)

    outfile_temp_2 = outfile_temp + ".tmp2.wav"
    if os.path.isfile(outfile_temp_2):
        os.unlink(outfile_temp_2)

    voice = get_piper_voice()


    splitter_conf = GreedySplitConfig(
        max_len=320,
        target_len=260,
        min_len=50,
        allow_early_cut_tier_index=0
    )
    splitter = GreedySentenceSplitter(splitter_conf)
    sentences = splitter.split(text.replace('\n', ' '))


    #for line in lines:
    for line in sentences:
        print(line)
        line0 = line
        with tempfile.TemporaryDirectory() as tempdir:

            outfile0 = os.path.join(tempdir, 'sent0.wav')
            e2a.util.perform_tts(line0, outfile0, tempdir, voice)
            if not os.path.isfile(outfile0):
                print("skipped")
                continue

            duration0 = get_wav_duration(outfile0)
            duration0 = int(duration0 * 1000)

            lyrics.append((line0, curr_time))
            #logger.info(f"[{round(curr_time,3):8}, {line0}")
            curr_time += duration0

            if os.path.isfile(outfile_temp_1):
                concat_audio_wave([outfile_temp_1, outfile0], outfile_temp_2)
                e2a.util.subproc(f"mv '{outfile_temp_2}' '{outfile_temp_1}'")
            else:
                concat_audio_wave([outfile0], outfile_temp_1)


    cmd = f"""
    ffmpeg -hide_banner -loglevel error -y -i "{outfile_temp_1}" -ab 64k "{outfile}"
    """
    e2a.util.subproc(cmd)
    if os.path.isfile(outfile_temp):
        os.unlink(outfile)

    m0 = mutagen.mp3.MP3(outfile)
    if m0.tags is None:
        m0.tags = mutagen.id3.ID3()

    # save ID3v2.3 only without ID3v1 (default is ID3v2.4)
    m0.save(v1=0, v2_version=3)

    audio = ID3(outfile)
    meta = SYLT(encoding=Encoding.UTF8, lang='eng', format=2, type=1, text=lyrics)
    audio.add(meta)
    audio.save(v2_version=3)

    return outfile


def _convert_text(chunk_generator, outfile_mp3: str, tempdir: str, gen_lrc: bool=True):
    """Yield (track, final_mp3_path) after synthesis."""
    for track in chunk_generator:
        if not isinstance(track, e2a.types.TTSTrack):
            raise TypeError("chunk_generator yielded non-TTSTrack")

        print("###########################################################")
        print(track.text)
        print("###########################################################")

        # Strip control chars
        for ch in (e2a.types.sentence_char, e2a.types.pg_char, e2a.types.page_char):
            track.text = track.text.replace(ch, "")

        if track.text.strip() == "":
            continue

        if gen_lrc:
            generate_with_sylt(track.text, outfile_mp3, tempdir)
        else:
            perform_tts(track.text, outfile_mp3, tempdir)

        yield track, outfile_mp3

def convert_text(
    chunk_gen,
    outpath: str,
    artist: str,
    tempdir: str,
    no_metadata: bool = False,
    gen_lrc: bool = True,
) -> None:
    outdir = Path(outpath)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp_mp3 = outdir / "raw.mp3"
    gen0 = _convert_text(chunk_gen, str(tmp_mp3), tempdir, gen_lrc=gen_lrc)
    out_text = ""
    for item_num, (track, _) in enumerate(gen0, start=1):

        z = f"{item_num:06d}"
        final_mp3 = outdir / f"{z}.mp3"
        meta = {
            "artist": artist,
            "title": f"{z} {track.title}",
            "album": artist,
            "track": item_num,
            "description": f"Created {dt.datetime.now().isoformat(timespec='minutes')}",
        }

        if not no_metadata:
            set_metadata_tag(str(tmp_mp3), meta)

        tmp_mp3.rename(final_mp3)
        if gen_lrc:
            sylt_to_lrc(meta['title'], meta['artist'], final_mp3)

        out_text = out_text + track.text + e2a.types.page_char + "\n"

    # Write the text to a file for archive purposes
    text_file = os.path.join(outpath, '00-text.txt')
    with open(text_file, 'w+') as fp:
        fp.write(out_text)
