"""
Meraki Documentation Scraper – Markdown, Versioned, Change-Aware
================================================================

PURPOSE
-------
This script logs into the Meraki documentation portal using Playwright,
extracts documentation pages as clean Markdown files, and prepares them
for AI ingestion (RAG, embeddings, search, etc.).

KEY FEATURES
------------
- Authenticated scraping via Playwright
- HTML → Markdown conversion
  - Preserves headings (h1–h4)
  - Preserves code blocks
- YAML frontmatter metadata for AI pipelines
- Change detection based on LAST_UPDATED
- Versioned filenames using unique document IDs

OUTPUT
------
markdown_docs/
  <DOC_ID>_<YYYYMMDD>_<TITLE>.md

STATE
-----
- last_run.txt stores the timestamp of the last successful run

REQUIREMENTS
------------
- Python 3.9+
- playwright
- beautifulsoup4
- Chromium / Chrome installed
"""

from playwright.sync_api import sync_playwright
import csv
import re
import os
from datetime import datetime, timezone, time
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime


# -----------------------------------------------------------------------------
# Utility: Detect Japanese characters to optionally skip non-English docs
# -----------------------------------------------------------------------------

def contains_japanese(text: str) -> bool:
    """
    Returns True if the input string contains Japanese characters.

    Used to skip documents that may not be suitable for ingestion
    in an English-only AI knowledge base.
    """
    if not text:
        return False

    japanese_re = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
    return bool(japanese_re.search(text))


# -----------------------------------------------------------------------------
# Load CSV and extract URLs + metadata
# -----------------------------------------------------------------------------

def create_urls_from_csv(csv_file_path):
    """
    Reads the documentation CSV and extracts:
      - UI URLs (used for scraping)
      - Metadata needed for versioning and frontmatter

    Expected CSV columns:
      ID, TITLE, UI_URL, LAST_UPDATED

    Returns:
      urls (list[str]) - List of all the doc URLs
      metadata (dict[str, dict]) - Metadata for each doc. UI_URL:{ID, TITLE, LAST_UPDATED}
    """
    urls = []
    metadata = {}

    with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            ui_url = row['UI_URL']
            urls.append(ui_url)

            metadata[ui_url] = {
                "id": row.get('ID'),
                "title": row.get('TITLE', 'document'), # title = 'document' if TITLE in row is NULL/empty
                "last_updated": row.get('LAST_UPDATED', '1970-01-01') #  last_updated = '1970-01-01' if 'LAST_UPDATED' in row is NULL/empty
            }

    return urls, metadata


# -----------------------------------------------------------------------------
# Convert HTML article content to structured Markdown
# -----------------------------------------------------------------------------

