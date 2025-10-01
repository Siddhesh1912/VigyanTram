import asyncio
import re
import urllib.parse
from typing import List, Dict

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower())


def build_listing_url(query: str) -> str:
    return f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(query)}&as=on&as-show=on"


def parse_listing(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag['href']
        if "/p/" in href:
            full_link = "https://www.flipkart.com" + href.split("?")[0]
            if full_link not in links:
                links.append(full_link)
    return links


def parse_product_details(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    data: Dict[str, str] = {}

    title = soup.find("span", class_="VU-ZEz")
    if title:
        data["Product Name"] = title.get_text(strip=True)

    container = soup.find("div", class_="DOjaWF gdgoEp col-8-12")
    if container:
        data["Raw_HTML"] = str(container)
        data["Raw_Text"] = container.get_text(separator=" ", strip=True)

    return data


class FlipkartPlaywrightScraper:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._page = await self._browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        ))

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def fetch_html(self, url: str, wait_ms: int = 5000) -> str:
        await self._page.goto(url, timeout=60000)
        await self._page.wait_for_timeout(wait_ms)
        return await self._page.content()

    async def scrape_category(self, query: str, max_pages: int = 1) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        base_url = build_listing_url(query)
        for page in range(1, max_pages + 1):
            page_url = f"{base_url}&page={page}"
            listing_html = await self.fetch_html(page_url)
            product_links = parse_listing(listing_html)
            if not product_links:
                break
            for link in product_links:
                prod_html = await self.fetch_html(link)
                prod_info = parse_product_details(prod_html)
                if prod_info:
                    # Map to common fields for CSV writer compatibility
                    mapped = {
                        "name": prod_info.get("Product Name", ""),
                        "price": "",
                        "details": prod_info.get("Raw_Text", ""),
                        "product_link": link,
                        "image_url": "",
                    }
                    results.append(mapped)
        return results


def _category_to_query(category: str) -> str:
    mapping = {
        "protein": "protein powder",
        "mobile": "mobile phones",
        "laptop": "laptop",
    }
    return mapping.get((category or "").lower(), category or "")


def scrape_category_sync(category: str, max_pages: int = 1) -> List[Dict[str, str]]:
    """Synchronous wrapper for Flask route usage."""
    async def _run() -> List[Dict[str, str]]:
        scraper = FlipkartPlaywrightScraper()
        await scraper.start()
        try:
            query = _category_to_query(category)
            return await scraper.scrape_category(query, max_pages=max_pages)
        finally:
            await scraper.close()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # If loop is already running (e.g., in certain environments), create a new one
    if loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(_run())
        finally:
            new_loop.close()
    else:
        return loop.run_until_complete(_run())


