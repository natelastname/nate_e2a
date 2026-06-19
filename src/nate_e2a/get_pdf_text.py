# -*- coding: utf-8 -*-
"""
Created on 2025-06-21T10:59:55-04:00

@author: nate
"""
import io
import re
import statistics
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator

import cv2
import numpy as np
import popplerqt5
import tqdm
from loguru import logger
from PIL import Image
from PyQt5.QtCore import QBuffer, QPointF, QRectF

from .preprocess import preprocess_text_lite
from .types import RunArgs, hline_char, page_char, toc_item_char


class SplitKind(Enum):
    HLINE = "hline"
    TOC = "toc"


@dataclass(frozen=True)
class PopplerPdfTocItem:
    title: str
    destination: popplerqt5.Poppler.LinkDestination


@dataclass(frozen=True)
class PageSplit:
    y_px: int
    kind: SplitKind
    toc_item: PopplerPdfTocItem | None = None

    @property
    def delimiter(self) -> str:
        if self.kind is SplitKind.HLINE:
            return hline_char
        if self.kind is SplitKind.TOC:
            return toc_item_char
        raise ValueError(f"unknown split kind: {self.kind}")


def iter_toc_nodes(node, level: int = 0) -> Iterator[tuple[int, object]]:
    children = node.childNodes()
    for i in range(children.length()):
        child = children.at(i)
        yield level, child
        yield from iter_toc_nodes(child, level + 1)


def _node_attr(node, name: str) -> str:
    attr = node.attributes().namedItem(name)
    if attr.isNull():
        return ""
    return attr.nodeValue() or ""


def iter_poppler_toc_items(path: str | Path) -> Iterator[tuple[int, PopplerPdfTocItem]]:
    doc = popplerqt5.Poppler.Document.load(str(path))
    if doc is None:
        raise RuntimeError(f"failed to load PDF: {path}")

    logger.info("Reading PDF table of contents...")
    toc = doc.toc()

    if not toc:
        # Synthetic root pointing to page 1.
        dest = popplerqt5.Poppler.LinkDestination("1;1;0;0;0;0;1;1;1;0")
        yield 0, PopplerPdfTocItem("root", dest)
        return

    last_page = 0

    for level, node in iter_toc_nodes(toc):
        title = node.nodeName() or ""
        dest_raw = _node_attr(node, "Destination")
        dest_name = _node_attr(node, "DestinationName")

        if dest_raw:
            dest = popplerqt5.Poppler.LinkDestination(dest_raw)
        elif dest_name:
            dest = doc.linkDestination(dest_name)
        else:
            logger.warning("Skipping TOC node with no destination: {!r}", title)
            continue

        page_no = dest.pageNumber()

        if page_no < 1:
            logger.warning("Skipping TOC node with invalid page number: {!r} -> {}", title, page_no)
            continue

        if page_no < last_page:
            logger.warning(
                "TOC page numbers are non-monotonic: previous={}, current={}, title={!r}",
                last_page,
                page_no,
                title,
            )

        last_page = page_no
        yield level, PopplerPdfTocItem(title, dest)


def get_toc_dict(args: RunArgs) -> dict[int, list[PopplerPdfTocItem]]:
    """
    Return TOC items keyed by Poppler's 1-based page number.
    """
    toc_items: dict[int, list[PopplerPdfTocItem]] = {}

    for _level, item in iter_poppler_toc_items(args.infile):
        page_no = item.destination.pageNumber()
        toc_items.setdefault(page_no, []).append(item)

    return toc_items


def qimage_to_pil(qimage) -> Image.Image:
    buff0 = QBuffer()
    buff0.open(QBuffer.ReadWrite)

    if not qimage.save(buff0, "PNG"):
        raise RuntimeError("failed to encode rendered PDF page as PNG")

    data = bytes(buff0.data())
    return Image.open(io.BytesIO(data)).convert("RGB")


def detect_horizontal_lines(gray_img: np.ndarray, kernel_width: int = 16) -> np.ndarray:
    """
    Return a binary-ish mask where horizontal line-like structures are white.
    """
    if gray_img.ndim != 2:
        raise ValueError(f"expected grayscale image, got shape={gray_img.shape}")

    _, binary = cv2.threshold(
        gray_img,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)


def top_k_indices_above(values: np.ndarray, *, k: int, min_value: float) -> list[int]:
    valid = np.where(values > min_value)[0]
    if len(valid) == 0:
        return []

    valid_values = values[valid]
    local_top = np.argsort(-valid_values)[: min(k, len(valid_values))]
    return valid[local_top].tolist()