def html_to_markdown(article):
    """
    Convert a MindTouch <article> element into clean, structured Markdown.

    Design goals:
    - Preserve document structure (headings, lists, tables, code)
    - Preserve nested lists with correct indentation
    - Avoid duplicate rendering caused by recursive DOM traversal
    - Explicitly mark internal-only content
    - Be deterministic and AI-ingestion friendly

    IMPORTANT:
    MindTouch pages nest nearly all real content inside wrapper <div>s.
    We must traverse recursively, but carefully guard against reprocessing
    elements that are already handled by parent renderers.
    """

    md_lines = []

    # -----------------------------
    # Helper: render unordered lists (supports nesting)
    # -----------------------------
    def render_ul(ul_elem, indent=0):
        for li in ul_elem.find_all('li', recursive=False):
            prefix = '  ' * indent + '- '

            # Extract only the text belonging to THIS list item,
            # excluding any nested <ul>/<ol> which will be rendered separately
            text_parts = []
            for child in li.contents:
                if getattr(child, 'name', None) not in ['ul', 'ol']:
                    if hasattr(child, 'get_text'):
                        text_parts.append(child.get_text(strip=True))
                    else:
                        text_parts.append(str(child).strip())

            text = ' '.join(filter(None, text_parts))
            if text:
                md_lines.append(prefix + text)

            # Recursively render nested lists
            for nested_ul in li.find_all('ul', recursive=False):
                render_ul(nested_ul, indent + 1)

            for nested_ol in li.find_all('ol', recursive=False):
                render_ol(nested_ol, indent + 1)

    # -----------------------------
    # Helper: render ordered lists (supports nesting)
    # -----------------------------
    def render_ol(ol_elem, indent=0):
        for idx, li in enumerate(ol_elem.find_all('li', recursive=False), start=1):
            prefix = '  ' * indent + f"{idx}. "

            text_parts = []
            for child in li.contents:
                if getattr(child, 'name', None) not in ['ul', 'ol']:
                    if hasattr(child, 'get_text'):
                        text_parts.append(child.get_text(strip=True))
                    else:
                        text_parts.append(str(child).strip())

            text = ' '.join(filter(None, text_parts))
            if text:
                md_lines.append(prefix + text)

            for nested_ul in li.find_all('ul', recursive=False):
                render_ul(nested_ul, indent + 1)

            for nested_ol in li.find_all('ol', recursive=False):
                render_ol(nested_ol, indent + 1)

    # -----------------------------
    # Main traversal
    # -----------------------------
    for elem in article.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'table', 'pre', 'div'],recursive=True):
        # ---------------------------------
        # GUARD 1: Never render <li> directly
        #
        # Reason:
        # List items are always rendered by render_ul/render_ol.
        # Rendering them here would cause duplication and flattening.
        # ---------------------------------
        if elem.name == 'li':
            continue

        # ---------------------------------
        # GUARD 2: Skip nested lists
        #
        # Reason:
        # Nested <ul>/<ol> are rendered recursively by their parent list.
        # Encountering them again during traversal would duplicate content.
        # ---------------------------------
        if elem.name in ['ul', 'ol'] and elem.find_parent(['ul', 'ol']):
            continue

        # ---------------------------------
        # GUARD 3: Skip paragraphs inside lists
        #
        # Reason:
        # <p> tags sometimes appear inside <li>.
        # Their text is already captured when rendering the list item.
        # ---------------------------------
        if elem.name == 'p' and elem.find_parent(['ul', 'ol']):
            continue

        # ---------------------------------
        # GUARD 4: Skip anything inside a table
        #
        # Reason:
        # Table content is fully rendered when we process <table>.
        # Rendering descendants (<tr>, <td>, <th>, text) would duplicate content.
        # ---------------------------------
        if elem.find_parent('table'):
            continue

        # ---------------------------------
        # Headings
        # ---------------------------------
        if elem.name in ['h1', 'h2', 'h3', 'h4']:
            level = int(elem.name[1])
            md_lines.append(f"{'#' * level} {elem.get_text(strip=True)}")
            md_lines.append("")
            continue

        # ---------------------------------
        # Code blocks
        # ---------------------------------
        if elem.name == 'pre':
            code = elem.get_text()
            md_lines.append("```")
            md_lines.append(code.rstrip())
            md_lines.append("```")
            md_lines.append("")
            continue

        # ---------------------------------
        # Tables
        # ---------------------------------
        if elem.name == 'table':
            rows = elem.find_all('tr')
            if not rows:
                continue

            for r_idx, row in enumerate(rows):
                cells = row.find_all(['th', 'td'])
                cell_text = [c.get_text(strip=True) for c in cells]
                if not cell_text:
                    continue

                md_lines.append("| " + " | ".join(cell_text) + " |")

                # Header separator after first row
                if r_idx == 0:
                    md_lines.append("| " + " | ".join(['---'] * len(cell_text)) + " |")

            md_lines.append("")
            continue

        # ---------------------------------
        # Internal-only (Meraki confidential)
        # ---------------------------------
        if elem.name == 'div' and 'internal-only' in (elem.get('class') or []):
            internal_text = elem.get_text("\n", strip=True)
            if internal_text:
                md_lines.append("> **Internal Only – Meraki Confidential**")
                md_lines.append(">")
                for line in internal_text.splitlines():
                    md_lines.append(f"> {line}")
                md_lines.append("")
            continue

        # ---------------------------------
        # Lists (top-level only)
        # ---------------------------------
        if elem.name == 'ul':
            render_ul(elem)
            md_lines.append("")
            continue

        if elem.name == 'ol':
            render_ol(elem)
            md_lines.append("")
            continue

        # ---------------------------------
        # Paragraphs (default text)
        # ---------------------------------
        if elem.name == 'p':
            text = elem.get_text(strip=True)
            if text:
                md_lines.append(text)
                md_lines.append("")
            continue

    return "\n".join(md_lines).strip()


# -----------------------------------------------------------------------------
# MAIN PROGRAM
# -----------------------------------------------------------------------------

csv_path = 'documentation.csv'
urls, metadata = create_urls_from_csv(csv_path)

# Track last successful run for change detection
STATE_FILE = 'last_run.txt'
if os.path.exists(STATE_FILE):
    with open(STATE_FILE, 'r') as f:
        last_run = datetime.fromisoformat(f.read().strip())
        print(f"last_run found: {last_run}")

