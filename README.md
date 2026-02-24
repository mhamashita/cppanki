# cpprefjp Anki Generator

Generates an Anki flashcard deck (`.apkg`) for all C++ reference entries on [cpprefjp.github.io](https://cpprefjp.github.io/).

Each card shows the C++ identifier (class / function / type) title on the front and the full formatted HTML reference page on the back — exactly as it appears on cpprefjp.

すぐに使う場合、AnkiのインストールされたWindows PCで.apkgファイルを開いてください

## Requirements

```bash
pip install requests beautifulsoup4 genanki tqdm
```

## Usage

### Full generation (all reference pages, ~2000+ cards)

```bash
python generate_cpprefjp_anki.py
```

This will:
1. Discover all pages under `reference/` via the GitHub API
2. Fetch each page from cpprefjp.github.io (with local caching)
3. Write `cpprefjp.apkg`

### Quick test (first 10 pages)

```bash
python generate_cpprefjp_anki.py --limit 10 --output test.apkg
```

### Options

| Option | Default | Description |
|---|---|---|
| `--limit N` | 0 (all) | Process only the first N pages |
| `--output FILE` | `cpprefjp.apkg` | Output filename |
| `--delay SECONDS` | `0.3` | Delay between HTTP requests |
| `--cache-dir DIR` | `.html_cache` | Cache directory for downloaded HTML |
| `--no-cache` | off | Disable HTML cache, always re-fetch |
| `--no-css` | off | Skip fetching site CSS |
| `--github-token TOKEN` | `$GITHUB_TOKEN` | GitHub PAT for higher API rate limit |

### Using a GitHub Token (recommended for full generation)

The GitHub API has a 60 request/hour rate limit without authentication. The page discovery step uses 3 API calls, so you won't hit the limit — but if you do:

```bash
python generate_cpprefjp_anki.py --github-token YOUR_TOKEN
# or
set GITHUB_TOKEN=YOUR_TOKEN
python generate_cpprefjp_anki.py
```

## Card Format

**Front** — The title area of the reference page:

```
std::ranges ::
in_in_out_result   ⚡ C++20
```

**Back** — Full reference documentation (HTML preserved):
- 概要 (Overview)
- メンバ変数・関数 (Members)
- 例 (Code examples)
- バージョン (Version info)
- 参照 (See also)

## Importing into Anki

1. Open Anki
2. **File → Import**
3. Select `cpprefjp.apkg`
4. Cards are added to the deck **"cpprefjp C++ Reference"**

Re-importing an updated `.apkg` will update existing cards (same deck/model IDs are used).

## Caching

Downloaded HTML is cached in `.html_cache/` by default. On subsequent runs, pages are read from the cache (much faster). Delete the cache directory to force re-download.
