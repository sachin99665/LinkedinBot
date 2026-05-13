from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import re
import requests
import os
import random
import json
import urllib.parse
import xml.etree.ElementTree as ET
from flask import Flask, jsonify
import threading  # ✅ Correct - 's' hatao
from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import asyncio

from linkedin_publish import publish_to_linkedin
from tech_news_fetcher import TechNewsFetcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

SCHEDULE_FILE = "schedule.json"
HISTORY_FILE = "post_history.json"
QUEUE_FILE = "post_queue.json"
QUEUE_MAX = 7

TONES = {"formal", "casual", "humorous", "professional"}
LENGTHS = {"short", "long"}

LOCAL_POSTS = [
    "🚀 AI is transforming QA — but it's not replacing testers.\n\nIt's eliminating the boring parts: repetitive test cases, flaky assertions, slow regression runs.\n\nThe best QA engineers are the ones learning to guide AI, not fight it.\n\n#QA #AIAutomation #SoftwareTesting",
    "🎭 Playwright has become my go-to for end-to-end testing.\n\nAuto-waiting. Parallel execution. Built-in tracing.\n\nNo more fighting with Selenium timeouts or brittle XPath selectors.\n\nIf you haven't tried it, your future self will thank you.\n\n#Playwright #TestAutomation #QA",
    "🔍 The most expensive bug is the one that reaches production.\n\nShift-left testing means catching issues at the design stage — before a single line of code is written.\n\nQA isn't a phase. It's a mindset.\n\n#ShiftLeft #QualityEngineering #SoftwareTesting",
    "⚡ Flaky tests are not a test problem. They're a trust problem.\n\nWhen tests randomly fail, developers ignore them. When developers ignore them, bugs ship.\n\nInvest in stability. Your pipeline is only as reliable as your test suite.\n\n#TestAutomation #CICD #QA",
    "🤖 AI-generated test cases are impressive.\n\nBut AI doesn't know your business logic, your edge cases, or why that one field has a 47-character limit for a very specific reason.\n\nUse AI to scale. Use human insight to stay accurate.\n\n#AITesting #QualityEngineering #Playwright",
    "📊 Code coverage is a metric, not a goal.\n\n100% coverage on happy paths with 0% on edge cases gives you false confidence.\n\nTest by risk, not by number.\n\n#QA #TestStrategy #SoftwareTesting",
    "🛠️ Playwright's trace viewer is the debugging tool I didn't know I needed.\n\nFull visual timeline. Network requests. Console logs. Screenshots at every step.\n\nNo more guessing why a test failed in CI.\n\n#Playwright #QA #TestAutomation",
    "💡 Quality is everyone's job — not just QA's.\n\nWhen devs write unit tests, designers think about edge cases, and PMs write clear acceptance criteria — bugs have nowhere to hide.\n\nBuild quality in. Don't bolt it on.\n\n#QualityEngineering #Agile #SoftwareDevelopment",
]


# ===================== SIMPLE RSS PARSER (replaces feedparser) =====================
def parse_rss(url):
    """Fetch and parse RSS feed using requests and ElementTree."""
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


# =========================
# SCHEDULE PERSISTENCE
# =========================
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r") as f:
            return json.load(f)
    return None

def save_schedule(hour: int, minute: int, chat_id: int):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump({"hour": hour, "minute": minute, "chat_id": chat_id}, f)

def delete_schedule():
    if os.path.exists(SCHEDULE_FILE):
        os.remove(SCHEDULE_FILE)


# =========================
# POST HISTORY
# =========================
def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_to_history(post_text: str, topic: str = ""):
    history = load_history()
    history.append({
        "date": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC"),
        "topic": topic or "auto",
        "text": post_text,
    })
    history = history[-50:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def get_recent_topics(n: int = 5) -> list:
    history = load_history()
    return [entry["topic"] for entry in history[-n:]]


# =========================
# POST QUEUE
# =========================
def load_queue() -> list:
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            return json.load(f)
    return []

def save_queue(queue: list):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)

