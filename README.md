# nate_e2a

`nate_e2a` is a command-line ebook-to-audio pipeline. It extracts readable text from ebooks, splits the book into tracks, synthesizes speech with Piper, and writes a directory of MP3 files with synchronized text.

The default voice is Piper's `en_GB-alan-medium`. Model files are downloaded automatically on first use and cached locally.

## Features

- Converts PDF, EPUB, TXT, AZW3, MOBI, and DJVU input
- Uses ebook structure / table-of-contents information to split books into tracks
- Synthesizes speech locally with Piper
- Encodes 64 kbps MP3 files
- Writes ID3 metadata and embedded synchronized lyrics (SYLT)
- Writes matching `.lrc` lyric files for each track
- Preserves the extracted book text as `00-text.txt`
- Can extract/split text without running TTS

## Requirements

`nate_e2a` currently requires Python 3.10.

The Python environment is managed with [uv](https://docs.astral.sh/uv/). The TTS pipeline also invokes a few system executables:

- `ffmpeg` — required to encode MP3 files
- `id3v2` — required to write track metadata
- `ebook-convert` from Calibre — required for AZW3, MOBI, and DJVU input
- `qpdf` — only required when using `--rm-linearization` with a PDF

## Installation

Clone the repository and install the locked environment:

```bash
git clone https://github.com/natelastname/nate_e2a.git
cd nate_e2a
uv sync
```

Check the CLI:

```bash
uv run nate_e2a --help
```

## Usage

Convert an ebook to audio:

```bash
uv run nate_e2a tts book.epub
```

By default, output is written alongside the input file in a directory derived from the book's filename. To choose an output parent directory:

```bash
uv run nate_e2a tts book.pdf --outpath ~/Audiobooks
```

The first TTS run downloads the `en_GB-alan-medium` Piper model and its configuration into the platform-specific `nate_e2a` user cache.

### Extract text without TTS

`split-txt` runs the ebook parsing / splitting stage without synthesizing audio:

```bash
uv run nate_e2a split-txt book.epub
```

For command-specific options:

```bash
uv run nate_e2a tts --help
uv run nate_e2a split-txt --help
```

### PDF linearization workaround

Some PDFs can be normalized through `qpdf` before parsing:

```bash
uv run nate_e2a tts book.pdf --rm-linearization
```

## Output

A normal TTS run produces one numbered MP3 per extracted track, a matching LRC file, and a copy of the processed text:

```text
BookName/
├── 000001.mp3
├── 000001.lrc
├── 000002.mp3
├── 000002.lrc
├── ...
└── 00-text.txt
```

The MP3 files also contain ID3 metadata and embedded sentence-level synchronized lyrics.

## Development

Install the development dependencies and run the test suite with uv:

```bash
uv sync
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).
