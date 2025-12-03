# Latin and Ancient Greek Lemma Extractor

Small web + CLI tool to extract Latin lemma concordance contexts from the UChicago PhiloLogic corpus and save them as CSV.

## Functionality

Given:

- one or more lemmas (OR search),
- optional **author** filter,
- optional **work title** filter,

the tool:

1. Queries the PhiloLogic JSON concordance API (Perseus Latin at UChicago).
2. Extracts:
   - the matched token(s),
   - the surrounding sentence/context (HTML stripped),
   - basic metadata (author, work),
   - a paragraph-level URL directly to the passage.
3. Writes everything to a CSV with one row per token.

Columns:

- `ID` – stable ID built from doc/passage/token index + abbreviated author/work
- `TOKEN` – highlighted token surface form
- `LEMMA` – lemma (or combined lemmas if multiple were queried)
- `SENTENCE` – cleaned context
- `author`
- `title`
- `language` – `Latin` or `Greek`
- `passage` – clickable URL such as  
  `https://artflsrv03.uchicago.edu/philologic4/Latin/navigate/181/1/26/1/1/?byte=77098`

---

## Web interface

The repository includes a single-page HTML app (`index.html`) that:

- runs entirely in the browser (no backend),
- calls the PhiloLogic JSON API directly,
- lets users:
  - enter lemmas (space- or comma-separated),
  - optionally restrict by `author` and `title`,
  - pick an output file name,
  - click a button to download the CSV.

### How to use

1. Open the GitHub Pages URL for this repo  
   https://mikcil.github.io/latin-lemma-extractor/
2. In the **Lemmas** box, type something like:  
   `inspicio invideo`
3. Optionally enter:
   - **Author**: `Vergil`
   - **Work title**: `Aeneid`
4. Choose an output filename (default: `output.csv`).
5. Click **“Run query & download CSV”**.
6. Wait until the CSV is downloaded; a short status line will say:  
   `Extracted N tokens into output.csv`.

If no results are found, it will still download an empty CSV with just headers.

---

## Local CLI usage (Python script)

For users who prefer the command line, the same logic is available as a Python script.

### Requirements

- Python 3.8+
- `requests` library

### Examples

- One lemma, all authors/works:

```bash
python perseus_lemma_extractor.py inspicio -L Latin -o inspicio_all.csv
```

- Multiple lemmas (OR), restricted to Vergil’s *Aeneid*:

```bash
   python perseus_lemma_extractor.py inspicio invideo -L Latin -a Vergil -t Aeneid -o aeneid_inspicio_invideo.csv`
```

### Command-line options

- `lemmas` (positional, one or more): lemmas to search for (OR between them).
- `-a / --author` (optional): restrict to author string used in metadata (e.g. `Vergil`).
- `-t / --title` (optional): restrict to work title (e.g. `Aeneid`).
- `-o / --output` (optional): CSV file path (default: `output.csv`).
- `-v / --verbose` (optional): print some progress messages to stderr.

On success, the script prints a simple message:

- `Extracted N tokens into output.csv`

---

## Files in this repo

- `index.html` – static web UI for GitHub Pages (front-end only).
- `perseus_lemma_extractor.py` – CLI script.
- `README.md` – this file.

---

## Notes and limitations

- This tool depends on the public PhiloLogic instance at UChicago; if the service is down or its API changes, the tool may stop working.
- For multiple lemmas, PhiloLogic does not reliably indicate **which** lemma matched each token, so the script stores the list of all queried lemmas (semicolon-separated) in the `LEMMA` column for every row.

---