def queue_add(topic: str) -> str:
    queue = load_queue()
    if len(queue) >= QUEUE_MAX:
        return f"Queue is full ({QUEUE_MAX} posts max). Use /queue list or /queue clear."
    queue.append({
        "topic": topic,
        "added": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M UTC"),
    })
    save_queue(queue)
    return f"Added to queue ({len(queue)}/{QUEUE_MAX}): {topic}"

def queue_pop(index=0):
    q = load_queue()
    if not q or index >= len(q):
        return None
    item = q.pop(index)
    save_queue(q)
    return item


# =========================
# PARSE /post ARGS
# =========================
def parse_post_args(args: list) -> tuple:
    tone = ""
    length = ""
    for arg in args:
        a = arg.lower()
        if a in TONES:
            tone = a
        elif a in LENGTHS:
            length = a
    return tone, length


# =========================
# GENERATE POST
# =========================
def call_groq(prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 400,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    data = response.json()
    if "choices" not in data:
        raise RuntimeError(data.get("error", {}).get("message", str(data)))
    return data["choices"][0]["message"]["content"].strip()

def generate_post(topic: str = "", tone: str = "", length: str = "") -> str:
    if GROQ_API_KEY:
        try:
            recent = get_recent_topics(5)
            avoid_hint = (
                f" Do NOT repeat or closely resemble these recent topics: {', '.join(recent)}."
                if recent else ""
            )
            tone_hint = f" Write in a {tone} tone." if tone else ""
            if length == "short":
                length_hint = " Keep it under 100 words."
            elif length == "long":
                length_hint = " Write 250-299 words — detailed, insightful, and engaging."
            else:
                length_hint = " Keep it under 120 words."
            base_topic = topic if topic else (
                "one of: Software Testing, QA Automation, Playwright, or AI tools in testing"
            )
            prompt = (
                f"Write a professional LinkedIn post about: {base_topic}."
                f"{tone_hint}{length_hint}{avoid_hint} "
                "Structure the post in short, clear paragraphs (2-4 sentences each) with a blank line between each paragraph. "
                "Add 2-3 relevant emojis and 3 hashtags at the end. "
                "Only output the post text, nothing else."
            )
            return call_groq(prompt)
        except Exception as e:
            print(f"Groq unavailable ({e}), using local post.")
    return random.choice(LOCAL_POSTS)


# =========================
# IMAGE GENERATION
# =========================
def generate_image_bytes(topic: str) -> bytes:
    prompt = (
        f"Professional LinkedIn post visual about {topic}. "
        "Clean, modern, corporate style. No text. High quality."
    )
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        "?width=1200&height=628&nologo=true"
    )
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Image generation failed ({resp.status_code})")
    return resp.content


# =========================
# AUTO-POST JOB
# =========================
async def auto_post_job(context):
    chat_id = context.job.data["chat_id"]
    try:
        queued = queue_pop()
        if queued:
            topic_used = queued["topic"]
            post_text = generate_post(topic=topic_used)
            label = f"Queued topic: {topic_used}"
        else:
            topic_used = "scheduled"
            post_text = generate_post()
            label = "Random auto-post"
        publish_to_linkedin(post_text)
        save_to_history(post_text, topic=topic_used)
        remaining = len(load_queue())
        queue_note = f"\n\n{remaining} post{'s' if remaining != 1 else ''} left in queue." if queued else ""
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Scheduled post published! ({label})\n\n{post_text}{queue_note}",
        )
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❗ Scheduled post failed: {e}",
        )


# =========================
# SHARED HELPER
# =========================
def make_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
         InlineKeyboardButton("🔄 Rewrite", callback_data="rewrite")],
    ])


# =========================
# /POST COMMAND
# =========================
async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tone, length = parse_post_args(context.args or [])
    label_parts = []
    if tone:
        label_parts.append(tone)
    if length:
        label_parts.append(length)
    label = f" ({', '.join(label_parts)})" if label_parts else ""
    if label:
        await update.message.reply_text(f"✍️ Generating{label} post...")
    ai_post = generate_post(tone=tone, length=length)
    context.user_data["approved_post"] = ai_post
    context.user_data["last_topic"] = ""
    context.user_data["last_tone"] = tone
    context.user_data["last_length"] = length
    await update.message.reply_text(ai_post, reply_markup=make_keyboard())


