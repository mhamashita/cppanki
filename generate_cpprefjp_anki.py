#!/usr/bin/env python3
"""
generate_cpprefjp_anki.py

Scrapes https://cpprefjp.github.io (the C++ Japanese reference) and generates
an Anki .apkg flashcard file.

Front of card : The title section of the reference page
                (namespace breadcrumb + class/function name + C++ version badge)
Back of card  : Full HTML main-pane content (below the title)

Usage:
    python generate_cpprefjp_anki.py [--limit N] [--output FILE] [--delay SECONDS]
                                     [--cache-dir DIR] [--no-cache]

Requirements:
    pip install requests beautifulsoup4 genanki tqdm
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional

import genanki
import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
REPO_OWNER = "cpprefjp"
REPO_NAME = "cpprefjp.github.io"
SITE_BASE = "https://cpprefjp.github.io"

# We only care about the reference/ directory for C++ library reference
TARGET_DIRS = ["reference"]

DECK_NAME = "cpprefjp C++ Reference"
DECK_ID = 1234567890  # Fixed ID so re-imports update instead of duplicate
MODEL_ID = 9876543210

DEFAULT_OUTPUT = "cpprefjp.apkg"
DEFAULT_DELAY = 0.3  # seconds between requests

# ---------------------------------------------------------------------------
# CSS constants
# ---------------------------------------------------------------------------

# Base CSS for the Anki model (shared across all cards)
# Site CSS (Pygments + kunai) is fetched at runtime and appended to this.
ANKI_BASE_CSS = """
.card {
  font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN",
               "Hiragino Sans", Meiryo, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: #333;
  background: #fff;
  margin: 0;
  padding: 10px;
  text-align: left;
}
"""

# cpprefjp-specific CSS for Anki card rendering.
# Handles all structural and typographic styling. Code/pre/table/link rules
# are defined here; the site's Pygments CSS (fetched separately) handles
# syntax-highlight token colours.
CPPREFJP_CSS = """
/* Identifier type badge (e.g. "class template", "function template") */
.identifier-type {
  display: inline-block;
  font-size: 11px;
  font-weight: bold;
  color: #fff;
  background: #6c757d;
  border-radius: 3px;
  padding: 2px 7px;
  margin-bottom: 4px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

/* Header file badge (e.g. "<algorithm>") */
div.header {
  display: inline-block;
  font-size: 12px;
  font-family: monospace;
  color: #555;
  background: #f0f0f0;
  border: 1px solid #ccc;
  border-radius: 3px;
  padding: 2px 8px;
  margin-bottom: 8px;
}

/* h1 title */
h1[itemprop="name"] {
  font-size: 24px;
  font-weight: bold;
  margin: 6px 0 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid #0366d6;
  color: #1a1a2e;
}

/* namespace prefix in h1 (e.g. "std::") */
h1 .namespace {
  color: #888;
  font-size: 18px;
}

/* main token in h1 (e.g. "binary_search") */
h1 .token {
  color: #0366d6;
}

/* Section headers */
h2 {
  font-size: 18px;
  font-weight: bold;
  margin-top: 24px;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #e1e4e8;
  color: #24292e;
}
h3 { font-size: 15px; font-weight: bold; margin-top: 16px; margin-bottom: 6px; }
h4 { font-size: 14px; font-weight: bold; margin-top: 12px; }

/* Inline code — vertical padding=0 to prevent expanding prose line height */
code {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
  background: #f6f8fa;
  border-radius: 3px;
  padding: 0 0.3em;
  color: #24292e;
}

/* Code blocks (.codehilite = Pygments wrapper) */
.codehilite {
  background: #f6f8fa;
  border: 1px solid #e1e4e8;
  border-radius: 6px;
  padding: 12px 14px;
  overflow-x: auto;
  margin: 8px 0;
}

/*
 * FIX: Uniform line spacing in all pre blocks.
 * .card sets line-height:1.6 which pre inherits. Any inline child
 * (<a>, <code>, <span>) that has different box metrics makes that line
 * taller. Setting an explicit value on pre and inheriting it down
 * through all descendants ensures every line is the same height.
 */
pre {
  line-height: 1.4;
}
pre * {
  line-height: inherit;
}

.codehilite pre {
  margin: 0;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
  white-space: pre;
  color: #24292e;
  background: transparent;
}

/* pre code: reset inline-code styles so they don't affect code-block lines */
pre code {
  background: none;
  border: none;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
}

/* Plain pre blocks (output sections, algorithm diagrams, etc.) */
pre:not([class]) {
  background: #f6f8fa;
  border: 1px solid #e1e4e8;
  border-radius: 6px;
  padding: 10px 14px;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
  overflow-x: auto;
  margin: 8px 0;
}

/* .codehilite pre must come AFTER pre:not([class]) so same-specificity cascade
   wins and cancels the box that pre:not([class]) would otherwise add. */
.codehilite pre {
  background: none;
  border: none;
  border-radius: 0;
  padding: 0;
  margin: 0;
  overflow-x: visible;
}

/* Tables */
table {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  font-size: 14px;
}
th, td {
  border: 1px solid #dfe2e5;
  padding: 6px 12px;
  text-align: left;
}
th {
  background: #f6f8fa;
  font-weight: bold;
}
tr:nth-child(even) { background: #fafafa; }

/* Lists */
ul, ol { padding-left: 24px; margin: 6px 0; }
li { margin: 3px 0; }

/* Links */
a { color: #0366d6; text-decoration: none; }
a:hover { text-decoration: underline; }

/* cpprefjp defined-word tooltip indicator */
.cpprefjp-defined-word {
  border-bottom: 1px dashed #888;
  cursor: help;
}

/* Code example containers */
.yata { margin: 8px 0; }

/* C++ version badge in h1 */
.since-cpp { font-size: 13px; color: #888; margin-left: 8px; font-weight: normal; }
"""

# Injected into every card's HTML (both front and back)
CARD_HEAD_EXTRAS = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
"""

# ---------------------------------------------------------------------------
# Anki model + deck
# ---------------------------------------------------------------------------

def make_model(extra_css: str = "") -> genanki.Model:
    """Create the Anki note model with front/back HTML fields.
    
    extra_css: additional CSS fetched from the site (e.g. Pygments theme).
    The CSS is stored once in the model, shared across all cards.
    """
    model_css = ANKI_BASE_CSS + CPPREFJP_CSS
    if extra_css:
        model_css += "\n" + extra_css
    return genanki.Model(
        MODEL_ID,
        "cpprefjp Reference Model",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
            {"name": "URL"},
        ],
        templates=[
            {
                "name": "cpprefjp Card",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}<hr id='answer'>{{Back}}",
            }
        ],
        css=model_css,
    )


def make_deck() -> genanki.Deck:
    return genanki.Deck(DECK_ID, DECK_NAME)


# ---------------------------------------------------------------------------
# GitHub API — discover all HTML pages under target directories
# ---------------------------------------------------------------------------

def get_tree_recursive(owner: str, repo: str, branch: str = "master", session: Optional[requests.Session] = None) -> list[dict]:
    """
    Use the GitHub Git Trees API (recursive) to get all files in the repo.
    Returns a list of tree entries with 'path', 'type', 'url'.
    """
    if session is None:
        session = requests.Session()

    # Try to get the commit SHA for the branch
    ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{branch}"
    resp = session.get(ref_url, timeout=30)
    resp.raise_for_status()
    commit_sha = resp.json()["object"]["sha"]

    # Get commit to find the tree SHA
    commit_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits/{commit_sha}"
    resp = session.get(commit_url, timeout=30)
    resp.raise_for_status()
    tree_sha = resp.json()["tree"]["sha"]

    # Get full recursive tree
    tree_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1"
    resp = session.get(tree_url, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if data.get("truncated"):
        print("WARNING: GitHub tree result was truncated. Some pages may be missing.", file=sys.stderr)

    return data.get("tree", [])


def filter_reference_pages(tree_entries: list[dict], target_dirs: list[str]) -> list[str]:
    """
    Filter tree entries to only HTML files inside target directories
    (e.g., reference/).  Returns a list of relative paths.
    """
    result = []
    for entry in tree_entries:
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        # Must be under one of the target dirs and end in .html
        if not path.endswith(".html"):
            continue
        # Check if it starts with one of our target directories
        if not any(path.startswith(d + "/") for d in target_dirs):
            continue
        # Skip index/top-level category pages (no sub-path component after dir)
        # e.g. reference/algorithm.html is a category index — skip it
        # reference/algorithm/ranges_in_in_out_result.html — keep it
        parts = path.split("/")
        if len(parts) < 3:
            continue
        result.append(path)
    return result


# ---------------------------------------------------------------------------
# Fetch CSS from cpprefjp site
# ---------------------------------------------------------------------------

def fetch_site_css(session: requests.Session) -> str:
    """
    Fetch only the Pygments syntax-highlight CSS from cpprefjp.github.io
    (~7 KB). Structural/typographic CSS is handled by CPPREFJP_CSS above.
    """
    css_parts = []
    try:
        resp = session.get(f"{SITE_BASE}/", timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href", "")
            if not href:
                continue
            # Only the Pygments stylesheet — skip the heavy kunai bundle
            if "pygments" not in href.lower():
                continue
            if href.startswith("/"):
                href = SITE_BASE + href
            elif not href.startswith("http"):
                href = SITE_BASE + "/" + href
            try:
                css_resp = session.get(href, timeout=20)
                css_resp.raise_for_status()
                css_parts.append(css_resp.text)
            except Exception as e:
                print(f"  [WARN] Could not fetch CSS {href}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] Could not fetch site CSS: {e}", file=sys.stderr)

    return "\n".join(css_parts)


# ---------------------------------------------------------------------------
# HTML fetching & parsing
# ---------------------------------------------------------------------------

def fetch_page_html(url: str, session: requests.Session, cache_dir: Optional[Path] = None) -> Optional[str]:
    """
    Fetch an HTML page, using a local file cache if cache_dir is set.
    Returns the raw HTML string or None on failure.
    """
    if cache_dir is not None:
        # Use URL hash as cache filename
        key = hashlib.md5(url.encode()).hexdigest()
        cache_file = cache_dir / f"{key}.html"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"  [ERROR] Failed to fetch {url}: {e}", file=sys.stderr)
        return None

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(html, encoding="utf-8")

    return html


def _remove_invalid_elements(soup: BeautifulSoup) -> None:
    """Remove elements that cause issues in Anki (custom HTML tags, scripts, etc.)."""
    # Remove Google Custom Search elements (gcse:*) — causes genanki warning
    for tag in soup.find_all(re.compile(r'^gcse:', re.I)):
        tag.decompose()
    # Also remove containers that held them
    for div in soup.find_all("div", class_="google-search-result"):
        div.decompose()
    # Remove script and style tags from body content
    for tag in soup.find_all(["script"]):
        tag.decompose()


def extract_main_content(html: str, page_url: str, site_css: str) -> Optional[tuple[str, str]]:
    """
    Parse the HTML page and extract the front and back content.

    cpprefjp page structure:
      <main id="main">
        <div class="container-fluid">
          <div class="row">
            <div class="col-sm-9 ...">          ← content column
              <div class="google-search-result"> ← SKIP
              <div class="content-header">       ← breadcrumb
              <div class="edit-button">          ← SKIP
              <div class="content-body">         ← THE CONTENT:
                <div class="identifier-type">   ← type label (e.g. "class template")
                <div class="header">            ← header (<algorithm>)
                <h1>                            ← TITLE (front card)
                <div itemprop="articleBody">    ← BODY (back card)

    Returns (front_html, back_html) or None if parsing fails.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Clean up invalid/unwanted elements first
    _remove_invalid_elements(soup)

    # Try to find the precise content-body div (cpprefjp-specific)
    content_body = soup.find("div", class_="content-body")

    if content_body is not None:
        # Precise extraction using known structure
        h1 = content_body.find("h1")
        if h1 is None:
            return None

        # FRONT: identifier-type + header div + h1  
        front_parts = []
        id_type = content_body.find("div", class_="identifier-type")
        header_div = content_body.find("div", class_="header")
        if id_type:
            front_parts.append(str(id_type))
        if header_div:
            front_parts.append(str(header_div))
        front_parts.append(str(h1))
        front_inner = "".join(front_parts)

        # BACK: article body div
        article_body = content_body.find("div", attrs={"itemprop": "articleBody"})
        if article_body:
            back_inner = str(article_body)
        else:
            # Fallback: everything after the h1
            back_parts = []
            after_h1 = False
            for child in content_body.children:
                if not after_h1:
                    if isinstance(child, Tag) and (child == h1 or child.find("h1") is not None):
                        after_h1 = True
                    continue
                back_parts.append(str(child))
            back_inner = "".join(back_parts)

    else:
        # Fallback for non-standard page layout
        main = (
            soup.find(id="main")
            or soup.find("article")
            or soup.find("main")
            or soup.find("div", class_="markdown-body")
            or soup.body
        )
        if main is None:
            return None

        h1 = main.find("h1")
        if h1 is None:
            return None

        # Collect up to and including h1 as front
        front_parts = []
        collecting = True
        for child in main.children:
            if not collecting:
                break
            if isinstance(child, Tag):
                front_parts.append(str(child))
                if child == h1 or child.find("h1") is not None:
                    collecting = False
        front_inner = "".join(front_parts)

        # Collect after h1 as back
        back_parts = []
        after_h1 = False
        for child in main.children:
            if not after_h1:
                if isinstance(child, Tag) and (child == h1 or child.find("h1") is not None):
                    after_h1 = True
                continue
            back_parts.append(str(child))
        back_inner = "".join(back_parts)

    # Rewrite relative links to absolute links so they work from inside Anki
    base_url = page_url.rsplit("/", 1)[0] + "/"

    def make_absolute(html_fragment: str) -> str:
        """Convert relative href/src attributes to absolute URLs."""
        # Simple regex replacement for href and src
        def replace_attr(m):
            attr = m.group(1)
            val = m.group(2)
            # Skip already-absolute, anchors, javascript:
            if val.startswith(("http://", "https://", "#", "javascript:", "data:")):
                return m.group(0)
            if val.startswith("/"):
                return f'{attr}="{SITE_BASE}{val}"'
            return f'{attr}="{base_url}{val}"'

        return re.sub(r'(href|src)="([^"]*)"', replace_attr, html_fragment)

    front_inner = make_absolute(front_inner)
    back_inner = make_absolute(back_inner)

    # --- Wrap in self-contained HTML stubs ---
    # NOTE: The Anki model CSS (CPPREFJP_CSS + Pygments) is applied automatically
    # by Anki to the .card wrapper.  We do NOT embed the CSS inside each field
    # because that would bloat the .apkg file (CSS × number of cards).
    # Both front and back get the same minimal wrapper so layout is consistent.

    front_html = f"""{CARD_HEAD_EXTRAS}<div class="cpprefjp-card" style="padding:12px;">{front_inner}</div>"""

    back_html = f"""{CARD_HEAD_EXTRAS}<div class="cpprefjp-card" style="padding:12px;">{back_inner}</div>"""

    return front_html, back_html


def extract_sort_field(html: str) -> str:
    """Extract a sort string (the h1 text) for ordering notes in Anki."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Anki flashcards from cpprefjp.github.io C++ reference pages."
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Only process the first N pages (0 = no limit, useful for testing)."
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Output .apkg filename (default: {DEFAULT_OUTPUT})."
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Delay in seconds between HTTP requests (default: {DEFAULT_DELAY})."
    )
    parser.add_argument(
        "--cache-dir", default=".html_cache",
        help="Directory to cache downloaded HTML pages (default: .html_cache)."
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Disable local HTML cache (always fetch from network)."
    )
    parser.add_argument(
        "--no-css", action="store_true",
        help="Skip fetching site CSS (cards won't have site styling)."
    )
    parser.add_argument(
        "--github-token", default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub personal access token (increases API rate limit from 60 to 5000/hr)."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    cache_dir = None if args.no_cache else Path(args.cache_dir)

    # --- HTTP Session ---
    session = requests.Session()
    session.headers.update({
        "User-Agent": "cpprefjp-anki-generator/1.0 (github.com/cpprefjp/cpprefjp.github.io)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
    })
    if args.github_token:
        session.headers["Authorization"] = f"token {args.github_token}"

    # --- Discover pages via GitHub API ---
    print("Discovering reference pages via GitHub API...")
    try:
        tree_entries = get_tree_recursive(REPO_OWNER, REPO_NAME, session=session)
    except Exception as e:
        print(f"ERROR: Failed to fetch repo tree from GitHub API: {e}", file=sys.stderr)
        print("Tip: Set GITHUB_TOKEN env var or use --github-token to avoid rate limiting.", file=sys.stderr)
        sys.exit(1)

    page_paths = filter_reference_pages(tree_entries, TARGET_DIRS)
    print(f"Found {len(page_paths)} reference pages.")

    if args.limit > 0:
        page_paths = page_paths[:args.limit]
        print(f"Limiting to first {args.limit} pages.")

    # --- Fetch site CSS ---
    site_css = ""
    if not args.no_css:
        print("Fetching site CSS...")
        site_css = fetch_site_css(session)
        if site_css:
            print(f"  CSS fetched ({len(site_css):,} bytes).")
        else:
            print("  Could not fetch site CSS, cards will use minimal styling.")

    # --- Build Anki deck ---
    model = make_model(extra_css=site_css)
    deck = make_deck()
    media_files = []  # We don't embed binary media — links point to live site

    skipped = 0
    processed = 0

    print(f"\nProcessing {len(page_paths)} pages → {args.output}")
    for rel_path in tqdm(page_paths):
        url = f"{SITE_BASE}/{rel_path}"

        # Rate limiting
        if processed > 0:
            time.sleep(args.delay)

        # Fetch HTML
        html = fetch_page_html(url, session, cache_dir)
        if html is None:
            skipped += 1
            continue

        # Extract front/back
        result = extract_main_content(html, url, site_css)
        if result is None:
            tqdm.write(f"  [SKIP] Could not extract content: {rel_path}")
            skipped += 1
            continue

        front_html, back_html = result

        # Derive a stable note ID from the URL (use hash)
        note_id = int(hashlib.sha256(url.encode()).hexdigest()[:15], 16) % (10**15)

        # Create note
        note = genanki.Note(
            model=model,
            fields=[front_html, back_html, url],
            guid=genanki.guid_for(url),
        )
        deck.add_note(note)
        processed += 1

    # --- Write .apkg ---
    print(f"\nWriting {args.output}...")
    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(args.output)

    print(f"\nDone!")
    print(f"  Cards created : {processed}")
    print(f"  Skipped       : {skipped}")
    print(f"  Output file   : {args.output}")
    print(f"\nImport {args.output} into Anki via File → Import.")


if __name__ == "__main__":
    main()
