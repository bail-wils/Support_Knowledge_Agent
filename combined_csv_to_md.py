#!/usr/bin/env python3
"""
combined_csv_to_md.py

Combine functionality of:
 - convert_kb_tsv_to_md.py (TSV KB -> Markdown, HTML cleaning, JSON-wrapped HTML extraction)
 - mule_csv_parser.py (CSV with encoding detection, one MD per "Mule Jira Issue")

Usage:
    python combined_csv_to_md.py <input_file> <output_folder>

The script will:
 - detect file encoding (chardet)
 - detect delimiter (csv.Sniffer: comma or tab)
 - pick parser based on header columns
"""

import csv
import json
import os
import re
import sys
from html import unescape
from io import TextIOWrapper

# External dependency: chardet, bs4 (BeautifulSoup)
try:
    import chardet
except Exception:
    print("Missing dependency 'chardet'. Install with: pip install chardet")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except Exception:
    print("Missing dependency 'beautifulsoup4'. Install with: pip install beautifulsoup4")
    sys.exit(1)

# Increase csv field size for very large fields
csv.field_size_limit(sys.maxsize)


def safe_print(*args, **kwargs):
    """Print safely even if console can't display Unicode characters."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="ignore").decode(), **kwargs)


def detect_encoding(path, read_bytes=65536):
    """Detect file encoding using chardet, sampling first read_bytes bytes."""
    with open(path, "rb") as f:
        sample = f.read(read_bytes)
    result = chardet.detect(sample)
    encoding = result.get("encoding") or "utf-8"
    safe_print(f"Detected encoding: {encoding} (confidence: {result.get('confidence')})")
    return encoding


def detect_delimiter(path, encoding):
    """Try to detect delimiter using csv.Sniffer on a small sample."""
    with open(path, "r", encoding=encoding, errors="replace") as f:
        sample = f.read(4096)
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample, delimiters=[",", "\t", ";", "|"])
        delim = dialect.delimiter
        safe_print(f"Detected delimiter: {repr(delim)}")
        return delim
    except csv.Error:
        # fallback: if there are tabs in header assume TSV, else comma
        if "\t" in sample.splitlines()[0]:
            safe_print("Falling back to delimiter: tab")
            return "\t"
        safe_print("Falling back to delimiter: comma")
        return ","


def clean_html(html_content):
    """Strip HTML tags and return plain text."""
    soup = BeautifulSoup(html_content or "", "html.parser")
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{2,}", "\n\n", text.strip())
    return unescape(text)


def extract_html_from_json(cell_value):
    """Handle HTML stored directly or wrapped in JSON."""
    if not cell_value:
        return ""
    try:
        data = json.loads(cell_value)
        if isinstance(data, dict):
            for key in ("body", "content", "text", "html"):
                if key in data:
                    return str(data[key])
        elif isinstance(data, list):
            return "\n".join(str(item) for item in data)
        return str(data)
    except (json.JSONDecodeError, TypeError):
        return str(cell_value)


def safe_filename(name, maxlen=120):
    name = name or "untitled"
    safe_title = re.sub(r"[\\/*?\"<>|:]", "_", str(name).strip())
    return safe_title[:maxlen] + (".md" if not safe_title.lower().endswith(".md") else "")


def parse_kb_row_to_md(row, output_folder):
    """
    KB/TSV style parsing:
    - Title fields: TITLE or Title
    - Content fields: CONTENTS or Content (may contain JSON-wrapped html)
    - Metadata: ID, CATEGORY, FULL_PATH, LAST_UPDATED, SOURCE
    """
    title = row.get("TITLE") or row.get("Title") or "Untitled"
    html_content = extract_html_from_json(row.get("CONTENTS") or row.get("Content"))
    body_text = clean_html(html_content)

    metadata = {
        "ID": row.get("ID", ""),
        "CATEGORY": row.get("CATEGORY", ""),
        "FULL_PATH": row.get("FULL_PATH", ""),
        "LAST_UPDATED": row.get("LAST_UPDATED", ""),
        "SOURCE": row.get("SOURCE", ""),
    }

    filename = safe_filename(title)
    filepath = os.path.join(output_folder, filename)

    with open(filepath, "w", encoding="utf-8") as outfile:
        outfile.write(f"# {title}\n\n")
        outfile.write("## Metadata\n")
        for key, value in metadata.items():
            outfile.write(f"- **{key}**: {value}\n")
        outfile.write("\n---\n\n")
        outfile.write(body_text)
    safe_print(f"Saved: {filepath}")


def parse_generic_row_to_md(row, output_folder, id_field=None):
    """
    Generic CSV parsing:
    - Use an identifier field (id_field) if provided to name the file, otherwise use first non-empty field.
    - Dump all keys/values into the MD.
    """
    identifier = None
    if id_field:
        identifier = row.get(id_field)
    if not identifier:
        # fallback: first non-empty value
        for k, v in row.items():
            if v:
                identifier = v
                break
    if not identifier:
        identifier = "row"

    filename = safe_filename(identifier)
    filepath = os.path.join(output_folder, filename)

    lines = [f"# {identifier}\n"]
    for key, value in row.items():
        if key:
            # preserve original content; avoid None
            v = value if value is not None else ""
            lines.append(f"**{key.strip()}:** {str(v).strip()}\n")

    with open(filepath, "w", encoding="utf-8") as outfile:
        # ensure blank lines between entries
        outfile.writelines(line + "\n" for line in lines)

    safe_print(f"Created: {filepath}")


def process_file(input_path, output_folder):
    os.makedirs(output_folder, exist_ok=True)

    encoding = detect_encoding(input_path)
    delimiter = detect_delimiter(input_path, encoding)

    with open(input_path, "r", encoding=encoding, errors="replace") as infile:
        reader = csv.DictReader(infile, delimiter=delimiter)
        headers = reader.fieldnames or []
        lower_headers = [h.lower() for h in headers]

        # Decide parser based on header heuristics
        # Mule CSV: has "Mule Jira Issue" column
        if any(h.lower() == "mule jira issue" for h in headers):
            safe_print("Using Mule-style parser (Mule Jira Issue found).")
            id_field = "Mule Jira Issue"
            for row in reader:
                if not row.get(id_field):
                    continue
                parse_generic_row_to_md(row, output_folder, id_field=id_field)
            safe_print("\nAll Mule-style Markdown files created successfully.")
            return

        # KB/TSV style: has TITLE and CONTENTS or Content
        if any(h.lower() in ("title", "title") for h in headers) and any(
            h.lower() in ("contents", "content") for h in headers
        ):
            safe_print("Using KB/TSV-style parser (TITLE + CONTENTS detected).")
            for row in reader:
                # Some TSV exports might include blank rows; skip those w/o title
                if not (row.get("TITLE") or row.get("Title")):
                    continue
                parse_kb_row_to_md(row, output_folder)
            safe_print("\n✅ KB-style Markdown conversion complete!")
            return

        # Fallback generic: try to find a reasonable id-like column (Issue, ID, Name, Subject)
        for candidate in ("issue", "id", "name", "subject", "title"):
            for h in headers:
                if h and h.lower() == candidate:
                    safe_print(f"Using generic parser with id field: {h}")
                    for row in reader:
                        parse_generic_row_to_md(row, output_folder, id_field=h)
                    safe_print("\nAll generic Markdown files created successfully.")
                    return

        # Final fallback: use the first non-empty value per row
        safe_print("No recognized schema detected; using generic fallback parser.")
        for row in reader:
            parse_generic_row_to_md(row, output_folder)
        safe_print("\nAll Markdown files created successfully (fallback).")


# --- Entry Point ---
if __name__ == "__main__":
    if len(sys.argv) != 3:
        safe_print("Usage: python combined_csv_to_md.py <input_csv_or_tsv> <output_folder>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_folder = sys.argv[2]

    if not os.path.isfile(input_path):
        safe_print(f"Input file does not exist: {input_path}")
        sys.exit(1)

    process_file(input_path, output_folder)