# =========================
# /TOPIC COMMAND
# =========================
async def topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /topic <your topic>\n\nExamples:\n"
            "/topic AI in healthcare\n/topic remote work productivity\n/topic Python automation tips"
        )
        return
    user_topic = " ".join(context.args)
    await update.message.reply_text(f"✍️ Generating post about: {user_topic}...")
    ai_post = generate_post(topic=user_topic)
    context.user_data["approved_post"] = ai_post
    context.user_data["last_topic"] = user_topic
    context.user_data["last_tone"] = ""
    context.user_data["last_length"] = ""
    await update.message.reply_text(ai_post, reply_markup=make_keyboard())


# =========================
# PLAIN TEXT → TOPIC
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_topic = update.message.text.strip()
    await update.message.reply_text(f"✍️ Generating post about: {user_topic}...")
    ai_post = generate_post(topic=user_topic)
    context.user_data["approved_post"] = ai_post
    context.user_data["last_topic"] = user_topic
    context.user_data["last_tone"] = ""
    context.user_data["last_length"] = ""
    await update.message.reply_text(ai_post, reply_markup=make_keyboard())


# =========================
# /HELP COMMAND
# =========================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Here's everything this bot can do:\n\n"
        "POST GENERATION\n"
        "/post — random LinkedIn post\n"
        "/post formal — formal tone\n"
        "/post casual — casual/friendly tone\n"
        "/post humorous — fun, light-hearted tone\n"
        "/post short — ~100 words\n"
        "/post long — ~250-299 words\n"
        "/post formal long — combine tone + length\n"
        "/topic <subject> — post on a custom topic\n"
        "/imagepost <subject> — post with AI image\n"
        "Just type anything — treated as a topic\n\n"
        "PUBLISHING\n"
        "/preview — see last generated post again\n"
        "/retry — republish last approved post to LinkedIn\n"
        "/quote — generate a punchy one-liner quote\n\n"
        "Every post shows 2 buttons:\n"
        "  ✅ Approve — post to LinkedIn\n"
        "  🔄 Rewrite — regenerate the post\n\n"
        "POST QUEUE (up to 7 planned ahead)\n"
        "/queue add <topic> — add a topic to the queue\n"
        "/queue list — see all queued topics\n"
        "/queue next — publish the next queued post now\n"
        "/queue remove <number> — remove item by position\n"
        "/queue clear — empty the entire queue\n\n"
        "SCHEDULING\n"
        "/schedule HH:MM — auto-post daily (UTC)\n"
        "/unschedule — stop auto-posting\n\n"
        "INSIGHTS\n"
        "/history — last 5 published posts\n"
        "/stats — top topics + weekly activity\n"
        "/status — schedule info + total post count\n"
        "/trend — fetch trending QA/automation topics and create post\n"
        "/inspire — generate an inspirational quote with AI commentary\n"
        "/news — fetch latest tech news and create a LinkedIn post\n"
        "/technews — manually fetch latest tech news and send alert\n\n"
    )
    await update.message.reply_text(msg)


# =========================
# /QUEUE COMMAND
# =========================
async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    subcommand = args[0].lower() if args else ""
    if subcommand == "add":
        topic_text = " ".join(args[1:]).strip()
        if not topic_text:
            await update.message.reply_text("Usage: /queue add <topic>")
            return
        msg = queue_add(topic_text)
        await update.message.reply_text(msg)
    elif subcommand == "list":
        q = load_queue()
        if not q:
            await update.message.reply_text("Queue is empty.")
            return
        lines = [f"Queued posts ({len(q)}/{QUEUE_MAX}):\n"]
        for i, item in enumerate(q, 1):
            lines.append(f"{i}. {item['topic']}\n   Added: {item['added']}")
        await update.message.reply_text("\n".join(lines))
    elif subcommand == "next":
        item = queue_pop()
        if not item:
            await update.message.reply_text("Queue is empty.")
            return
        await update.message.reply_text(f"Generating post for: {item['topic']}...")
        try:
            post_text = generate_post(topic=item["topic"])
            publish_to_linkedin(post_text)
            save_to_history(post_text, topic=item["topic"])
            remaining = len(load_queue())
            note = f"\n\n{remaining} post left." if remaining else "\n\nQueue empty."
            await update.message.reply_text(f"✅ Published: {item['topic']}\n\n{post_text}{note}")
        except Exception as e:
            await update.message.reply_text(f"❗ Failed: {e}")
    elif subcommand == "remove":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("Usage: /queue remove <number>")
            return
        idx = int(args[1]) - 1
        q = load_queue()
        if idx < 0 or idx >= len(q):
            await update.message.reply_text(f"No item at position {args[1]}")
            return
        removed = q.pop(idx)
        save_queue(q)
        await update.message.reply_text(f"Removed: {removed['topic']}\n{len(q)} items left.")
    elif subcommand == "clear":
        q = load_queue()
        if not q:
            await update.message.reply_text("Queue already empty.")
            return
        save_queue([])
        await update.message.reply_text(f"Cleared {len(q)} items.")
    else:
        await update.message.reply_text(
            "Queue commands:\n/queue add <topic>\n/queue list\n/queue next\n/queue remove <num>\n/queue clear"
        )