def collapse_adjacent_splits(splits: Iterable[PageSplit]) -> list[PageSplit]:
    """
    Collapse consecutive pixel rows into one split at the median row.

    If TOC and hline splits collide, TOC wins, because it carries semantic
    structure from the PDF outline.
    """
    sorted_splits = sorted(splits, key=lambda s: s.y_px)
    if not sorted_splits:
        return []

    result: list[PageSplit] = []
    block: list[PageSplit] = [sorted_splits[0]]

    def flush_block() -> None:
        ys = [s.y_px for s in block]
        y_median = int(statistics.median(ys))

        toc_splits = [s for s in block if s.kind is SplitKind.TOC]
        if toc_splits:
            chosen = toc_splits[0]
            if len(toc_splits) > 1:
                logger.warning("Multiple TOC items point to roughly the same page location")
            result.append(PageSplit(y_median, SplitKind.TOC, chosen.toc_item))
        else:
            result.append(PageSplit(y_median, SplitKind.HLINE))

    for split in sorted_splits[1:]:
        if split.y_px == block[-1].y_px + 1:
            block.append(split)
        else:
            flush_block()
            block = [split]

    flush_block()
    return result


def page_toc_splits(
    toc_items: list[PopplerPdfTocItem],
    *,
    image_height: int,
) -> list[PageSplit]:
    splits: list[PageSplit] = []

    for item in toc_items:
        top = item.destination.top()

        # Poppler destinations can be weird. Treat top as normalized when in
        # [0, 1], otherwise clamp defensively.
        top = max(0.0, min(1.0, float(top)))
        y_px = int(round(top * image_height))
        y_px = max(0, min(image_height - 1, y_px))

        logger.info("TOC split: page={}, y_px={}, title={!r}", item.destination.pageNumber(), y_px, item.title)
        splits.append(PageSplit(y_px, SplitKind.TOC, item))

    return splits


def page_hline_splits(
    pil_img: Image.Image,
    *,
    top_k: int = 5,
    min_row_fraction: float = 0.10,
) -> list[PageSplit]:
    gray = np.array(pil_img.convert("L"))
    mask = detect_horizontal_lines(gray)

    binary = np.where(mask > 0, 1, 0)
    row_fractions = binary.sum(axis=1) / binary.shape[1]

    ys = top_k_indices_above(row_fractions, k=top_k, min_value=min_row_fraction)
    return [PageSplit(int(y), SplitKind.HLINE) for y in ys]


def pixel_y_to_page_y(y_px: int, *, image_height: int, page_height: float) -> float:
    """
    Convert rendered-image pixel Y coordinates to Poppler page coordinates.
    """
    if image_height <= 1:
        return 0.0
    return y_px / (image_height - 1) * page_height


def extract_text_by_splits(page, splits: list[PageSplit], image_height: int) -> str:
    size = page.pageSizeF()
    page_width = size.width()
    page_height = size.height()

    parts: list[str] = []
    y0 = 0.0

    # Always include a final split at the bottom so the last segment is emitted.
    bottom = PageSplit(image_height - 1, SplitKind.HLINE)
    all_splits = collapse_adjacent_splits([*splits, bottom])

    for split in all_splits:
        y1 = pixel_y_to_page_y(split.y_px, image_height=image_height, page_height=page_height)

        if y1 < y0:
            logger.warning("Skipping inverted text rectangle: y0={}, y1={}", y0, y1)
            continue

        rect = QRectF(QPointF(0.0, y0), QPointF(page_width, y1))
        segment = page.text(rect)

        if segment:
            parts.append(segment)

        parts.append(split.delimiter)
        y0 = y1

    return "\n".join(parts)


def cleanup_delimiters(text: str) -> str:
    delim_chars = re.escape(hline_char + toc_item_char)
    page = re.escape(page_char)

    # Remove delimiter noise immediately before page breaks.
    text = re.sub(rf"(?:[{delim_chars}]|\s)+{page}", page_char, text)

    # Collapse repeated blank lines around structural delimiters.
    text = re.sub(rf"\n{{3,}}([{delim_chars}{page}])", r"\n\1", text)
    text = re.sub(rf"([{delim_chars}{page}])\n{{3,}}", r"\1\n", text)

    return text


def get_text_poppler_line_split(args: RunArgs) -> str:
    """
    Extract PDF text using Poppler, inserting structural delimiters at:

    - horizontal line detections from rendered page images
    - PDF TOC destinations from the document outline

    Poppler page numbers in TOC destinations are 1-based.
    Rendered page loop indices are 0-based.
    """
    doc = popplerqt5.Poppler.Document.load(str(args.infile))
    if doc is None:
        raise RuntimeError(f"failed to load PDF: {args.infile}")

    toc_by_page = get_toc_dict(args)
    pages: list[str] = []

    pbar = tqdm.tqdm(total=doc.numPages(), ncols=0, mininterval=1)

    try:
        for page_index in range(doc.numPages()):
            pbar.update()

            page = doc.page(page_index)
            if page is None:
                logger.warning("Skipping unreadable page index {}", page_index)
                continue

            qimage = page.renderToImage()
            pil_img = qimage_to_pil(qimage)
            image_height = pil_img.height

            hline_splits = page_hline_splits(pil_img)
            toc_splits = page_toc_splits(
                toc_by_page.get(page_index + 1, []),
                image_height=image_height,
            )

            splits = collapse_adjacent_splits([*hline_splits, *toc_splits])
            page_text = extract_text_by_splits(page, splits, image_height)

            pages.append(page_text)
            pages.append(page_char)

    finally:
        pbar.close()

    text = "\n".join(pages)
    text = cleanup_delimiters(text)
    text = preprocess_text_lite(text, args.unspace)
    return text