else:
    print("No last_run.txt found. Beginning fresh run")
    last_run = datetime.fromisoformat('1970-01-01T00:00:00+00:00')

os.makedirs('markdown_docs', exist_ok=True)

with sync_playwright() as p:
    print("Launching Chrome browser")

    browser = p.chromium.launch(
        executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
        headless=False
    )
    context = browser.new_context()
    page = context.new_page()

    # -------------------------------------------------------------------------
    # AUTHENTICATION STEP
    # -------------------------------------------------------------------------
    # Navigate to Okta login page and complete authentication manually or via
    # scripted steps. Once authenticated, the browser context can access
    # protected documentation pages.
    # -------------------------------------------------------------------------
    print("Beginning Mindtouch authentication")

    page.goto("https://meraki.okta.com/oauth2/v1/authorize?client_id=okta.2b1959c8-bcc0-56eb-a589-cfcfb7422f26&code_challenge=jDrhYDukWpnhpf2ow5W1YEXKIyUAimrs4JBUKyAAlUA&code_challenge_method=S256&nonce=TfFG2pJjrpHwN1RUAjoGbZtuWj6P6fWS5NZ0QUtL6EMe3hgnGpeyIbgqRKdRQ5ZP&redirect_uri=https%3A%2F%2Fmeraki.okta.com%2Fenduser%2Fcallback&response_type=code&state=5yYwzPP9rkBOv5nF32ol9BJqk5RuzSjxu3KK23FqWJjXf99xM0VNjHhGqML7de03&scope=openid%20profile%20email%20okta.users.read.self%20okta.users.manage.self%20okta.internal.enduser.read%20okta.internal.enduser.manage%20okta.enduser.dashboard.read%20okta.enduser.dashboard.manage%20okta.myAccount.sessions.manage%20okta.internal.navigation.enduser.read")
    # Fill username and password
    page.fill('input#input28', 'bailey.wilson')
    page.click('input.button-primary[type="submit"][value="Next"]')
    page.fill('input[aria-label="Email Address"]', 'bailwils@cisco.com')
    page.click('button.c--primary.primary.align-flex-items-center.align-flex-justify-content-start.input__width-full.size-margin-top-medium.button--xlarge[type="button"]');
    
    print("Please complete Okta/Duo authentication in the browser.")
    print("Once the MindTouch documentation page loads, press ENTER here.")

    page.wait_for_load_state("networkidle") 
    input("Press ENTER to continue after login...")


    for url in urls:
        meta = metadata.get(url, {})
        last_updated = parsedate_to_datetime(meta.get('last_updated'))

        # Skip documents that have not changed since last run
        if last_updated <= last_run:
            continue

        title = meta.get('title', 'document').strip()
        if contains_japanese(title):
            continue

        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("article", timeout=30000)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
                time.sleep(3)

        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')

        # Remove non-content elements
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()

        article = soup.find('article') or soup.body
        markdown_body = html_to_markdown(article)

        # Construct versioned filename
        doc_id = meta.get('id', 'unknown')
        version = last_updated.strftime('%Y%m%d')
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)

        filename = f"{doc_id}_{version}_{safe_title}.md"
        md_path = f"markdown_docs/{filename}"

        # YAML frontmatter for AI pipelines
        frontmatter = (
            "---\n"
            f"title: {title}\n"
            f"source_url: {url}\n"
            f"last_updated: {meta.get('last_updated')}\n"
            f"doc_id: {doc_id}\n"
            f"version: {version}\n"
            f"scraped_at: {datetime.now(timezone.utc).isoformat()}Z\n"
            "---\n\n"
        )

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(frontmatter)
            f.write(markdown_body)

        print(f"Saved Markdown: {md_path}")

    browser.close()

# Update last run timestamp only after successful completion
with open(STATE_FILE, 'w') as f:
    f.write(datetime.now(timezone.utc).isoformat())


"""
GETTING STARTED GUIDE
====================

1. Install dependencies:
   pip install playwright beautifulsoup4
   playwright install

2. Prepare documentation.csv with columns:
   ID, TITLE, UI_URL, LAST_UPDATED

3. Update Chrome executable_path if needed

4. Run the script:
   python doc_scraper.py

5. Output:
   - Markdown files in markdown_docs/
   - last_run.txt for incremental updates

This output is ready for chunking, embedding, and RAG ingestion.
"""