# =========================
# /QUOTE COMMAND
# =========================
async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if GROQ_API_KEY:
        try:
            prompt = (
                "Write one short, punchy, original LinkedIn quote (1-2 sentences max). "
                "It should be thought-provoking and relevant to tech, work, growth, or leadership. "
                "Do NOT use quotation marks. Do NOT add attribution. Only output the quote text."
            )
            q = call_groq(prompt)
            context.user_data["approved_post"] = q
            context.user_data["last_topic"] = "quote"
            await update.message.reply_text(q, reply_markup=make_keyboard())
            return
        except Exception as e:
            print(f"Groq quote error: {e}")
    await update.message.reply_text("The best code is the code you never have to write.")


# =========================
# /RETRY COMMAND
# =========================
async def retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_post = context.user_data.get("approved_post")
    if not last_post:
        records = load_history()
        if records:
            last_post = records[-1]["text"]
    if not last_post:
        await update.message.reply_text("No previous post found.")
        return
    try:
        publish_to_linkedin(last_post)
        last_topic = context.user_data.get("last_topic", "auto")
        save_to_history(last_post, topic=last_topic)
        await update.message.reply_text("✅ Last post republished!")
    except Exception as e:
        await update.message.reply_text(f"❗ Failed: {e}")


# =========================
# /PREVIEW COMMAND
# =========================
async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_post = context.user_data.get("approved_post")
    if not last_post:
        records = load_history()
        if records:
            last_post = records[-1]["text"]
    if not last_post:
        await update.message.reply_text("No post generated yet.")
        return
    await update.message.reply_text(f"Last generated post:\n\n{last_post}", reply_markup=make_keyboard())


# =========================
# /STATS COMMAND
# =========================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = load_history()
    if not records:
        await update.message.reply_text("No posts published yet.")
        return
    total = len(records)
    skip = {"auto", "scheduled", ""}
    topics = [e["topic"] for e in records if e["topic"] not in skip]
    top_topics = Counter(topics).most_common(5)
    now = datetime.now(ZoneInfo("UTC"))
    week_ago = now - timedelta(days=7)
    this_week = []
    for e in records:
        try:
            dt = datetime.strptime(e["date"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=ZoneInfo("UTC"))
            if dt >= week_ago:
                this_week.append(e)
        except:
            pass
    day_counts = Counter()
    for e in this_week:
        try:
            dt = datetime.strptime(e["date"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=ZoneInfo("UTC"))
            day_counts[dt.strftime("%a %d %b")] += 1
        except:
            pass
    lines = [f"Your LinkedIn posting stats:\n", f"Total posts: {total}", f"Posts this week: {len(this_week)}\n"]
    if top_topics:
        lines.append("Top topics:")
        for t, c in top_topics:
            lines.append(f"  {t} — {c} post(s)")
        lines.append("")
    if day_counts:
        lines.append("Activity this week:")
        for day, count in sorted(day_counts.items()):
            lines.append(f"  {day}: {'█' * count} ({count})")
    await update.message.reply_text("\n".join(lines))


# =========================
# /IMAGEPOST COMMAND
# =========================
async def imagepost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_topic = " ".join(args) if args else ""
    await update.message.reply_text(f"🎨 Generating post{' about: ' + user_topic if user_topic else ''}...\nThis takes a few seconds.")
    post_text = generate_post(topic=user_topic)
    context.user_data["approved_post"] = post_text
    context.user_data["last_topic"] = user_topic
    try:
        img_bytes = generate_image_bytes(user_topic or "software testing and QA automation")
        context.user_data["pending_image_bytes"] = img_bytes
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve + Image", callback_data="approve_image")],
            [InlineKeyboardButton("🔄 Rewrite", callback_data="rewrite")],
            [InlineKeyboardButton("✅ Approve (text only)", callback_data="approve")],
        ])
        await update.message.reply_photo(photo=img_bytes, caption=post_text, reply_markup=keyboard)
    except Exception as e:
        context.user_data["pending_image_bytes"] = None
        await update.message.reply_text(f"{post_text}\n\n⚠️ Image generation failed ({e}).", reply_markup=make_keyboard())


