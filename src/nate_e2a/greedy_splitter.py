#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-11-01T17:39:30-04:00

@author: nate
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Pattern, Sequence

# ---------- Strategy objects (all the knobs live here) ----------

@dataclass(slots=True)
class BoundaryStrategy:
    tiers: Sequence[Pattern[str]]                  # highest → lowest preference
    space: Pattern[str]                            # fallback word boundary
    para_split: Pattern[str]                       # strong paragraph break
    line_split: Pattern[str]                       # mild line break
    bullet_line: Pattern[str]                      # bullets/numbered lines
    abbreviations: set[str]

    def looks_abbreviation(self, s: str, dot_idx: int) -> bool:
        start = max(0, dot_idx - 12)
        window = s[start: dot_idx + 1].lower()
        for tok in self.abbreviations:
            if window.endswith(tok):
                return True
        # Initials: "U.S.", "J.R.R."
        if re.search(r"(\b[A-Z]\.){1,6}$", s[start: dot_idx + 1]):
            return True
        # Decimals/version numbers
        if 0 < dot_idx + 1 < len(s):
            if s[dot_idx - 1].isdigit() and s[dot_idx + 1].isdigit():
                return True
        return False


def default_strategy() -> BoundaryStrategy:
    return BoundaryStrategy(
        tiers=[
            re.compile(r"[.?!…][\"')\]]*\s"),     # sentence-ish
            re.compile(r"[;:—–-][\"')\]]*\s"),   # strong clause
            re.compile(r",[\"')\]]*\s"),         # weak clause
        ],
        space=re.compile(r"\s+"),
        para_split=re.compile(r"\n{2,}"),
        line_split=re.compile(r"\r?\n"),
        bullet_line=re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+"),
        abbreviations={
            # titles / names
            "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
            # refs
            "no.", "nos.", "vol.", "ch.", "sec.", "fig.", "eq.", "pp.", "p.",
            # latin
            "i.e.", "e.g.", "etc.", "cf.", "viz.", "vs.", "al.", "ca.",
            # misc
            "st.", "mt.", "dept.", "est.", "inc.", "co.", "corp.",
        },
    )


# ---------- Greedy engine (uses the strategy) ----------

@dataclass(slots=True)
class GreedySplitConfig:
    max_len: int = 300
    target_len: int = 240
    min_len: int = 40
    join_hardwraps: bool = True
    keep_bullets_as_units: bool = True
    allow_early_cut_tier_index: int | None = None
    """
    If set (e.g., 0), allow tiers with index <= value to cut even before min_len.
    Useful when you want periods to beat min_len.
    """

class GreedySentenceSplitter:
    def __init__(
        self,
        cfg: GreedySplitConfig | None = None,
        strategy: BoundaryStrategy | None = None,
    ):
        self.cfg = cfg or GreedySplitConfig()
        self.st = strategy or default_strategy()

    def split(self, text: str) -> List[str]:
        return list(self.iter_sentences(text))

    def iter_sentences(self, text: str) -> Iterator[str]:
        if not text:
            return
        for para in self.st.para_split.split(text.strip()):
            if not para.strip():
                continue
            yield from self._split_paragraph(para)

    def _split_paragraph(self, para: str) -> Iterator[str]:
        cfg, st = self.cfg, self.st
        lines = st.line_split.split(para)

        if cfg.join_hardwraps:
            merged: List[str] = []
            buf: List[str] = []

            def flush():
                if buf:
                    merged.append(" ".join(buf))
                    buf.clear()

            for ln in lines:
                if cfg.keep_bullets_as_units and st.bullet_line.match(ln):
                    flush()
                    merged.append(ln.strip())
                else:
                    buf.append(ln.strip())
            flush()
            blocks = merged
        else:
            blocks = [ln.strip() for ln in lines if ln.strip()]

        for block in blocks:
            if not block:
                continue
            if cfg.keep_bullets_as_units and st.bullet_line.match(block) and len(block) <= cfg.max_len:
                yield block
                continue
            yield from self._greedy_chunk(block)

    def _greedy_chunk(self, s: str) -> Iterator[str]:
        cfg, st = self.cfg, self.st
        n = len(s)
        i = 0
        while i < n:
            lo = i
            soft_hi = min(n, i + cfg.target_len)
            hard_hi = min(n, i + cfg.max_len)
            cut = self._best_cut(s, lo, soft_hi, hard_hi)
            if cut <= lo:
                cut = max(lo + cfg.min_len, min(n, lo + cfg.max_len))
            seg = s[lo:cut].strip()
            if seg:
                yield seg
            i = cut
            if i < n and s[i].isspace():
                i += 1

    def _best_cut(self, s: str, lo: int, soft_hi: int, hard_hi: int) -> int:
        cfg, st = self.cfg, self.st
        n = len(s)
        if hard_hi > n:
            hard_hi = n

        def ok_abbrev(end_idx: int) -> bool:
            # end_idx is the char index of the punctuation (usually '.')
            return not st.looks_abbreviation(s, end_idx)

        for tier_idx, pat in enumerate(st.tiers):
            last_ok = -1
            for m in pat.finditer(s, lo, hard_hi):
                end = m.end()
                length = end - lo

                # Walk back over included whitespace to find the punctuation index if present
                end_minus = end - 1
                while end_minus > lo and s[end_minus - 1].isspace():
                    end_minus -= 1

                # Respect min_len, unless allowed to cut early for top tiers
                early_ok = (
                    cfg.allow_early_cut_tier_index is not None
                    and tier_idx <= cfg.allow_early_cut_tier_index
                )
                if not early_ok and length < cfg.min_len:
                    continue

                # Avoid abbreviations like "Dr.", "U.S.", or decimals
                if end_minus >= 0 and s[end_minus] == '.' and not ok_abbrev(end_minus):
                    continue

                last_ok = end
                if end <= soft_hi:
                    return end
            if last_ok != -1:
                return last_ok

        # Fallback: last whitespace before the hard cap
        last_space = -1
        for m in st.space.finditer(s, lo, hard_hi):
            end = m.end()
            if end - lo >= cfg.min_len:
                last_space = end
        if last_space != -1:
            return last_space

        return hard_hi
