#!/usr/bin/env python3
"""
Extract passages containing selected lemmas from the Perseus / PhiloLogic
Latin or Greek corpora and save them to a CSV file.

Supports:
  - Latin: https://artflsrv03.uchicago.edu/philologic4/Latin/query
  - Greek: https://artflsrv03.uchicago.edu/philologic4/Greek/query

- Builds a query like:
  https://artflsrv03.uchicago.edu/philologic4/<Language>/query
    ?report=concordance
    &method=proxy
    &colloc_filter_choice=frequency
    &q=lemma:inspicio%20%7C%20lemma:invideo
    &title=Aeneid
    &author=Vergil
    &start=0
    &end=0
    &format=json

- First query uses end=0 to discover results_length.
- Second query uses end=<results_length> to get the full JSON.

For each hit, it extracts:

    ID        a stable ID derived from PhiloLogic ids + author/work codes
    TOKEN     the highlighted token
    LEMMA     the lemma (or lemmas) you searched for
    SENTENCE  cleaned context text (HTML stripped, spacing normalized)
    author    metadata_fields["author"]
    title     metadata_fields["title"]
    language  "Latin" or "Greek"
    passage   a clickable URL (paragraph-level, with byte)

Usage examples:

    # Latin, one lemma, all authors/works
    python philologic_lemmas_to_csv.py inspicio -o inspicio_all.csv

    # Latin, multiple lemmas (OR), restricted to Vergil's Aeneid
    python philologic_lemmas_to_csv.py inspicio invideo \\
        -a Vergil -t Aeneid -o aeneid_inspicio_invideo.csv

    # Greek, lemma πόλις, Xenophon Anabasis
    python philologic_lemmas_to_csv.py πόλις \\
        -a Xenophon -t Anabasis -L Greek -o polis_xen_anabasis.csv
"""

import argparse
import csv
import html
import re
import sys
from typing import Dict, List, Any
from urllib.parse import urljoin

import requests

# Language-dependent configuration
LANG_CONFIG = {
    "Latin": {
        "query_url": "https://artflsrv03.uchicago.edu/philologic4/Latin/query",
        "nav_url": "https://artflsrv03.uchicago.edu/philologic4/Latin/",
    },
    "Greek": {
        "query_url": "https://artflsrv03.uchicago.edu/philologic4/Greek/query",
        "nav_url": "https://artflsrv03.uchicago.edu/philologic4/Greek/",
    },
}

# These will be set in main() based on --language
BASE_QUERY_URL = LANG_CONFIG["Latin"]["query_url"]
BASE_NAV_URL = LANG_CONFIG["Latin"]["nav_url"]

