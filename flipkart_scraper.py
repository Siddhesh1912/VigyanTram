import os
import csv
from datetime import datetime
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _category_to_query(category: str) -> str:
    mapping = {
        "protein": "whey protein",
        "mobile": "mobile phones",
        "laptop": "laptop",
    }
    return mapping.get((category or "").lower(), category or "")


def _build_search_urls(query: str, pages: int = 2) -> List[str]:
    # Flipkart search URL pattern; keep pages small to be polite
    base = "https://www.flipkart.com/search?q="
    return [f"{base}{requests.utils.quote(query)}&page={p}" for p in range(1, pages + 1)]


def _parse_search_page(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, str]] = []

    # Flipkart uses multiple card templates; try a few common ones
    cards = []
    cards.extend(soup.select("div._1AtVbE"))
    cards.extend(soup.select("div._2kHMtA"))
    cards.extend(soup.select("div._4ddWXP"))

    for card in cards:
        title_el = card.select_one("a.s1Q9rs, a.IRpwTa, ._4rR01T")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        link = title_el.get("href") or title_el.get("to")
        if link and link.startswith("/"):
            link = "https://www.flipkart.com" + link

        price_el = card.select_one("._30jeq3._1_WHN1, ._30jeq3")
        price = price_el.get_text(strip=True) if price_el else ""

        details_el = card.select_one("ul._1xgFaf, ul._1xgFaf li, .IRpwTa")
        details = details_el.get_text(" | ", strip=True) if details_el else ""

        img_el = card.select_one("img._396cs4, img._2r_T1I, img._1a8UBa")
        image_url = img_el.get("src") if img_el else ""

        if name:
            items.append({
                "name": name,
                "price": price,
                "details": details,
                "product_link": link or "",
                "image_url": image_url or "",
            })

    return items


def scrape_flipkart_category(category: str, time_filter: str, max_pages: int = 2) -> List[Dict[str, str]]:
    """Scrape Flipkart listing results for a category keyword.

    time_filter is accepted for future extension but not used (Flipkart search lacks simple time filters).
    """
    query = _category_to_query(category)
    if not query:
        return []

    urls = _build_search_urls(query, pages=max_pages)
    results: List[Dict[str, str]] = []
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            items = _parse_search_page(resp.text)
            results.extend(items)
        except Exception:
            continue

    # Deduplicate by link then name
    seen = set()
    unique: List[Dict[str, str]] = []
    for item in results:
        key = item.get("product_link") or item.get("name")
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # Enrich common fields
    now_iso = datetime.now().isoformat()
    for item in unique:
        item["scraped_at"] = now_iso
        item["source"] = "flipkart"
        item["category"] = category
        item["time_filter"] = time_filter or ""

    return unique


def write_scraped_csv(rows: List[Dict[str, str]], csv_path: str) -> Tuple[str, int]:
    if not rows:
        return csv_path, 0
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    file_exists = os.path.exists(csv_path)
    fieldnames = [
        "scraped_at", "source", "category", "time_filter",
        "name", "price", "details", "product_link", "image_url",
    ]
    with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
    return csv_path, len(rows)


