# -*- coding: utf-8 -*-
"""
Created on 2024-12-08T10:04:25-05:00

@author: nate
"""
import atexit
import dataclasses
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional
import argh
from loguru import logger

from .get_model import ensure_model_weights, load_piper_voice
from .get_toc import get_toc_epub, get_toc_pdf, get_toc_txt
from .outpath_generator import gen_outpath
from .pipeline import convert_text
from .types import RunArgs, RunMode, TOCStrat, page_char

# --------------------------- subprocess utils ---------------------------

def run(cmd: list[str]) -> None:
    """Run a subprocess command with check=True, no shell."""
    logger.debug("Running: {}", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)

# --------------------------- pdf linearization --------------------------

def strip_linearization_to_temp(input_pdf: Path) -> Path:
    """
    Use qpdf to strip linearization and normalize content to a temp PDF file.
    File is removed on process exit.
    """
    input_pdf = input_pdf.resolve()
    _, out_path_str = tempfile.mkstemp(suffix=".pdf", prefix="e2a.qpdf.")
    Path(out_path_str).unlink(missing_ok=True)  # qpdf will create it

    out_path = Path(out_path_str)

    def _cleanup() -> None:
        out_path.unlink(missing_ok=True)

    atexit.register(_cleanup)

    run([
        "qpdf",
        str(input_pdf),
        "--qdf",
        "--normalize-content=y",
        str(out_path),
    ])
    return out_path


def _coerce_suffix(p: Path) -> str:
    return p.suffix.lower().lstrip(".")

def _maybe_strip_pdf(args: RunArgs) -> RunArgs:
    p = Path(args.infile)
    if args.rm_linearization and _coerce_suffix(p) == "pdf":
        logger.info("Stripping PDF linearization…")
        stripped = strip_linearization_to_temp(p)
        logger.info("Linearization stripped to temp: {}", stripped)
        return dataclasses.replace(args, infile=str(stripped))
    return args

# --------------------------- generator selection ------------------------

def get_chunk_generator(args: RunArgs, infile: Path):
    """
    Decide how to produce TTSTrack chunks given the input file.
    This should stay thin; ideally it moves into ebook_to_audio.pipeline later.
    """


def get_chunk_generator(args: RunArgs, infile: Path):
    """
    Decide how to produce TTSTrack chunks given the input file.
    """
    suffix = _coerce_suffix(infile)

    if suffix == "pdf":
        return get_toc_pdf(args)

    if suffix == "epub":
        return get_toc_epub(args)

    if suffix == "txt":
        text = infile.read_text(encoding="utf-8", errors="replace")
        return get_toc_txt(text)

    if suffix in {"azw3", "mobi", "djvu"}:
        def converted_generator():
            with tempfile.TemporaryDirectory(prefix="e2a.") as tempdir:
                converted = Path(tempdir) / f"{infile.stem}.epub"
                run(["ebook-convert", str(infile), str(converted)])
                args0 = dataclasses.replace(args, infile=str(converted))
                yield from get_toc_epub(args0)

        return converted_generator()

    raise ValueError(f"No chunk generator for '*.{suffix}' files.")
# --------------------------- outpath helpers ----------------------------

def ensure_outdir(base_outpath: Optional[Path], infile: Path) -> tuple[str, Path]:
    """
    Compute album name and ensure the final outpath directory exists.
    """
    out_root = (base_outpath or infile.parent).resolve()
    album, outdir = gen_outpath(str(out_root), str(infile))
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    return album, outdir_path

def plain_outfile(base_outpath: Optional[Path], infile: Path) -> Path:
    """
    Where split_txt writes by default: a sibling .txt under outpath root.
    (Not in the input directory.)
    """
    out_root = (base_outpath or infile.parent).resolve()
    album, outdir = gen_outpath(str(out_root), str(infile))
    outdir_path = Path(outdir+".txt")
    return outdir_path

# --------------------------- core operations ----------------------------

def write_toc_text(outfile: Path, toc: Iterable) -> None:
    """
    Stream TOC chunks to disk with page separators, avoiding big in-memory strings.
    """
    outfile.parent.mkdir(parents=True, exist_ok=True)

    with outfile.open("w", encoding="utf-8") as fp:
        for i, toc_item in enumerate(toc):
            logger.info("{:4}: {}", i, getattr(toc_item, "title", str(toc_item)))
            page_txt = (getattr(toc_item, "text", "") or "").strip()
            fp.write(page_txt)
            fp.write(page_char + "\n\n")


# --------------------------- CLI commands --------------------------------

def split_txt(
    infile: str,
    toc_strat: TOCStrat = TOCStrat.DEFAULT,
    unspace: bool = False,
    rm_linearization: bool = False,
) -> None:
    """
    Extract TOC text into a single .txt with page separators.
    """
    src = Path(infile).resolve()
    inf = Path(infile)
    if not inf.is_file():
        raise Exception('Not a file')

    out_root = inf.parent

    runargs = RunArgs(
        infile=str(src),
        outpath=str(out_root or src.parent),
        toc_strat=toc_strat,
        unspace=unspace,
        run_mode="full",
        rm_linearization=rm_linearization,
    )

    runargs = _maybe_strip_pdf(runargs)

    chunk_gen = get_chunk_generator(runargs, Path(runargs.infile))
    outfile = plain_outfile(out_root, Path(runargs.infile))

    logger.info("Writing text to {}", outfile)
    write_toc_text(outfile, chunk_gen)
    logger.success("Done: {}", outfile)



def tts(
    infile: str,
    *,
    outpath: Optional[str] = None,
    toc_strat: TOCStrat = TOCStrat.DEFAULT,
    unspace: bool = False,
    run_mode: RunMode = RunMode.NORMAL,
    rm_linearization: bool = False,
) -> Optional[str]:
    """
    TTS pipeline.
    """
    ensure_model_weights()

    src = Path(infile).resolve()
    out_root = Path(outpath).resolve() if outpath else None

    runargs = RunArgs(
        infile=str(src),
        outpath=str(out_root or src.parent),
        toc_strat=toc_strat,
        unspace=unspace,
        run_mode=run_mode,
        rm_linearization=rm_linearization,
    )

    runargs = _maybe_strip_pdf(runargs)

    # Print-only / debug modes
    if runargs.run_mode != RunMode.NORMAL:
        toc = get_chunk_generator(runargs, Path(runargs.infile))
        for i, toc_item in enumerate(toc):
            if runargs.run_mode == "name":
                print(f"{i:4}: {toc_item}")
                continue
            if runargs.run_mode == "full":
                print("#####################################################")
                print(f"{i:4}: {toc_item.title}")
                print("#####################################################")
                print((toc_item.text or "").strip())
                print("#####################################################")
        return None

    album, final_outdir = ensure_outdir(out_root, Path(runargs.infile))
    chunk_gen = get_chunk_generator(runargs, Path(runargs.infile))
    voice = load_piper_voice()
    convert_text(
        chunk_gen,
        str(final_outdir),
        album,
        voice,
        bitrate_kbps=64
    )

    logger.success("Audio written to {}", final_outdir)
    return str(final_outdir)


def e2a_cli() -> None:
    parser = argh.ArghParser()
    parser.add_commands([split_txt, tts])
    parser.dispatch()