# =========================
# /HISTORY COMMAND
# =========================
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = load_history()
    if not records:
        await update.message.reply_text("No posts published yet.")
        return
    recent = records[-5:][::-1]
    lines = [f"Last {len(recent)} published posts:\n"]
    for i, entry in enumerate(recent, 1):
        preview_text = entry["text"][:80].replace("\n", " ")
        lines.append(f"{i}. [{entry['date']}] ({entry['topic']})\n   {preview_text}...")
    await update.message.reply_text("\n".join(lines))


# =========================
# /SCHEDULE COMMAND
# =========================
async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /schedule HH:MM (UTC)")
        return
    try:
        hour, minute = map(int, context.args[0].split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid format. Use HH:MM")
        return
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name("auto_post")
    for job in jobs:
        job.schedule_removal()
    context.job_queue.run_daily(auto_post_job, time=time(hour=hour, minute=minute, tzinfo=ZoneInfo("UTC")), name="auto_post", data={"chat_id": chat_id})
    save_schedule(hour, minute, chat_id)
    await update.message.reply_text(f"✅ Scheduled daily at {hour:02d}:{minute:02d} UTC.")


# =========================
# /UNSCHEDULE COMMAND
# =========================
async def unschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = context.job_queue.get_jobs_by_name("auto_post")
    if not jobs:
        await update.message.reply_text("No active schedule.")
        return
    for job in jobs:
        job.schedule_removal()
    delete_schedule()
    await update.message.reply_text("✅ Schedule cancelled.")


# =========================
# /STATUS COMMAND
# =========================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saved = load_schedule()
    jobs = context.job_queue.get_jobs_by_name("auto_post")
    history_count = len(load_history())
    if jobs and saved:
        h, m = saved["hour"], saved["minute"]
        await update.message.reply_text(f"Auto-post: active daily at {h:02d}:{m:02d} UTC\nTotal posts: {history_count}")
    else:
        await update.message.reply_text(f"Auto-post: not active\nTotal posts: {history_count}")


# =========================
# TRENDING TOPIC FINDER
# =========================
def fetch_trending_topics(limit: int = 5) -> list:
    topics = []
    try:
        entries = parse_rss("https://github.com/trending/python?rss")
        for entry in entries[:3]:
            title = entry.get("title", "")
            repo_match = re.search(r"repository: (.+)", title)
            if repo_match:
                topics.append(f"GitHub trending: {repo_match.group(1)}")
            else:
                topics.append(title[:80])
    except:
        pass
    try:
        entries = parse_rss("https://dev.to/feed/tag/qa")
        for entry in entries[:3]:
            title = entry.get("title", "")
            topics.append(f"Dev.to article: {title[:70]}")
    except:
        pass
    seen = set()
    unique = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:limit]

async def trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching trending topics...")
    topics = fetch_trending_topics(5)
    if not topics:
        await update.message.reply_text("Couldn't fetch trends. Try /topic <your idea>")
        return
    context.user_data["trending_topics"] = topics
    msg = "*📈 Trending Topics Today:*\n\n"
    for i, t in enumerate(topics, 1):
        msg += f"{i}. {t}\n"
    msg += f"\n_Reply with number (1-{len(topics)}) to generate post._"
    await update.message.reply_text(msg, parse_mode="Markdown")
    context.user_data["awaiting_trend_choice"] = True

