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
    &q=lemma:aspicio
    &title="Gallic War"
    &author=Caesar
    &start=0
    &end=0
    &format=json

ID format
---------

The ID column is now based on the PhiloLogic citation structure:

    doc_id.div1.div2.div3.byte_DocLabel

where:

    doc_id   = metadata_fields["philo_doc_id"] or first element of philo_id
    div1-3   = up to three division labels from result["citation"]
               with object_type "div1", "div2", "div3"
    byte     = the "byte=" parameter extracted from any citation href
               (or citation_links as fallback)
    DocLabel = citation[0]["label"] (usually something like "Caes. Gal.")
               with whitespace removed, e.g. "Caes.Gal."

Example:

    77.5.14.2.636137_Caes.Gal.

For each JSON result, all highlighted tokens share this same ID (the ID
identifies the specific cited passage/hit).
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


def build_passage_url(citation_links: Dict[str, str]) -> str:
    """
    Build a clickable passage URL from citation_links.

    Preference:
      1. paragraph level ('para'), reshaped as ".../para_path/?byte=..."
      2. line ('line')
      3. doc ('doc')
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


def build_unique_id(result: Dict[str, Any]) -> str:
    """
    Build an ID of the form:

        doc_id.div1.div2.div3.byte_DocLabel

    using data from result["metadata_fields"] and result["citation"].

    Example:
        77.5.14.2.636137_Caes.Gal.
    """
    metadata = result.get("metadata_fields") or {}
    doc_id = str(metadata.get("philo_doc_id", "")).strip()

    # Fallback: first element of philo_id
    if not doc_id:
        philo_id = result.get("philo_id")
        if isinstance(philo_id, list) and philo_id:
            doc_id = str(philo_id[0])

    citation = result.get("citation") or []
    doc_label = ""
    div_labels: List[str] = []
    byte = ""

    for cit in citation:
        obj_type = (cit.get("object_type") or "").lower()
        label = (cit.get("label") or "").strip()

        if obj_type == "doc" and label and not doc_label:
            doc_label = label

        if obj_type.startswith("div") and label:
            div_labels.append(label)

        href = cit.get("href") or ""
        if not byte and href:
            m = re.search(r"byte=(\d+)", href)
            if m:
                byte = m.group(1)

    # Only keep up to three structural labels (e.g. 5.14.2)
    div_labels = div_labels[:3]

    # Fallback for byte: look in citation_links
    if not byte:
        citation_links = result.get("citation_links") or {}
        for key in ("para", "line", "doc"):
            href = citation_links.get(key) or ""
            m = re.search(r"byte=(\d+)", href)
            if m:
                byte = m.group(1)
                break

    parts: List[str] = []
    if doc_id:
        parts.append(doc_id)
    parts.extend(div_labels)
    if byte:
        parts.append(byte)

    base_id = ".".join(parts)

    if doc_label:
        # Remove whitespace inside label: "Caes. Gal." -> "Caes.Gal."
        doc_label_clean = re.sub(r"\s+", "", doc_label)
        if base_id:
            return f"{base_id}_{doc_label_clean}"
        return doc_label_clean

    return base_id


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

        citation_links = result.get("citation_links", {}) or {}
        passage_url = build_passage_url(citation_links)

        unique_id = build_unique_id(result)

        # Guarantee at least one row per result; if no highlight spans were found,
        # we still store one row with an empty TOKEN.
        if not tokens:
            tokens = [""]

        for token in tokens:
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
        help="Lemma(s) to search for (OR between them). Example: aspicio or πόλις",
    )
    parser.add_argument(
        "-a",
        "--author",
        help="Restrict to this author (as in metadata, e.g. 'Caesar' or 'Xenophon').",
    )
    parser.add_argument(
        "-t",
        "--title",
        help="Restrict to this work title (as in metadata, e.g. 'Gallic War' or 'Anabasis').",
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
