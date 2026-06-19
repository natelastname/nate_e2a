import re

from ..get_pdf_text import get_text_poppler_line_split
from ..preprocess import preprocess_text_lite
from ..types import RunArgs, TTSTrack, page_char


def get_chunk_by_page(text0):
    page_num = 0
    pages = re.split(page_char, text0)
    for i, page in enumerate(pages):
        page_num += 1
        track = TTSTrack(text=page, title=f"p. {page_num}")
        yield track
    return


def get_toc_pdf(args: RunArgs):
    text = get_text_poppler_line_split(args)
    text = preprocess_text_lite(text, args.unspace)
    iterator = get_chunk_by_page(text)
    for track in iterator:
        if args.run_mode == "name":
            yield TTSTrack(title=track.title, text="")
            continue
        yield track