async def handle_trend_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_trend_choice"):
        return
    text = update.message.text.strip()
    if not text.isdigit():
        context.user_data["awaiting_trend_choice"] = False
        return
    choice = int(text)
    topics = context.user_data.get("trending_topics", [])
    if 1 <= choice <= len(topics):
        selected = topics[choice-1]
        context.user_data["awaiting_trend_choice"] = False
        await update.message.reply_text(f"✍️ Generating post on: *{selected}*...", parse_mode="Markdown")
        ai_post = generate_post(topic=selected)
        context.user_data["approved_post"] = ai_post
        context.user_data["last_topic"] = selected
        await update.message.reply_text(ai_post, reply_markup=make_keyboard())
    else:
        await update.message.reply_text(f"Invalid choice. Pick 1-{len(topics)}")


# =========================
# /INSPIRE COMMAND
# =========================
async def inspire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Finding wisdom...")
    fallback = [
        "“It's not a bug, it's an undocumented feature.” – Anonymous\n\nIn testing, our job is to find those features before customers do. 😄 #QA #TestingHumor",
        "“Quality is never an accident; it is always the result of intelligent effort.” – John Ruskin\n\nEvery bug we catch is proof of that effort. #QualityFirst",
        "“The best time to plant a tree was 20 years ago. The second best time is now.” – Chinese Proverb\n\nStart automating those flaky tests today. #TestAutomation",
    ]
    if not GROQ_API_KEY:
        import random
        post_text = random.choice(fallback)
        context.user_data["approved_post"] = post_text
        context.user_data["last_topic"] = "inspire"
        await update.message.reply_text(post_text, reply_markup=make_keyboard())
        return
    try:
        prompt = (
            "You are an expert software testing coach. Generate an inspirational LinkedIn post with this structure:\n"
            "1. A real quote from a famous software testing/QA leader (e.g., James Bach, Michael Bolton). Write the quote inside double quotes, followed by the author's name.\n"
            "2. Write a short, punchy commentary (2-3 sentences) explaining why this quote matters for modern QA/automation engineers.\n"
            "3. End with 2 relevant hashtags (e.g., #QAInspiration #TestingWisdom).\n"
            "Keep total length under 220 words. No markdown."
        )
        quote_post = call_groq(prompt)
        context.user_data["approved_post"] = quote_post
        context.user_data["last_topic"] = "inspire"
        await update.message.reply_text(quote_post, reply_markup=make_keyboard())
    except Exception as e:
        import random
        post_text = random.choice(fallback) + "\n\n(Note: AI unavailable, using manual quote.)"
        context.user_data["approved_post"] = post_text
        context.user_data["last_topic"] = "inspire"
        await update.message.reply_text(post_text, reply_markup=make_keyboard())


# =========================
# /NEWS COMMAND (tech news -> post)
# =========================
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📰 Fetching latest tech news...")
    feeds = {
        "TechCrunch": "https://techcrunch.com/feed/",
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "Wired": "https://www.wired.com/feed/rss",
        "Ars Technica": "https://arstechnica.com/feed/",
        "Hacker News": "https://news.ycombinator.com/rss",
    }
    articles = []
    for source, url in feeds.items():
        try:
            entries = parse_rss(url)
            if entries:
                entry = entries[0]
                articles.append(f"**{source}**: {entry['title']}\n{entry['link']}")
        except:
            continue
    if not articles:
        await update.message.reply_text("❌ Couldn't fetch news.")
        return
    news_text = "Latest Tech News today:\n\n" + "\n\n".join(articles)
    if not GROQ_API_KEY:
        await update.message.reply_text(news_text)
        return
    prompt = (
        "You are a professional LinkedIn content writer. Based on the following tech news headlines, write a single engaging LinkedIn post. "
        "Pick the most interesting story to create a hook.\n\n"
        "The post should have:\n1. A catchy hook\n2. 1-2 lines of insight\n3. A 'My Take' section\n4. End with 3 hashtags\n"
        f"Keep it under 200 words. No markdown.\n\nNews:\n{news_text}"
    )
    try:
        ai_post = call_groq(prompt)
        context.user_data["approved_post"] = ai_post
        context.user_data["last_topic"] = "Tech News"
        await update.message.reply_text(ai_post, reply_markup=make_keyboard())
    except Exception as e:
        await update.message.reply_text(f"AI failed.\n\n{news_text}\n\nError: {e}")


