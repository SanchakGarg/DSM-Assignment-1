"""
Disaster Evolution & Response Pipeline — Web Scraper
=====================================================
Scrapes disaster data from ReliefWeb using HTML web scraping (requests + BeautifulSoup).
Extracts: Summary (magnitude, country, date), Impact (casualties, displacement, exposure),
and Media/Headlines (all report titles, sources, counts).

Events:
  1. Indonesia Earthquake Nov 2022 (Recent)  — eq-2022-000363-idn
  2. Indonesia Earthquake Nov 2008 (Historical) — eq-2008-000226-idn
  3. Myanmar Earthquake Mar 2025 (Recent)  — eq-2025-000043-mmr
  4. China Earthquake Jun 2012 (Historical)  — eq-2012-000112-chn
"""

import re
import json
import csv
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ── Configuration ──────────────────────────────────────────────────────────────

DISASTER_URLS = [
    {
        "url": "https://reliefweb.int/disaster/eq-2022-000363-idn",
        "event_type": "Recent",
        "label": "Indonesia Earthquake Nov 2022",
    },
    {
        "url": "https://reliefweb.int/disaster/eq-2008-000226-idn",
        "event_type": "Historical",
        "label": "Indonesia Earthquake Nov 2008",
    },
    {
        "url": "https://reliefweb.int/disaster/eq-2025-000043-mmr",
        "event_type": "Recent",
        "label": "Myanmar Earthquake Mar 2025",
    },
    {
        "url": "https://reliefweb.int/disaster/eq-2012-000112-chn",
        "event_type": "Historical",
        "label": "China Earthquake Jun 2012",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BASE_URL = "https://reliefweb.int"

# ── Helper utilities ───────────────────────────────────────────────────────────


def fetch_page(url: str) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    print(f"  📡 Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def safe_int(text: str) -> int | None:
    """Extract the first integer-like number from a string (handles commas)."""
    if not text:
        return None
    # Remove commas and grab the first number
    cleaned = text.replace(",", "").replace(".", "")
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


# ── Impact data extraction (regex on description text) ─────────────────────────


def parse_impact_data(description_text: str) -> dict:
    """
    Parse quantitative impact data from the disaster description text using regex.
    Returns a dict with keys: magnitude, deaths, injured, missing, displaced,
    affected, houses_damaged, houses_destroyed, schools_affected, hospitals_affected.
    """
    text = description_text

    impact = {
        "magnitude": None,
        "depth_km": None,
        "deaths": None,
        "injured": None,
        "missing": None,
        "displaced": None,
        "affected_population": None,
        "houses_destroyed": None,
        "houses_damaged": None,
        "schools_affected": None,
        "hospitals_affected": None,
        "population_exposed_to_shaking": None,
    }

    # ── Magnitude ──────────────────────────────────────────────────────────
    mag_patterns = [
        r"(\d+\.?\d*)\s*(?:M|magnitude)",
        r"magnitude[:\s]*(\d+\.?\d*)",
        r"(\d+\.?\d*)\s*(?:on the Richter scale)",
        r"(\d+\.?\d*)-magnitude",
    ]
    for pat in mag_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            impact["magnitude"] = float(m.group(1))
            break

    # ── Depth ──────────────────────────────────────────────────────────────
    depth_m = re.search(r"depth\s+of\s+(\d+)\s*km", text, re.IGNORECASE)
    if depth_m:
        impact["depth_km"] = int(depth_m.group(1))

    # ── Deaths / fatalities ────────────────────────────────────────────────
    death_patterns = [
        r"([\d,]+)\s*(?:people\s+)?(?:fatalities|deaths|dead|killed|death toll)",
        r"(?:fatalities|deaths|death toll|killed|killing)\s*(?:of|at least|over|reached|stood at over)?\s*([\d,]+)",
        r"([\d,]+)\s*(?:people\s+)?(?:have\s+)?(?:died|confirmed\s+killed)",
    ]
    deaths_found = []
    for pat in death_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1) if m.group(1) and m.group(1).replace(",", "").isdigit() else m.group(1))
            if val and val < 1_000_000:
                deaths_found.append(val)
    if deaths_found:
        impact["deaths"] = max(deaths_found)  # take the largest (most updated) figure

    # ── Injured ────────────────────────────────────────────────────────────
    inj_patterns = [
        r"([\d,]+)\s*(?:people\s+)?(?:injured|hurt|sustained injuries)",
        r"(?:injured|injuries)[:\s]*([\d,]+)",
        r"([\d,]+)\s*injured",
    ]
    injured_found = []
    for pat in inj_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 10_000_000:
                injured_found.append(val)
    if injured_found:
        impact["injured"] = max(injured_found)

    # ── Missing ────────────────────────────────────────────────────────────
    miss_patterns = [
        r"([\d,]+)\s*(?:people\s+)?(?:missing|still missing|unaccounted)",
        r"(?:missing)[:\s]*([\d,]+)",
    ]
    missing_found = []
    for pat in miss_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 1_000_000:
                missing_found.append(val)
    if missing_found:
        impact["missing"] = max(missing_found)

    # ── Displaced ──────────────────────────────────────────────────────────
    disp_patterns = [
        r"([\d,]+)\s*(?:people\s+)?(?:displaced|evacuated|fled|left homeless)",
        r"(?:displaced|evacuated)[:\s]*([\d,]+)",
        r"([\d,]+)\s*(?:have been\s+)?displaced",
    ]
    disp_found = []
    for pat in disp_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 100_000_000:
                disp_found.append(val)
    if disp_found:
        impact["displaced"] = max(disp_found)

    # ── Affected population ────────────────────────────────────────────────
    aff_patterns = [
        r"([\d,.]+)\s*(?:million\s+)?(?:people\s+)?(?:affected|been affected)",
        r"(?:affected)[:\s]*([\d,]+)",
        r"([\d,]+)\s*(?:people\s+)?(?:had been\s+)?affected",
    ]
    aff_found = []
    for pat in aff_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw = m.group(1).replace(",", "")
            # Handle "million" nearby
            surrounding = text[max(0, m.start() - 5):m.end() + 20]
            if "million" in surrounding.lower():
                try:
                    aff_found.append(int(float(raw) * 1_000_000))
                except ValueError:
                    pass
            else:
                val = safe_int(m.group(1))
                if val and val < 1_000_000_000:
                    aff_found.append(val)
    if aff_found:
        impact["affected_population"] = max(aff_found)

    # ── Houses destroyed / damaged ─────────────────────────────────────────
    hd_patterns = [
        r"([\d,]+)\s*(?:houses?\s+)?(?:have been\s+)?(?:destroyed|collapsed)",
        r"([\d,]+)\s*(?:houses?|homes?)\s*(?:were\s+)?(?:destroyed|torn down|collapsed)",
        r"([\d,]+)\s*(?:housing units?)\s*.*?(?:destroyed|damaged)",
    ]
    hd_found = []
    for pat in hd_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 10_000_000:
                hd_found.append(val)
    if hd_found:
        impact["houses_destroyed"] = max(hd_found)

    hdmg_patterns = [
        r"([\d,]+)\s*(?:houses?|homes?)\s*(?:were\s+)?(?:damaged|affected)",
        r"damaged\s*(?:another\s+)?([\d,]+)\s*(?:houses?|homes?)",
    ]
    hdmg_found = []
    for pat in hdmg_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 10_000_000:
                hdmg_found.append(val)
    if hdmg_found:
        impact["houses_damaged"] = max(hdmg_found)

    # ── Schools ────────────────────────────────────────────────────────────
    sch_patterns = [
        r"([\d,]+)\s*(?:schools?|educational facilities)",
        r"(?:schools?|educational facilities)\s*(?:have been\s+)?(?:affected|damaged|destroyed)[:\s]*([\d,]+)",
    ]
    sch_found = []
    for pat in sch_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            for g in m.groups():
                val = safe_int(g)
                if val and val < 100_000:
                    sch_found.append(val)
    if sch_found:
        impact["schools_affected"] = max(sch_found)

    # ── Hospitals ──────────────────────────────────────────────────────────
    hosp_patterns = [
        r"([\d,]+)\s*(?:hospitals?|healthcare facilities|medical facilities)",
    ]
    hosp_found = []
    for pat in hosp_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val and val < 100_000:
                hosp_found.append(val)
    if hosp_found:
        impact["hospitals_affected"] = max(hosp_found)

    # ── Population exposed to shaking ──────────────────────────────────────
    exp_patterns = [
        r"(?:up to\s+)?([\d,]+)\s*(?:people\s+)?(?:were\s+)?exposed\s+to\s+(?:very\s+)?(?:strong|severe|violent)\s+shaking",
        r"([\d,]+)\s*(?:people\s+)?exposed\s+to\s+(?:strong|severe)",
    ]
    exp_found = []
    for pat in exp_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = safe_int(m.group(1))
            if val:
                exp_found.append(val)
    if exp_found:
        impact["population_exposed_to_shaking"] = max(exp_found)

    return impact


# ── Scrape main disaster page ─────────────────────────────────────────────────


def scrape_disaster_page(url: str) -> dict:
    """
    Scrape the main ReliefWeb disaster page.
    Returns dict with: title, country, description, impact data, headlines from
    visible sections, and the 'View all updates' URL.
    """
    soup = fetch_page(url)
    result = {
        "url": url,
        "title": None,
        "country": None,
        "disaster_description": None,
        "alert_level": None,
        "impact": {},
        "headlines_from_main_page": [],
        "view_all_updates_url": None,
    }

    # ── Title ──────────────────────────────────────────────────────────────
    h1 = soup.find("h1")
    if h1:
        result["title"] = h1.get_text(strip=True)

    # ── Country (from "Affected Countries" section or meta) ────────────────
    # Try the affected countries section
    country_section = None
    for heading in soup.find_all(["h2", "h3"]):
        if "affected countr" in heading.get_text(strip=True).lower():
            country_section = heading
            break

    if country_section:
        # Find the next list or links after this heading
        parent = country_section.find_parent()
        if parent:
            links = parent.find_all("a", href=re.compile(r"/country/"))
            countries = [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
            result["country"] = ", ".join(dict.fromkeys(countries))  # deduplicate preserving order

    if not result["country"]:
        # Fallback: parse from title
        title = result.get("title", "") or ""
        if ":" in title:
            result["country"] = title.split(":")[0].strip()

    # ── Disaster description ───────────────────────────────────────────────
    desc_section = None
    for heading in soup.find_all(["h2", "h3"]):
        if "disaster description" in heading.get_text(strip=True).lower():
            desc_section = heading
            break

    description_text = ""
    if desc_section:
        # Collect all text in the description section
        parent_div = desc_section.find_parent("div") or desc_section.find_parent("section")
        if parent_div:
            # Get all paragraph text after the heading
            for sibling in desc_section.find_next_siblings():
                txt = sibling.get_text(" ", strip=True)
                if txt:
                    description_text += txt + "\n"
            if not description_text.strip():
                description_text = parent_div.get_text(" ", strip=True)

    result["disaster_description"] = description_text.strip()

    # ── Alert level (look for Green / Orange / Red badges) ─────────────────
    alert_keywords = ["green", "orange", "red"]
    for el in soup.find_all(class_=re.compile(r"alert|level|badge|tag|severity", re.IGNORECASE)):
        txt = el.get_text(strip=True).lower()
        for kw in alert_keywords:
            if kw in txt:
                result["alert_level"] = kw.capitalize()
                break
        if result["alert_level"]:
            break

    # If not found in badges, try to find in description
    if not result["alert_level"] and description_text:
        for kw in ["Red alert", "Orange alert", "Green alert"]:
            if kw.lower() in description_text.lower():
                result["alert_level"] = kw
                break

    # ── Impact data from description ───────────────────────────────────────
    result["impact"] = parse_impact_data(description_text)

    # ── Headlines from "Latest Updates", "Maps and Infographics", "Most Read" ─
    headline_sections = [
        "latest updates",
        "maps and infographics",
        "most read",
        "appeals and response plans",
    ]

    seen_urls = set()
    for heading in soup.find_all(["h2", "h3"]):
        heading_text = heading.get_text(strip=True).lower()
        if any(sec in heading_text for sec in headline_sections):
            # Find the parent container
            container = heading.find_parent("div") or heading.find_parent("section")
            if container:
                for a_tag in container.find_all("a", href=True):
                    href = a_tag.get("href", "")
                    title_text = a_tag.get_text(strip=True)

                    # Only include report/map links, skip navigation and country links
                    if (
                        title_text
                        and len(title_text) > 10
                        and ("/report/" in href or "/map/" in href)
                        and href not in seen_urls
                    ):
                        full_url = urljoin(BASE_URL, href)
                        seen_urls.add(href)
                        result["headlines_from_main_page"].append(
                            {
                                "title": title_text,
                                "url": full_url,
                                "section": heading_text.title(),
                            }
                        )

    # ── "View all updates" link ────────────────────────────────────────────
    for a_tag in soup.find_all("a", href=True):
        if "view all" in a_tag.get_text(strip=True).lower() and "updates" in a_tag.get_text(strip=True).lower():
            result["view_all_updates_url"] = urljoin(BASE_URL, a_tag["href"])
            break

    return result


# ── Scrape "View all updates" page (with pagination) ──────────────────────────


def scrape_all_updates(updates_url: str, max_pages: int = 10) -> list[dict]:
    """
    Scrape all headlines from the 'View all updates' page.
    Follows pagination to get the complete list.
    Returns a list of dicts: {title, url, source, date}.
    """
    all_headlines = []
    seen_urls = set()
    current_url = updates_url
    page_num = 0

    while current_url and page_num < max_pages:
        page_num += 1
        print(f"    📄 Updates page {page_num}: {current_url}")

        try:
            soup = fetch_page(current_url)
        except Exception as e:
            print(f"    ⚠️  Failed to fetch page {page_num}: {e}")
            break

        # Find all article/report cards on the page
        # ReliefWeb lists updates as article elements or in a list
        articles = soup.find_all("article")
        if not articles:
            # Fallback: look for list items with report links
            articles = soup.find_all("li")

        for article in articles:
            # Find the main headline link
            link = article.find("a", href=re.compile(r"/report/|/map/"))
            if not link:
                continue

            href = link.get("href", "")
            title_text = link.get_text(strip=True)

            if not title_text or len(title_text) < 10 or href in seen_urls:
                continue

            seen_urls.add(href)
            full_url = urljoin(BASE_URL, href)

            # Try to find the source/organization
            source = ""
            source_el = article.find("span", class_=re.compile(r"source|org", re.IGNORECASE))
            if source_el:
                source = source_el.get_text(strip=True)
            else:
                # Look for organization links
                org_link = article.find("a", href=re.compile(r"/organization/"))
                if org_link:
                    source = org_link.get_text(strip=True)

            # Try to find the date
            date_str = ""
            time_el = article.find("time")
            if time_el:
                date_str = time_el.get("datetime", "") or time_el.get_text(strip=True)
            else:
                date_el = article.find(class_=re.compile(r"date", re.IGNORECASE))
                if date_el:
                    date_str = date_el.get_text(strip=True)

            all_headlines.append(
                {
                    "title": title_text,
                    "url": full_url,
                    "source": source,
                    "date": date_str,
                }
            )

        # ── Pagination: find "Next" link ───────────────────────────────────
        next_link = None
        for a_tag in soup.find_all("a", href=True):
            txt = a_tag.get_text(strip=True).lower()
            if txt in ("next", "next page", "›", "»", "next ›"):
                next_link = urljoin(BASE_URL, a_tag["href"])
                break

        # Also check for rel="next"
        if not next_link:
            rel_next = soup.find("a", rel="next")
            if rel_next and rel_next.get("href"):
                next_link = urljoin(BASE_URL, rel_next["href"])

        if next_link and next_link != current_url:
            current_url = next_link
            time.sleep(1)  # Be polite to the server
        else:
            break

    return all_headlines


# ── Save results ───────────────────────────────────────────────────────────────


def save_to_json(data: list[dict], filepath: str = "disasters_data.json"):
    """Save the full scraped data to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Data saved to {filepath}")


def save_to_csv(data: list[dict], filepath: str = "disasters_data.csv"):
    """Save a flat summary to CSV for easy viewing."""
    rows = []
    for d in data:
        impact = d.get("impact", {})
        row = {
            "Event Label": d.get("label", ""),
            "Event Type": d.get("event_type", ""),
            "Title": d.get("title", ""),
            "Country": d.get("country", ""),
            "URL": d.get("url", ""),
            "Alert Level": d.get("alert_level", "N/A"),
            "Magnitude": impact.get("magnitude", ""),
            "Depth (km)": impact.get("depth_km", ""),
            "Deaths": impact.get("deaths", ""),
            "Injured": impact.get("injured", ""),
            "Missing": impact.get("missing", ""),
            "Displaced": impact.get("displaced", ""),
            "Affected Population": impact.get("affected_population", ""),
            "Population Exposed to Shaking": impact.get("population_exposed_to_shaking", ""),
            "Houses Destroyed": impact.get("houses_destroyed", ""),
            "Houses Damaged": impact.get("houses_damaged", ""),
            "Schools Affected": impact.get("schools_affected", ""),
            "Hospitals Affected": impact.get("hospitals_affected", ""),
            "Total Reports (Main Page)": d.get("total_headlines_main_page", 0),
            "Total Reports (All Updates)": d.get("total_headlines_all_updates", 0),
        }
        rows.append(row)

    if rows:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"💾 Summary CSV saved to {filepath}")

    # Also save headlines to a separate CSV
    headline_rows = []
    for d in data:
        for h in d.get("all_update_headlines", []):
            headline_rows.append(
                {
                    "Event Label": d.get("label", ""),
                    "Event Type": d.get("event_type", ""),
                    "Headline": h.get("title", ""),
                    "Source": h.get("source", ""),
                    "Date": h.get("date", ""),
                    "URL": h.get("url", ""),
                }
            )
        # Also include main page headlines not in all_updates
        for h in d.get("headlines_from_main_page", []):
            headline_rows.append(
                {
                    "Event Label": d.get("label", ""),
                    "Event Type": d.get("event_type", ""),
                    "Headline": h.get("title", ""),
                    "Source": h.get("section", ""),
                    "Date": "",
                    "URL": h.get("url", ""),
                }
            )

    if headline_rows:
        hl_path = filepath.replace(".csv", "_headlines.csv")
        with open(hl_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headline_rows[0].keys())
            writer.writeheader()
            writer.writerows(headline_rows)
        print(f"💾 Headlines CSV saved to {hl_path}")


# ── Pretty-print summary to console ───────────────────────────────────────────


def print_summary(data: list[dict]):
    """Print a formatted summary of scraped data."""
    print("\n" + "=" * 80)
    print("  DISASTER EVOLUTION & RESPONSE PIPELINE — SCRAPING RESULTS")
    print("=" * 80)

    for d in data:
        impact = d.get("impact", {})
        print(f"\n{'─' * 70}")
        print(f"  📌 {d.get('label', 'Unknown')}")
        print(f"  Type: {d.get('event_type', 'N/A')} | Country: {d.get('country', 'N/A')}")
        print(f"  URL:  {d.get('url', '')}")
        print(f"{'─' * 70}")

        print(f"\n  📋 SUMMARY TAB:")
        print(f"     Title:       {d.get('title', 'N/A')}")
        print(f"     Magnitude:   {impact.get('magnitude', 'N/A')}")
        print(f"     Depth:       {impact.get('depth_km', 'N/A')} km")
        print(f"     Alert Level: {d.get('alert_level', 'N/A')}")
        print(f"     Country:     {d.get('country', 'N/A')}")

        print(f"\n  💥 IMPACT TAB:")
        print(f"     Deaths:           {impact.get('deaths', 'N/A')}")
        print(f"     Injured:          {impact.get('injured', 'N/A')}")
        print(f"     Missing:          {impact.get('missing', 'N/A')}")
        print(f"     Displaced:        {impact.get('displaced', 'N/A')}")
        print(f"     Affected Pop:     {impact.get('affected_population', 'N/A')}")
        print(f"     Pop. Exposed:     {impact.get('population_exposed_to_shaking', 'N/A')}")
        print(f"     Houses Destroyed: {impact.get('houses_destroyed', 'N/A')}")
        print(f"     Houses Damaged:   {impact.get('houses_damaged', 'N/A')}")
        print(f"     Schools:          {impact.get('schools_affected', 'N/A')}")
        print(f"     Hospitals:        {impact.get('hospitals_affected', 'N/A')}")

        print(f"\n  📰 MEDIA TAB:")
        print(f"     Reports on main page:  {d.get('total_headlines_main_page', 0)}")
        print(f"     Reports (all updates): {d.get('total_headlines_all_updates', 0)}")

        # Show first 5 headlines
        headlines = d.get("all_update_headlines", []) or d.get("headlines_from_main_page", [])
        if headlines:
            print(f"     Sample headlines:")
            for h in headlines[:5]:
                print(f"       • {h.get('title', '')[:80]}")
            if len(headlines) > 5:
                print(f"       ... and {len(headlines) - 5} more")

    print(f"\n{'=' * 80}\n")


# ── Main pipeline ─────────────────────────────────────────────────────────────


def main():
    print("🚀 Starting Disaster Evolution & Response Pipeline — Web Scraper")
    print(f"   Scraping {len(DISASTER_URLS)} disaster events from ReliefWeb...\n")

    all_data = []

    for i, event in enumerate(DISASTER_URLS, 1):
        print(f"\n{'━' * 60}")
        print(f"  [{i}/{len(DISASTER_URLS)}] Scraping: {event['label']}")
        print(f"{'━' * 60}")

        # Step 1: Scrape main disaster page
        try:
            page_data = scrape_disaster_page(event["url"])
        except Exception as e:
            print(f"  ❌ Error scraping main page: {e}")
            page_data = {"url": event["url"], "title": None, "impact": {}}

        # Add metadata
        page_data["label"] = event["label"]
        page_data["event_type"] = event["event_type"]
        page_data["total_headlines_main_page"] = len(page_data.get("headlines_from_main_page", []))

        # Step 2: Scrape all updates (complete headlines list)
        updates_url = page_data.get("view_all_updates_url")
        if updates_url:
            print(f"\n  📰 Scraping all update headlines...")
            try:
                all_headlines = scrape_all_updates(updates_url)
                page_data["all_update_headlines"] = all_headlines
                page_data["total_headlines_all_updates"] = len(all_headlines)
                print(f"  ✅ Found {len(all_headlines)} headlines from updates pages")
            except Exception as e:
                print(f"  ⚠️  Error scraping updates: {e}")
                page_data["all_update_headlines"] = []
                page_data["total_headlines_all_updates"] = 0
        else:
            print(f"  ⚠️  No 'View all updates' link found")
            page_data["all_update_headlines"] = []
            page_data["total_headlines_all_updates"] = 0

        all_data.append(page_data)

        # Be polite — wait between events
        if i < len(DISASTER_URLS):
            print(f"\n  ⏳ Waiting 2 seconds before next event...")
            time.sleep(2)

    # Step 3: Save results
    print(f"\n{'━' * 60}")
    print("  💾 Saving results...")
    print(f"{'━' * 60}")

    save_to_json(all_data, "disasters_data.json")
    save_to_csv(all_data, "disasters_data.csv")

    # Step 4: Print summary
    print_summary(all_data)

    print("✅ Scraping pipeline complete!")


if __name__ == "__main__":
    main()
