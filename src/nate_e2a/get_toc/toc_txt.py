import re

from ..types import TTSTrack, page_char


def get_toc_txt(text0):
    page_num = 0
    pages = re.split(page_char, text0)
    for _, page in enumerate(pages):
        page_num += 1
        track = TTSTrack(text=page, title=f"p. {page_num}")
        yield track
    return