TAG_RE = re.compile(r"<[^>]+>")
HIGHLIGHT_RE = re.compile(
    r'<span[^>]*class="[^"]*highlight[^"]*"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


def build_query_params(
    lemmas: List[str],
    author: str = None,
    title: str = None,
    start: int = 0,
    end: int = 0,
) -> Dict[str, Any]:
    """Build the query parameters for the PhiloLogic JSON API."""
    lemma_parts = [f"lemma:{lemma}" for lemma in lemmas]
    q_string = " | ".join(lemma_parts)

    params: Dict[str, Any] = {
        "report": "concordance",
        "method": "proxy",
        "colloc_filter_choice": "frequency",
        "q": q_string,
        "start": start,
        "end": end,
        "direction": "",
        "metadata_sorting_field": "",
        "format": "json",
    }
    if author:
        params["author"] = author
    if title:
        params["title"] = title
    return params


def fetch_json(params: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch JSON from PhiloLogic with the given params, or exit on error."""
    try:
        resp = requests.get(BASE_QUERY_URL, params=params, timeout=60)
    except requests.RequestException as e:
        print(f"Error contacting {BASE_QUERY_URL}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(
            f"HTTP {resp.status_code} from server. "
            f"URL was: {resp.url}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError as e:
        print(f"Response was not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    return data


def extract_highlight_tokens(context_html: str) -> List[str]:
    """
    Extract tokens marked by <span class="highlight">…</span> in the context.

    Returns a list of cleaned surface forms.
    """
    tokens: List[str] = []
    for match in HIGHLIGHT_RE.finditer(context_html):
        inner_html = match.group(1)
        # Strip any nested tags and unescape entities
        text = TAG_RE.sub(" ", inner_html)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            tokens.append(text)
    return tokens


def clean_context(context_html: str) -> str:
    """Strip HTML tags, clean whitespace, and tidy punctuation/quotes spacing."""
    # Remove tags
    text = TAG_RE.sub(" ", context_html)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    # Remove spaces before common punctuation (", . ; : ? !")
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    # Remove spaces immediately after an opening double quote “
    text = re.sub(r"“\s+", "“", text)
    return text


def abbreviate_word(word: str, length: int = 3) -> str:
    """
    Create a simple alphabetic abbreviation (e.g. 'Cicero' -> 'Cic',
    'Aeneid' -> 'Aen').
    """
    letters_only = re.sub(r"[^A-Za-z]+", "", word)
    if not letters_only:
        return ""
    return letters_only[:length]


def build_passage_url(citation_links: Dict[str, str]) -> str:
    """
    Build a clickable passage URL from citation_links.

    Preference:
      1. paragraph level ('para'), reshaped as ".../para_path/?byte=..."
      2. line ('line')
      3. doc ('doc')

    The main fix is (1): paragraph-level URL + ?byte=...,
    e.g. navigate/181/1/26/1/1/?byte=77098
    """
    raw = citation_links.get("para") or citation_links.get("line") or citation_links.get("doc")
    if not raw:
        return ""

    # If there is a ?byte= parameter, insert a trailing slash before it
    # to get ".../path/?byte=..."
    if "?" in raw:
        path, query = raw.split("?", 1)
        if not path.endswith("/"):
            path = path + "/"
        raw = f"{path}?{query}"

    return urljoin(BASE_NAV_URL, raw)


def extract_rows(data: Dict[str, Any], lemmas: List[str], language: str) -> List[Dict[str, str]]:
    """Turn a PhiloLogic JSON response into a list of CSV rows."""
    results = data.get("results", [])
    rows: List[Dict[str, str]] = []

    # Determine how to fill the LEMMA column
    if len(lemmas) == 1:
        lemma_value = lemmas[0]
    else:
        # For multiple lemmas we store the whole set as a semicolon-separated list.
        # (PhiloLogic does not tell us which exact lemma matched each token.)
        lemma_value = ";".join(lemmas)

    for result in results:
        context_html = result.get("context", "")
        tokens = extract_highlight_tokens(context_html)
        sentence = clean_context(context_html)

        metadata = result.get("metadata_fields", {}) or {}
        author = (metadata.get("author") or "").strip()
        title = (metadata.get("title") or "").strip()
        doc_id = (metadata.get("philo_doc_id") or "").strip()
        line_n = (metadata.get("n") or "").strip()

        author_code = abbreviate_word(author or "Unknown")
        title_code = abbreviate_word(title or "Work")

        citation_links = result.get("citation_links", {}) or {}
        passage_url = build_passage_url(citation_links)

        # Guarantee at least one row per result; if no highlight spans were found,
        # we still store one row with an empty TOKEN.
        if not tokens:
            tokens = [""]

        for idx, token in enumerate(tokens, start=1):
            # Stable ID: docId.lineNumber.tokenIndex + short author/title codes
            # e.g. "181.387.1Verg_Aen"
            id_core = f"{doc_id}.{line_n}.{idx}."
            id_suffix = f"{author_code}_{title_code}" if author_code or title_code else ""
            unique_id = f"{id_core}{id_suffix}"

            rows.append(
                {
                    "ID": unique_id,
                    "TOKEN": token,
                    "LEMMA": lemma_value,
                    "SENTENCE": sentence,
                    "author": author,
                    "title": title,
                    "language": language,
                    "passage": passage_url,
                }
            )

    return rows


def write_csv(rows: List[Dict[str, str]], output_path: str) -> None:
    """Write rows to CSV with the desired column order."""
    fieldnames = [
        "ID",
        "TOKEN",
        "LEMMA",
        "SENTENCE",
        "author",
        "title",
        "language",
        "passage",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Latin/Greek lemma contexts from Perseus / PhiloLogic into CSV."
    )
    parser.add_argument(
        "lemmas",
        nargs="+",
        help="Lemma(s) to search for (OR between them). Example: inspicio invideo or πόλις",
    )
    parser.add_argument(
        "-a",
        "--author",
        help="Restrict to this author (as in metadata, e.g. 'Vergil' or 'Xenophon').",
    )
    parser.add_argument(
        "-t",
        "--title",
        help="Restrict to this work title (as in metadata, e.g. 'Aeneid' or 'Anabasis').",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output.csv",
        help="Output CSV path (default: output.csv).",
    )
    parser.add_argument(
        "-L",
        "--language",
        choices=["Latin", "Greek"],
        default="Latin",
        help="Corpus language: Latin or Greek (default: Latin).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print more information while running.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Select the correct base URLs for the chosen language
    cfg = LANG_CONFIG[args.language]
    global BASE_QUERY_URL, BASE_NAV_URL
    BASE_QUERY_URL = cfg["query_url"]
    BASE_NAV_URL = cfg["nav_url"]

    if args.verbose:
        print(f"Language: {args.language}", file=sys.stderr)
        print(f"Lemmas: {args.lemmas}", file=sys.stderr)
        if args.author:
            print(f"Author filter: {args.author}", file=sys.stderr)
        if args.title:
            print(f"Title filter:  {args.title}", file=sys.stderr)

    # First query: end=0 to discover results_length
    params_initial = build_query_params(
        lemmas=args.lemmas,
        author=args.author,
        title=args.title,
        start=0,
        end=0,
    )
    data_initial = fetch_json(params_initial)

    results_length = int(data_initial.get("results_length", 0) or 0)
    if args.verbose:
        print(f"Found {results_length} result(s).", file=sys.stderr)

    if results_length == 0:
        print("No results found for this query.", file=sys.stderr)
        # Still create an empty CSV with just headers
        write_csv([], args.output)
        print(f"Extracted 0 tokens into {args.output}")
        return

    # Second query: fetch the full set with end=results_length
    params_full = build_query_params(
        lemmas=args.lemmas,
        author=args.author,
        title=args.title,
        start=1,
        end=results_length,
    )
    data_full = fetch_json(params_full)

    rows = extract_rows(data_full, args.lemmas, args.language)
    write_csv(rows, args.output)

    # Simple output message with token count
    print(f"Extracted {len(rows)} tokens into {args.output}")


if __name__ == "__main__":
    main()
