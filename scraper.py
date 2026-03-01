import re, json, csv, time, html
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DISASTER_URLS = [
    {"url": "https://reliefweb.int/disaster/eq-2022-000363-idn", "event_type": "Recent", "label": "Indonesia Earthquake Nov 2022"},
    {"url": "https://reliefweb.int/disaster/eq-2008-000226-idn", "event_type": "Historical", "label": "Indonesia Earthquake Nov 2008"},
    {"url": "https://reliefweb.int/disaster/eq-2025-000043-mmr", "event_type": "Recent", "label": "Myanmar Earthquake Mar 2025"},
    {"url": "https://reliefweb.int/disaster/eq-2012-000112-chn", "event_type": "Historical", "label": "China Earthquake Jun 2012"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
BASE_URL = "https://reliefweb.int"

WORD_TO_NUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,
               "eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"twenty":20,"thirty":30,
               "forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90,"hundred":100}

def fetch_page(url):
    print(f"  Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")

def safe_int(text):
    if not text: return None
    cleaned = text.replace(",", "").replace(".", "")
    m = re.search(r"\d+", cleaned)
    return int(m.group()) if m else None

def clean_text(text):
    if not text: return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [l.strip(" \t,;|–—-") for l in text.splitlines() if l.strip()]
    return "\n".join(lines).strip()

def find_all_matches(patterns, text, limit=1000000):
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            for g in m.groups():
                if g:
                    val = safe_int(g)
                    if val and val < limit: found.append(val)
    return found

def parse_impact_data(text):
    impact = {"magnitude": None, "depth_km": None, "deaths": None, "injured": None,
              "missing": None, "displaced": None, "affected_population": None,
              "population_exposed_to_shaking": None}

    for pat in [r"(\d+\.?\d*)\s*(?:M|magnitude)", r"magnitude[:\s]*(\d+\.?\d*)",
                r"(\d+\.?\d*)\s*(?:on the Richter scale)", r"(\d+\.?\d*)-magnitude"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            impact["magnitude"] = float(m.group(1))
            break

    depth_m = re.search(r"depth\s+of\s+(\d+)\s*km", text, re.IGNORECASE)
    if depth_m: impact["depth_km"] = int(depth_m.group(1))

    deaths_found = find_all_matches([
        r"([\d,]+)\s*(?:people\s+)?(?:fatalities|deaths|dead|killed|death toll)",
        r"(?:fatalities|deaths|death toll|killed|killing)\s*(?:of|at least|over|reached|stood at over)?\s*([\d,]+)",
        r"([\d,]+)\s*(?:people\s+)?(?:have\s+)?(?:died|confirmed\s+killed)",
        r"killing\s+(?:at least\s+)?([\d,]+)", r"([\d,]+)\s+people\s+(?:were\s+)?killed",
    ], text, 1000000)
    for m in re.finditer(r"(?:killing|killed)\s+(?:at least\s+)?(\w+)\s+(?:people|persons)", text, re.IGNORECASE):
        wval = WORD_TO_NUM.get(m.group(1).lower())
        if wval: deaths_found.append(wval)
    if deaths_found: impact["deaths"] = max(deaths_found)

    injured_found = find_all_matches([
        r"([\d,]+)\s*(?:people\s+)?(?:injured|hurt|sustained injuries)",
        r"(?:injured|injuries|injuring)[:\s]*([\d,]+)", r"([\d,]+)\s*injured",
        r"(?:climbed to|reached)\s*([\d,]+)\s*(?:people\s+)?(?:injured)?",
        r"injuring\s+([\d,]+)",
    ], text, 10000000)
    for m in re.finditer(r"injuring\s+(\w+)\b", text, re.IGNORECASE):
        wval = WORD_TO_NUM.get(m.group(1).lower())
        if wval: injured_found.append(wval)
    if injured_found: impact["injured"] = max(injured_found)

    missing_found = find_all_matches([
        r"([\d,]+)\s*(?:people\s+)?(?:missing|still missing|unaccounted)",
        r"(?:missing)[:\s]*([\d,]+)",
    ], text, 1000000)
    if missing_found: impact["missing"] = max(missing_found)

    disp_found = find_all_matches([
        r"([\d,]+)\s*(?:people\s+)?(?:displaced|evacuated|fled|left homeless)",
        r"(?:displaced|evacuated)[:\s]*([\d,]+)", r"([\d,]+)\s*(?:have been\s+)?displaced",
    ], text, 100000000)
    if disp_found: impact["displaced"] = max(disp_found)

    aff_found = []
    for pat in [r"([\d,.]+)\s*(?:million\s+)?(?:people\s+)?(?:affected|been affected)",
                r"(?:affected)[:\s]*([\d,]+)", r"([\d,]+)\s*(?:people\s+)?(?:had been\s+)?affected"]:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw = m.group(1).replace(",", "")
            surrounding = text[max(0, m.start()-5):m.end()+20]
            if "million" in surrounding.lower():
                try: aff_found.append(int(float(raw) * 1000000))
                except: pass
            else:
                val = safe_int(m.group(1))
                if val and val < 1000000000: aff_found.append(val)
    if aff_found: impact["affected_population"] = max(aff_found)

    exp_found = find_all_matches([
        r"(?:up to\s+)?([\d,]+)\s*(?:people\s+)?(?:were\s+)?exposed\s+to\s+(?:very\s+)?(?:strong|severe|violent)\s+shaking",
        r"([\d,]+)\s*(?:people\s+)?exposed\s+to\s+(?:strong|severe)",
    ], text)
    if exp_found: impact["population_exposed_to_shaking"] = max(exp_found)

    specific = sum(impact.get(k) or 0 for k in ["deaths","injured","missing","displaced"])
    broad = [v for k in ["affected_population","population_exposed_to_shaking"] if (v := impact.get(k))]
    best = max([specific] + broad) if [specific] + broad else 0
    impact["total_population_affected"] = best if best > 0 else None

    return impact

def scrape_disaster_page(url):
    soup = fetch_page(url)
    result = {"url": url, "title": None, "country": None, "disaster_description": None,
              "impact": {}, "headlines_from_main_page": [], "view_all_updates_url": None}

    h1 = soup.find("h1")
    if h1: result["title"] = clean_text(h1.get_text(strip=True))

    for heading in soup.find_all(["h2","h3"]):
        if "affected countr" in heading.get_text(strip=True).lower():
            parent = heading.find_parent()
            if parent:
                links = parent.find_all("a", href=re.compile(r"/country/"))
                countries = [clean_text(a.get_text(strip=True)) for a in links if a.get_text(strip=True)]
                result["country"] = ", ".join(dict.fromkeys(countries))
            break

    if not result["country"]:
        title = result.get("title", "") or ""
        if ":" in title: result["country"] = clean_text(title.split(":")[0])

    desc_text = ""
    for heading in soup.find_all(["h2","h3"]):
        if "disaster description" in heading.get_text(strip=True).lower():
            parent_div = heading.find_parent("div") or heading.find_parent("section")
            if parent_div:
                for sib in heading.find_next_siblings():
                    txt = sib.get_text(" ", strip=True)
                    if txt: desc_text += txt + "\n"
                if not desc_text.strip():
                    desc_text = parent_div.get_text(" ", strip=True)
            break

    result["disaster_description"] = clean_text(desc_text)
    result["impact"] = parse_impact_data(desc_text)

    seen_urls = set()
    for heading in soup.find_all(["h2","h3"]):
        htxt = heading.get_text(strip=True).lower()
        if any(s in htxt for s in ["latest updates","maps and infographics","most read","appeals and response plans"]):
            container = heading.find_parent("div") or heading.find_parent("section")
            if container:
                for a in container.find_all("a", href=True):
                    href = a.get("href","")
                    title_text = a.get_text(strip=True)
                    if title_text and len(title_text) > 10 and ("/report/" in href or "/map/" in href) and href not in seen_urls:
                        seen_urls.add(href)
                        result["headlines_from_main_page"].append(
                            {"title": clean_text(title_text), "url": urljoin(BASE_URL, href), "section": clean_text(htxt.title())})

    for a in soup.find_all("a", href=True):
        if "view all" in a.get_text(strip=True).lower() and "updates" in a.get_text(strip=True).lower():
            result["view_all_updates_url"] = urljoin(BASE_URL, a["href"])
            break

    return result

def scrape_all_updates(updates_url, max_pages=15):
    all_headlines, seen = [], set()
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(updates_url)
    base_params = parse_qs(parsed.query)
    for k in base_params: base_params[k] = base_params[k][0]

    for page_num in range(max_pages):
        params = dict(base_params)
        if page_num > 0: params["page"] = str(page_num)
        page_url = urlunparse(parsed._replace(query=urlencode(params)))
        print(f"    Page {page_num+1}: {page_url}")
        try: soup = fetch_page(page_url)
        except Exception as e:
            print(f"    Failed page {page_num+1}: {e}")
            break

        new_count = 0
        articles = soup.find_all("article") or soup.find_all("li")
        for article in articles:
            link = article.find("a", href=re.compile(r"/report/|/map/"))
            if not link: continue
            href = link.get("href","")
            title_text = clean_text(link.get_text(strip=True))
            if not title_text or len(title_text) < 10 or href in seen: continue
            seen.add(href)

            source = ""
            src_el = article.find("span", class_=re.compile(r"source|org", re.IGNORECASE))
            if src_el: source = clean_text(src_el.get_text(strip=True))
            else:
                org_link = article.find("a", href=re.compile(r"/organization/"))
                if org_link: source = clean_text(org_link.get_text(strip=True))

            date_str = ""
            time_el = article.find("time")
            if time_el: date_str = clean_text(time_el.get("datetime","") or time_el.get_text(strip=True))
            else:
                date_el = article.find(class_=re.compile(r"date", re.IGNORECASE))
                if date_el: date_str = clean_text(date_el.get_text(strip=True))

            if not date_str: continue
            all_headlines.append({"title": title_text, "url": urljoin(BASE_URL, href), "source": source, "date": date_str})
            new_count += 1

        print(f"    Got {new_count} new articles (total: {len(all_headlines)})")
        if new_count == 0: break
        time.sleep(1)

    return all_headlines

def save_to_json(data, filepath="disasters_data.json"):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nData saved to {filepath}")

def save_to_csv(data, filepath="disasters_data.csv"):
    rows = []
    for d in data:
        imp = d.get("impact", {})
        rows.append({
            "Event Label": d.get("label",""), "Event Type": d.get("event_type",""),
            "Title": d.get("title",""), "Country": d.get("country",""), "URL": d.get("url",""),
            "Magnitude": imp.get("magnitude",""), "Depth (km)": imp.get("depth_km",""),
            "Deaths": imp.get("deaths",""), "Injured": imp.get("injured",""),
            "Missing": imp.get("missing",""), "Displaced": imp.get("displaced",""),
            "Affected Population": imp.get("affected_population",""),
            "Population Exposed to Shaking": imp.get("population_exposed_to_shaking",""),
            "Total Population Affected": imp.get("total_population_affected",""),
            "Total Reports": d.get("total_headlines_all_updates",0) or d.get("total_headlines_main_page",0),
        })
    if rows:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=rows[0].keys()).writeheader()
            csv.DictWriter(f, fieldnames=rows[0].keys()).writerows(rows)
        print(f"CSV saved to {filepath}")

    hl_rows = []
    for d in data:
        for h in d.get("all_update_headlines", []):
            hl_rows.append({"Event Label": d.get("label",""), "Event Type": d.get("event_type",""),
                            "Headline": h.get("title",""), "Source": h.get("source",""),
                            "Date": h.get("date",""), "URL": h.get("url","")})
        for h in d.get("headlines_from_main_page", []):
            hl_rows.append({"Event Label": d.get("label",""), "Event Type": d.get("event_type",""),
                            "Headline": h.get("title",""), "Source": h.get("section",""),
                            "Date": "", "URL": h.get("url","")})
    if hl_rows:
        hl_path = filepath.replace(".csv", "_headlines.csv")
        with open(hl_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=hl_rows[0].keys())
            w.writeheader(); w.writerows(hl_rows)
        print(f"Headlines saved to {hl_path}")

def print_summary(data):
    print("\nResults:")
    for d in data:
        imp = d.get("impact", {})
        total = d.get('total_headlines_all_updates',0) or d.get('total_headlines_main_page',0)
        print(f"  {d.get('label','Unknown')} | Mag: {imp.get('magnitude','N/A')} | Deaths: {imp.get('deaths','N/A')} | Headlines: {total}")

def main():
    print(f"Scraping {len(DISASTER_URLS)} disaster events from ReliefWeb...\n")
    all_data = []
    for i, event in enumerate(DISASTER_URLS, 1):
        print(f"\n[{i}/{len(DISASTER_URLS)}] {event['label']}")
        try: page_data = scrape_disaster_page(event["url"])
        except Exception as e:
            print(f"  Error: {e}")
            page_data = {"url": event["url"], "title": None, "impact": {}}

        page_data["label"] = event["label"]
        page_data["event_type"] = event["event_type"]
        page_data["total_headlines_main_page"] = len(page_data.get("headlines_from_main_page", []))

        updates_url = page_data.get("view_all_updates_url")
        if updates_url:
            print(f"  Scraping headlines...")
            try:
                headlines = scrape_all_updates(updates_url)
                page_data["all_update_headlines"] = headlines
                page_data["total_headlines_all_updates"] = len(headlines)
                print(f"  Found {len(headlines)} headlines")
            except Exception as e:
                print(f"  Error scraping updates: {e}")
                page_data["all_update_headlines"] = []
                page_data["total_headlines_all_updates"] = 0
        else:
            page_data["all_update_headlines"] = []
            page_data["total_headlines_all_updates"] = 0

        all_data.append(page_data)
        if i < len(DISASTER_URLS):
            time.sleep(2)

    save_to_json(all_data)
    save_to_csv(all_data)
    print_summary(all_data)
    print("\nDone!")

if __name__ == "__main__":
    main()