# =========================
# /TECHNEWS COMMAND (manual alert)
# =========================
async def technews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching latest tech news...")
    fetcher = TechNewsFetcher()
    items = await fetcher.fetch_new_articles()
    if not items:
        await update.message.reply_text("No new tech news found.")
        return
    for item in items:
        await update.message.reply_text(item["msg"], parse_mode="Markdown", disable_web_page_preview=True)
        await asyncio.sleep(1)


# =========================
# BUTTONS CALLBACK
# =========================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "rewrite":
        last_topic = context.user_data.get("last_topic", "")
        last_tone = context.user_data.get("last_tone", "")
        last_length = context.user_data.get("last_length", "")
        new_post = generate_post(topic=last_topic, tone=last_tone, length=last_length)
        context.user_data["approved_post"] = new_post
        await query.message.reply_text(new_post, reply_markup=make_keyboard())
    elif query.data == "approve":
        final_post = context.user_data.get("approved_post")
        last_topic = context.user_data.get("last_topic", "")
        try:
            publish_to_linkedin(final_post)
            save_to_history(final_post, topic=last_topic or "auto")
            await query.message.reply_text("✅ Published to LinkedIn!")
        except Exception as e:
            await query.message.reply_text(f"❗ LinkedIn failed: {e}")
    elif query.data == "approve_image":
        final_post = context.user_data.get("approved_post")
        last_topic = context.user_data.get("last_topic", "")
        img_bytes = context.user_data.get("pending_image_bytes")
        try:
            publish_to_linkedin(final_post, image_bytes=img_bytes)
            save_to_history(final_post, topic=last_topic or "auto")
            await query.message.reply_text("✅ Published with image!")
        except Exception as e:
            await query.message.reply_text(f"❗ Failed: {e}")


# =========================
# POST INIT (scheduler + tech news background)
# =========================
async def post_init(application):
    saved = load_schedule()
    if saved:
        h, m, chat_id = saved["hour"], saved["minute"], saved["chat_id"]
        application.job_queue.run_daily(
            auto_post_job,
            time=time(hour=h, minute=m, tzinfo=ZoneInfo("UTC")),
            name="auto_post",
            data={"chat_id": chat_id},
        )
        print(f"Restored schedule: daily at {h:02d}:{m:02d} UTC for chat {chat_id}")

    # Tech news background fetcher (every 30 min)
    fetcher = TechNewsFetcher()
    NEWS_CHAT_ID = int(os.environ.get("8291705336", "0"))
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        fetcher.check_and_send,
        "interval",
        minutes=30,
        args=[application.bot, NEWS_CHAT_ID],
        id="tech_news_job",
        replace_existing=True
    )
    scheduler.start()
    print("📰 Tech news checker started (every 30 min)")

#fresh deployement commit
# =========================
# BUILD & RUN
# =========================
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("post", post))
app.add_handler(CommandHandler("topic", topic))
app.add_handler(CommandHandler("imagepost", imagepost))
app.add_handler(CommandHandler("quote", quote))
app.add_handler(CommandHandler("retry", retry))
app.add_handler(CommandHandler("queue", queue_command))
app.add_handler(CommandHandler("preview", preview))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("schedule", schedule))
app.add_handler(CommandHandler("unschedule", unschedule))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("trend", trend))
app.add_handler(CommandHandler("inspire", inspire))
app.add_handler(CommandHandler("news", news))
app.add_handler(CommandHandler("technews", technews))
app.add_handler(CallbackQueryHandler(buttons))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trend_choice), group=1)


import threading
def start_flask():
    try:
        from web_dashboard import run_web
        run_web()
    except Exception as e:
        print(f"⚠️ Dashboard error: {e}")

flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()
print("🌐 Web dashboard starting at http://localhost:5000")
print("Bot running...")
app.run_polling()