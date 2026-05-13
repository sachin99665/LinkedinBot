# tech_news_fetcher.py
import os
import json
import hashlib
import asyncio
import requests
import xml.etree.ElementTree as ET

STATE_FILE = "news_state.json"
MAX_ENTRIES_PER_FEED = 3

TECH_FEEDS = [
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Wired", "https://www.wired.com/feed/rss"),
    ("Hacker News", "https://news.ycombinator.com/rss"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
]

# Simple RSS parser (without feedparser)
def parse_rss(url):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item"):
            title = item.find("title")
            link = item.find("link")
            if title is not None and link is not None:
                items.append({
                    "title": title.text,
                    "link": link.text
                })
        return items
    except Exception as e:
        print(f"RSS parse error for {url}: {e}")
        return []

class TechNewsFetcher:
    def __init__(self):
        self.state = self._load_state()
    
    def _load_state(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        return {"posted_ids": []}
    
    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)
    
    def _hash_article(self, title, link):
        unique = (title + link).strip().lower()
        return hashlib.md5(unique.encode()).hexdigest()[:16]
    
    async def fetch_new_articles(self):
        new_items = []
        for source_name, url in TECH_FEEDS:
            try:
                entries = parse_rss(url)
                await asyncio.sleep(0.5)
                for entry in entries[:MAX_ENTRIES_PER_FEED]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    if not title or not link:
                        continue
                    article_id = self._hash_article(title, link)
                    if article_id not in self.state["posted_ids"]:
                        msg = self._format_message(source_name, title, link)
                        new_items.append({"id": article_id, "msg": msg})
            except Exception as e:
                print(f"Error fetching {source_name}: {e}")
        return new_items
    
    def _format_message(self, source, title, link):
        return f"📡 **{source}**\n📰 [{title}]({link})\n🔗 [Read more]({link})"
    
    async def check_and_send(self, bot, chat_id):
        new_articles = await self.fetch_new_articles()
        if not new_articles:
            return 0
        sent_count = 0
        for article in new_articles:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=article["msg"],
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                self.state["posted_ids"].append(article["id"])
                sent_count += 1
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Send error: {e}")
        self.state["posted_ids"] = self.state["posted_ids"][-500:]
        self._save_state()
        return sent_count