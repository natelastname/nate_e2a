#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-01-12T08:30:13-05:00

@author: nate
"""
import gzip
import os
import re
import unicodedata

import hakilo
import omterms
import wordninja
from transliterate import translit

from .types import page_char


class Unspacer():
    def __init__(self):
        self.word_file = os.path.dirname(os.path.abspath(wordninja.__file__))
        self.word_file = os.path.join(self.word_file, 'wordninja','wordninja_words.txt.gz')
        with gzip.open(self.word_file) as f:
            self.words = f.read().decode().split()

        self.letters = set()
        for word in self.words:
            word_letters = set([l0 for l0 in word])
            self.letters = self.letters.union(word_letters)

        self.letters = list(self.letters)

    def _toke(self, text0: str):
        if not text0:
            return text0
        flag = False
        if text0[0] in self.letters:
            flag = True
        out_text = ""
        for letter in text0:

            # If the letter is in the corpus or it is whitespace,
            cond1 = letter.lower() in self.letters
            cond1 = cond1 or re.match('\\s', letter)

            if not cond1 and flag == False:
                # Continue non-char block
                out_text += letter
                continue
            elif not cond1 and flag == True:
                # char block -> non-char block
                yield flag, out_text
                out_text = letter
                flag = False
                continue
            elif cond1 and flag == False:
                # non-char block -> char block
                yield flag, out_text
                out_text = letter
                flag = True
                continue
            elif cond1 and flag == True:
                # non-char block -> char block
                out_text += letter
                continue
            raise Exception(f'unhandled case: "{letter}", {flag} ')
        yield flag, out_text

    def unspace(self, text0: str):
        terms = omterms.interface.extract_terms(text0)
        terms = [t0 for t0 in terms['Term'].unique()]

        self.words = list(set(self.words).union(set(terms)))

        out_text = ""
        for i, (flag, block) in enumerate(self._toke(text0)):
            if flag:
                block = wordninja.split(''.join(block.split()))
                block = ' '.join(block)
            else:
                block += ''
            #print(f'{i:5}: "{block}", {flag}')
            out_text = out_text + block
        out_text = re.sub("\\s*'\\s*", "'", out_text)
        #re.search(pattern, text, re.IGNORECASE)
        #out_text = fix_spacing(out_text.strip())
        return out_text.strip()

######################################################################
# Text conversion / processing
######################################################################

def yank_re(re0, str0):
    out0 = ""
    for m0 in re.finditer(re0, str0):
        out0 += m0.group()
    out1 = re.sub(re0, '', str0)
    return out1, out0

def split_hakilo(txt):
    out_lines = []
    found = False
    for line in hakilo.split_text(txt):
        line = re.sub('[\r\n\f]+', ' ', line)
        yield line
    return


def hakilo_sentences(text):
    page_num = 0
    page = ""
    gen0 = e2a.preprocess.split_hakilo(text)
    for i, sentence in enumerate(gen0):
        yanked_from, yanked = yank_re(f'[{page_char}]', sentence)
        line = yanked_from+yanked
        yield line

def pp_remove_newlines(text):
    filtered = re.sub('(\\s*\n)+', '\n', text)
    return filtered

def pp_remove_watermarks(text):
    filtered = re.sub('\\*+ebook converter DEMO Watermarks\\*+', '', text)
    return filtered

def pp_truncate_text(text):
    res = text.split('\n')[0:300]
    return "\n".join(res)

def pp_break_paragraphs(text):
    res = text.split('\n')
    newlines = []
    for line in res:
        temp = re.sub('[1-9]', '', line)
        if temp.strip().endswith(('.', ':')):
            line = line + "\n"
        newlines.append(line)
    text = "\n".join(newlines)
    text = re.split('\\s*\n\\s*\n', text)
    newlines = []
    for line in text:
        newline = re.sub('\n', ' ', line)
        newlines.append(newline)
    text = '\n\n'.join(newlines)
    return text

def pp_fix_formfeeds(text):

    # Pre-compile for speed if you call this a lot
    _SOFT_OR_ZERO_WIDTH = re.compile(r'[\u00AD\u200B\u200C\u200D]')  # soft hyphen & zero-widths
    # Hyphen-like chars that are used for word breaks (not em/en dashes)
    _WORD_HYPHEN = r'[-\u2010\u2011\u00AD]'  # -, hyphen, non-breaking hyphen, soft hyphen
    # 1) Join hyphenated words that break across newline or form-feed
    _JOIN_HYPHEN_BREAK = re.compile(
        rf'(\w){_WORD_HYPHEN}\s*(?:\r?\n|\r|\x0c)\s*(?=[A-Za-z])'
    )
    # 2) Replace any whitespace + form-feed + whitespace with a paragraph break
    _FORMFEED_TO_PARA = re.compile(r'\s*\x0c+\s*')
    # 3) Normalize multiple blank lines and excess spaces
    _MULTIBLANKS = re.compile(r'\n{3,}')
    _MULTISPACES = re.compile(r'[ \t]{2,}')
    # Normalize line endings early
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Remove soft/zero-width characters that confuse tokenization/tts
    text = _SOFT_OR_ZERO_WIDTH.sub('', text)
    # Join hyphenated words that were split by newline or form-feed:
    # "inter-\n national" -> "international", "co-\x0c operate" -> "cooperate"
    text = _JOIN_HYPHEN_BREAK.sub(r'\1', text)
    # Convert form-feeds to paragraph breaks; this keeps a pause for TTS
    text = _FORMFEED_TO_PARA.sub('\n\n', text)
    # Collapse silly spacing
    text = _MULTIBLANKS.sub('\n\n', text)
    text = _MULTISPACES.sub(' ', text)

    return text


def pp_expand_honorifics(text):
    # OPening parens, quotes..
    text = re.sub('\\s+Mr\\.', ' Mister', text)
    text = re.sub('\\s+Mrs\\.', ' Misses', text)
    text = re.sub('\\s+Ms\\.', ' Miss', text)
    text = re.sub('\\s+Fr\\.', ' Father', text)
    text = re.sub('\\s+St\\.', ' Saint', text)
    text = re.sub('\\s+Pvt\\.', ' Private', text)
    text = re.sub('\\s+Sgt\\.', ' Sargeant', text)
    text = re.sub('\\s+Lt\\.', ' Lieutenant', text)
    text = re.sub('\\s+Capt\\.', ' Captain', text)
    text = re.sub('\\s+Col\\.', ' Colonel', text)
    text = re.sub('\\s+Adm\\.', ' Admiral', text)
    text = re.sub('\\s+Rev\\.', ' Reverend', text)
    return text

def filter_non_printable(s0: str):
    s0 = s0.replace('\t', " ")
    chars = []
    filtered = ['Cc']
    for char0 in s0:
        cat = unicodedata.category(char0)
        if cat in filtered:
            breakpoint()
            continue
        chars.append(char0)
    out_str = ''.join(chars)
    return out_str

def do_translit(text):
    found = {}
    for char in text:
        if unicodedata.name(char, "").startswith("GREEK"):
            found['el'] = True
        if unicodedata.name(char, "").startswith("CYRILLIC"):
            found['ru'] = True
    for key, val in found.items():
        text = translit(text, key, reversed=True)
    return text

def preprocess_text(text, unspace: bool):
    str0 = '\xc2\xad'
    text = re.sub(f"[{str0}]", '', text)
    text = re.sub('[\x0c]', e2a.types.page_char, text)
    text = pp_remove_newlines(text)
    text = pp_break_paragraphs(text)
    text = pp_fix_formfeeds(text)
    text = pp_expand_honorifics(text)

    gen0 = hakilo_sentences(text)
    result = ""
    unspacer = Unspacer()
    for sentence in gen0:
        sent = filter_non_printable(sentence)
        if sent.strip() == "":
            continue
        s2 = do_translit(sent)
        if unspace:
            s2 = unspacer.unspace(s2)
        result += s2 + "\n"
    return result


def preprocess_text_lite(text, unspace: bool):
    str0 = '\xc2\xad'
    text = re.sub(f"[{str0}]", '', text)
    text = re.sub('[\x0c]', page_char, text)
    pages = text.split(page_char)
    out_pages = []
    for page in pages:
        result = pp_fix_formfeeds(page)
        out_pages.append(result)
    text = page_char.join(out_pages)
    return text


