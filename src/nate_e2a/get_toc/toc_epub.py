# -*- coding: utf-8 -*-
"""
Created on 2025-12-19T15:09:06-05:00

@author: nate
"""
import re
import tempfile
from collections.abc import Iterable, Iterator
from itertools import groupby
from typing import Any

import ebooklib
from ebooklib import epub as ebooklib_epub
from loguru import logger

from ..preprocess import preprocess_text
from ..types import RunArgs, TTSTrack
from ..util import ebookconvert_to_text
from .html_split import html_split


def _flatten(items: Iterable[Any]) -> Iterator[Any]:
    for x in items:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            for y in _flatten(x):
                yield y
        else:
            yield x

def _flatten_toc_with_parents(items: Iterable[Any], parents: list[Any] | None = None) -> Iterator[list[Any]]:
    if parents is None:
        parents = []
    for x in items:
        if isinstance(x, tuple):
            section, children = x
            if not isinstance(section, ebooklib_epub.Section):
                raise TypeError(f"Expected Section, got {type(section)}")
            for y in _flatten_toc_with_parents(children, parents=parents + [section]):
                yield y
        elif isinstance(x, ebooklib_epub.Link):
            yield parents + [x]
        else:
            raise TypeError(f"Unexpected toc element: {type(x)}")



def _epub_by_title(args: RunArgs, book: ebooklib_epub.EpubBook) -> Iterator[tuple[str, bytes | str]]:
    for items in _flatten_toc_with_parents(book.toc):
        title = "/".join([i.title for i in items])
        last = items[-1]
        href = last.href.split("#")[0]
        doc = book.get_item_with_href(href)
        if doc is None:
            logger.warning("Missing href in book: %s", href)
            continue
        yield title, doc.content

def _epub_by_fname(args: RunArgs, book: ebooklib_epub.EpubBook) -> Iterator[tuple[str, bytes | str]]:
    flat = list(_flatten(book.toc))
    refs: list[dict[str, str | int]] = []

    for i, item in enumerate(flat):
        doc_path = item.href.split("#")[0]
        doc_id = ""
        m = re.match(r"(.*)#(.*)", item.href)
        if m:
            doc_path, doc_id = m.groups()
        refs.append({"index": i, "path": doc_path, "id": doc_id})

    refs.sort(key=lambda x: str(x["path"]))

    for path, group in groupby(refs, key=lambda x: x["path"]):
        group_list = list(group)
        by_id = {str(g["id"]): g for g in group_list}
        group_ids = [str(g["id"]) for g in group_list]

        html_item = book.get_item_with_href(str(path))
        if html_item is None:
            continue

        html_str = html_item.content
        pieces: list[tuple[str, str, int]] = []

        first = True
        for hr, name, text in html_split(html_str, str(path), group_ids):
            m = re.match(r"(.*)#(.*)", name)
            if not m:
                if not first:
                    continue
                first = False
                pieces.append((hr, text, 0))
                continue

            _, href_id = m.groups()
            if href_id != "init" and href_id not in by_id:
                continue

            index = 0 if href_id == "init" else int(by_id[href_id]["index"]) + 1
            pieces.append((hr, text, index))

        for name, text, _index in pieces:
            yield name, text


def _epub_html_items(args: RunArgs) -> Iterator[tuple[str, bytes | str]]:
    book = ebooklib_epub.read_epub(args.infile, options={"ignore_ncx": True})

    items = book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    html_items = {item.get_id(): item for item in items}

    reading_order = []
    for idref, _ in book.spine:
        if idref in html_items:
            reading_order.append(html_items[idref])

    for item in reading_order:
        yield item.id, item.content

def html_str_to_text(html: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        encoding="utf-8",
        delete=True,
    ) as fp:
        fp.write(html)
        fp.flush()
        return ebookconvert_to_text(fp.name)

def get_toc_epub(args: RunArgs):
    logger.info("Getting TOC of epub: %s", args.infile)
    book = ebooklib_epub.read_epub(args.infile)
    iterator = _epub_html_items(args)
    #iterator = _epub_by_fname(args, book)
    #iterator = _epub_by_title(args, book)

    for title, content in iterator:
        if args.run_mode == "name":
            yield TTSTrack(title=title, text="")
            continue

        text_content = content
        if not isinstance(content, str):
            text_content = html_str_to_text(content.decode())

        text_content = preprocess_text(text_content, args.unspace)
        yield TTSTrack(title=title, text=text_content)
