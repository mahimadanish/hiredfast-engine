import os
import re
import time
import json
import random
import threading
import requests
import feedparser
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, render_template_string, Response
from groq import Groq

app = Flask(__name__)

# --- CONFIGURATION & CREDENTIALS ---
ADMIN_API_KEY = "hf_secret_key_98234729"
INDEXNOW_KEY = "hf_indexnow_key_778899"

HIREDFAST_DOMAIN = "hiredfast.online"
HIREDFAST_BASE_URL = f"https://{HIREDFAST_DOMAIN}"

JAPAAN_DOMAIN = "japaan.net"
JAPAAN_BASE_URL = f"https://{JAPAAN_DOMAIN}"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# In-memory stores
jobs_db = []      # Stores hiredfast.online JobPosting entries
japaan_db = []    # Stores japaan.net NewsArticle entries

JOB_LOCATIONS = ["Remote", "New York, NY", "Austin, TX", "London, UK", "San Francisco, CA"]
SALARY_RANGES = ["$90,000 - $120,000", "$130,000 - $160,000", "$170,000 - $210,000"]

# Active RSS feeds with designated categories
RSS_FEEDS = [
    {"url": "https://www.nhk.or.jp/rss/news/cat0.xml", "category": "Tech"},
    {"url": "https://gigazine.net/news/rss_2.0/", "category": "Tech"},
    {"url": "https://www.nhk.or.jp/rss/news/cat6.xml", "category": "Business"},
    {"url": "https://www.nhk.or.jp/rss/news/cat5.xml", "category": "World"}
]

# --- HELPER FUNCTIONS ---
def generate_synthetic_job_title(target_url):
    target = target_url.lower()
    if "spotify" in target:
        return "Audio Systems & Media Streaming Engineer"
    elif "instagram" in target:
        return "Visual Media & Audience Operations Manager"
    elif "synology" in target:
        return "Network Attached Storage & Data Specialist"
    elif "wokwi" in target:
        return "Embedded Systems & Hardware Simulation Developer"
    return "Senior Infrastructure & Cloud Systems Architect"

def call_groq_structured_rewrite(category, original_title, original_summary):
    """Uses Groq JSON mode with the active llama-3.1-8b-instant model."""
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY environment variable is missing.")
    
    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
You are a professional Japanese news journalist. Rewrite and translate the following news item into fluent, natural Japanese news reporting text.

Feed Category Hint: {category}
Original Title: {original_title}
Original Summary: {original_summary[:800]}

Rules:
1. Assign the correct category from [Tech, Business, World, Sports].
2. Create a clean Japanese headline starting with 【Category速報】 (e.g. 【Tech速報】...).
3. Write exactly 3 paragraphs of news body text in Japanese.
4. Return ONLY a valid JSON object with no markdown wrapping, no extra text, and no conversational filler.

JSON structure required:
{{
  "category": "Tech",
  "title": "【Tech速報】Japanese headline here",
  "body": "Paragraph 1 text here.\\n\\nParagraph 2 text here.\\n\\nParagraph 3 text here."
}}
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    
    return json.loads(response.choices[0].message.content.strip())

def fetch_and_publish_rss_articles():
    """Ingests RSS feeds, rewrites via Groq, and auto-publishes to japaan.net."""
    global japaan_db
    
    for feed_info in RSS_FEEDS:
        try:
            parsed_feed = feedparser.parse(feed_info["url"])
            default_category = feed_info["category"]
            
            for entry in parsed_feed.entries[:2]:
                original_title = entry.get('title', '')
                original_summary = entry.get('summary', entry.get('description', ''))
                target_url = entry.get('link', JAPAAN_BASE_URL)
                
                # Prevent duplicate ingestion
                if any(article.get('source_rss_link') == target_url for article in japaan_db):
                    continue

                result = call_groq_structured_rewrite(default_category, original_title, original_summary)
                
                category = result.get("category", default_category)
                if category not in ["Tech", "Business", "World", "Sports"]:
                    category = default_category
                    
                title_jp = result.get("title", f"【{category}速報】{original_title}")
                body_jp = result.get("body", original_summary)
                
                timestamp = int(time.time())
                slug_base = re.sub(r'[^a-zA-Z0-9]+', '-', original_title.lower()).strip('-')
                if not slug_base:
                    slug_base = "news-report"
                jp_slug = f"{category.lower()}-{slug_base[:25].strip('-')}-{timestamp}"
                
                japaan_url = f"{JAPAAN_BASE_URL}/news/{jp_slug}"

                japaan_db.insert(0, {
                    "id": f"jp-{timestamp}",
                    "title_jp": title_jp,
                    "body_jp": body_jp,
                    "category": category,
                    "target_url": target_url,
                    "source_rss_link": target_url,
                    "slug": jp_slug,
                    "created_at": time.time()
                })
                
                # Dispatch background broadcasting pings
                threading.Thread(target=run_full_broadcast_pipeline, args=(None, japaan_url)).start()
                
        except Exception as e:
            print(f"Error parsing feed {feed_info['url']}: {e}")

def clean_expired_jobs():
    global jobs_db, japaan_db
    seven_days_ago = time.time() - (7 * 86400)
    jobs_db = [j for j in jobs_db if j['created_at'] > seven_days_ago]
    japaan_db = [a for a in japaan_db if a['created_at'] > seven_days_ago]

def run_full_broadcast_pipeline(job_url=None, japaan_url=None):
    urls_to_index = []
    if job_url: urls_to_index.append(job_url)
    if japaan_url: urls_to_index.append(japaan_url)

    if urls_to_index:
        try:
            requests.post("https://api.indexnow.org/indexnow", json={
                "host": HIREDFAST_DOMAIN,
                "key": INDEXNOW_KEY,
                "keyLocation": f"{HIREDFAST_BASE_URL}/{INDEXNOW_KEY}.txt",
                "urlList": urls_to_index
            }, timeout=3)
        except Exception: pass

    try:
        requests.post("https://pubsubhubbub.appspot.com/", data={
            "hub.mode": "publish",
            "hub.url": f"{HIREDFAST_BASE_URL}/feed.xml"
        }, timeout=3)
    except Exception: pass


# --- ROUTING & DOMAIN DISPATCHING ---

@app.route(f'/{INDEXNOW_KEY}.txt')
def indexnow_key():
    return Response(INDEXNOW_KEY, mimetype='text/plain')

# HOMEPAGE SWITCHER
@app.route('/')
def homepage():
    clean_expired_jobs()
    host = request.headers.get('Host', '').lower()

    if JAPAAN_DOMAIN in host:
        html = """
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>JAPAAN.NET - 最新テクノロジー・ニュース速報</title>
            <style>
                :root { --primary: #0f172a; --accent: #2563eb; --bg: #f8fafc; --card-bg: #ffffff; --text: #334155; --border: #e2e8f0; }
                * { box-sizing: border-box; margin: 0; padding: 0; }
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg); color: var(--text); line-height: 1.7; }
                header { background: var(--card-bg); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
                .nav-container { max-width: 1100px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; flex-wrap: wrap; gap: 10px; }
                .logo { font-size: 24px; font-weight: 800; color: var(--primary); text-decoration: none; }
                .logo span { color: var(--accent); }
                nav a { margin-left: 20px; text-decoration: none; color: var(--text); font-weight: 600; font-size: 15px; }
                nav a:hover, nav a.active { color: var(--accent); }
                .container { max-width: 1100px; margin: 30px auto; padding: 0 20px; }
                .hero { background: linear-gradient(135deg, #1e293b, #0f172a); color: white; padding: 40px; border-radius: 12px; margin-bottom: 35px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1); }
                .hero span.badge { background: var(--accent); color: white; padding: 4px 10px; font-size: 12px; border-radius: 20px; font-weight: 600; text-transform: uppercase; }
                .hero h1 { font-size: 28px; margin-top: 15px; line-height: 1.4; }
                .hero p { margin-top: 10px; color: #94a3b8; font-size: 15px; }
                .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px; }
                .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 24px; transition: transform 0.2s; display: flex; flex-direction: column; justify-content: space-between; }
                .card:hover { transform: translateY(-3px); box-shadow: 0 10px 20px -5px rgba(0,0,0,0.08); }
                .card-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .cat-tag { background: #eff6ff; color: var(--accent); padding: 3px 10px; font-size: 12px; border-radius: 6px; font-weight: 700; }
                .card h3 a { color: var(--primary); text-decoration: none; font-size: 18px; line-height: 1.5; }
                .card h3 a:hover { color: var(--accent); }
                .empty-state { text-align: center; padding: 60px 20px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; }
                footer { text-align: center; padding: 40px 20px; color: #64748b; font-size: 14px; border-top: 1px solid var(--border); margin-top: 60px; background: var(--card-bg); }
            </style>
        </head>
        <body>
            <header>
                <div class="nav-container">
                    <a href="/" class="logo">JAPAAN<span>.NET</span></a>
                    <nav>
                        <a href="/" class="active">トップ</a>
                        <a href="/category/tech">Tech</a>
                        <a href="/category/business">Business</a>
                        <a href="/category/sports">Sports</a>
                        <a href="/category/world">World</a>
                    </nav>
                </div>
            </header>

            <div class="container">
                {% if articles %}
                <div class="hero">
                    <span class="badge">{{ articles[0].category }} 速報</span>
                    <h1><a href="/news/{{ articles[0].slug }}" style="color: white; text-decoration: none;">{{ articles[0].title_jp }}</a></h1>
                    <p>最新のAI自動解析・翻訳によるライブ配信ニュースフィードです。</p>
                </div>

                <h2 style="margin-bottom: 20px; font-size: 22px; color: var(--primary);">最新ニュース一覧</h2>
                <div class="grid">
                    {% for article in articles[1:] %}
                    <div class="card">
                        <div>
                            <div class="card-meta">
                                <span class="cat-tag">{{ article.category }}</span>
                            </div>
                            <h3><a href="/news/{{ article.slug }}">{{ article.title_jp }}</a></h3>
                        </div>
                        <div style="margin-top: 20px; font-size: 13px; color: #64748b;">
                            <span>⏱️ 自動生成フィード</span>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <div class="empty-state">
                    <h3>最新ニュース速報を準備中です</h3>
                    <p>ただいま編集部デスクより次回のライブ配信フィードを同期しています。</p>
                </div>
                {% endif %}
            </div>

            <footer>
                <p>&copy; 2026 Japaan.net News Editorial Network. All rights reserved.</p>
            </footer>
        </body>
        </html>
        """
        return render_template_string(html, articles=japaan_db[:50])
    
    # Default HiredFast Homepage
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HiredFast Engineering & Tech Jobs Hub</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; }
            h1 { color: #111; }
            ul { list-style: none; padding: 0; }
            li { background: #fdfdfd; border: 1px solid #e1e4e8; padding: 15px; margin-bottom: 10px; border-radius: 6px; }
            a { color: #0366d6; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>Latest Technical Roles & Application Portals</h1>
        <ul>
            {% for job in jobs %}
            <li>
                <a href="/jobs/{{ job.slug }}"><strong>{{ job.title }}</strong></a> 
                &mdash; <span style="color: #586069;">{{ job.location }} ({{ job.salary }})</span>
            </li>
            {% endfor %}
        </ul>
    </body>
    </html>
    """
    return render_template_string(html, jobs=jobs_db[:50])

# CATEGORY FILTER ROUTE
@app.route('/category/<cat_name>')
def japaan_category_page(cat_name):
    clean_expired_jobs()
    filtered = [a for a in japaan_db if a.get('category', '').lower() == cat_name.lower()]
    
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>{{ cat_name | capitalize }} ニュース - Japaan Network</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #334155; line-height: 1.7; padding: 20px; max-width: 1100px; margin: 0 auto; }
            a { color: #2563eb; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>{{ cat_name | capitalize }} カテゴリー速報</h1>
        <p><a href="/">&larr; トップに戻る</a></p>
        <hr>
        <ul>
            {% for article in articles %}
            <li><a href="/news/{{ article.slug }}"><strong>{{ article.title_jp }}</strong></a></li>
            {% endfor %}
        </ul>
    </body>
    </html>
    """
    return render_template_string(html, articles=filtered, cat_name=cat_name)

# HIREDFAST JOB PAGE
@app.route('/jobs/<slug>')
def job_page(slug):
    job = next((j for j in jobs_db if j['slug'] == slug), None)
    if not job:
        return "Position Not Found or Expired", 404

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{{ job.title }} - Application Portal</title>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; line-height: 1.5;">
        <h2>{{ job.title }}</h2>
        <p><strong>Location:</strong> {{ job.location }} | <strong>Salary:</strong> {{ job.salary }}</p>
        <div style="background: #f4f4f4; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #ddd;">
            <a href="{{ job.target_url }}" target="_blank" rel="noopener follow" style="font-weight: bold; color: #0066cc; font-size: 16px;">
                Access Direct Target Resource ({{ job.target_url }})
            </a>
        </div>
        <iframe src="{{ job.target_url }}" style="width: 100%; height: 600px; border: 1px solid #ccc; border-radius: 4px;"></iframe>
    </body>
    </html>
    """
    return render_template_string(html, job=job)

# JAPAAN.NET NEWS ARTICLE PAGE
@app.route('/news/<slug>')
def japaan_news_page(slug):
    article = next((a for a in japaan_db if a['slug'] == slug), None)
    if not article:
        return "Article Not Found or Expired", 404

    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ article.title_jp }} - Japaan News</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #334155; line-height: 1.8; max-width: 800px; margin: 40px auto; padding: 20px; }
            .article-container { background: #ffffff; padding: 40px; border-radius: 12px; border: 1px solid #e2e8f0; }
            h1 { font-size: 24px; color: #0f172a; margin-bottom: 20px; }
            .content-body { white-space: pre-line; margin-bottom: 30px; }
            .source-box { background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; }
        </style>
    </head>
    <body>
        <p><a href="/">&larr; トップに戻る</a></p>
        <div class="article-container">
            <span style="background: #eff6ff; color: #2563eb; padding: 3px 10px; font-size: 12px; border-radius: 6px; font-weight: 700;">{{ article.category }}</span>
            <h1 style="margin-top: 15px;">{{ article.title_jp }}</h1>
            <hr style="border: none; border-top: 1px solid #e2e8f0; margin-bottom: 20px;">
            <div class="content-body">{{ article.body_jp }}</div>
            
            <div class="source-box">
                <p style="font-weight: bold; margin-bottom: 5px;">参照・検証元ソース (Original Source):</p>
                <a href="{{ article.target_url }}" target="_blank" rel="noopener follow" style="color: #2563eb; word-break: break-all;">
                    {{ article.target_url }}
                </a>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, article=article)

# SITEMAPS
@app.route('/sitemap.xml')
def sitemap():
    clean_expired_jobs()
    urlset = ET.Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    url_elm = ET.SubElement(urlset, "url")
    ET.SubElement(url_elm, "loc").text = HIREDFAST_BASE_URL
    for job in jobs_db:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = f"{HIREDFAST_BASE_URL}/jobs/{job['slug']}"
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding='utf-8', method='xml'), mimetype='text/xml')

@app.route('/news-sitemap.xml')
def news_sitemap():
    clean_expired_jobs()
    urlset = ET.Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    for article in japaan_db:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = f"{JAPAAN_BASE_URL}/news/{article['slug']}"
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding='utf-8', method='xml'), mimetype='text/xml')

# CRON ENDPOINT
@app.route('/api/cron-fetch-rss', methods=['GET', 'POST'])
def cron_fetch_rss():
    provided_key = request.headers.get("X-API-KEY") or request.args.get("key")
    if provided_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}}, 401

    threading.Thread(target=fetch_and_publish_rss_articles).start()

    return jsonify({
        "status": "success",
        "message": "Groq RSS fetching dispatched in background!"
    }), 200

# UNIFIED BROADCAST ENDPOINT
@app.route('/api/broadcast', methods=['POST'])
def api_broadcast():
    clean_expired_jobs()
    
    provided_key = request.headers.get("X-API-KEY") or request.args.get("key")
    if provided_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}}, 401

    data = request.get_json(silent=True) or request.form
    target_url = data.get('target_url')
    if not target_url:
        return jsonify({"error": "target_url is required"}), 400

    timestamp = int(time.time())
    job_title = generate_synthetic_job_title(target_url)
    job_slug = re.sub(r'[^a-z0-9]+', '-', job_title.lower()).strip('-') + f"-{timestamp}"
    job_url = f"{HIREDFAST_BASE_URL}/jobs/{job_slug}"
    
    jobs_db.insert(0, {
        "id": f"job-{timestamp}",
        "title": job_title,
        "target_url": target_url,
        "location": random.choice(JOB_LOCATIONS),
        "salary": random.choice(SALARY_RANGES),
        "slug": job_slug,
        "created_at": time.time()
    })

    return jsonify({
        "status": "success",
        "hiredfast_url": job_url,
        "target_url": target_url,
        "message": "Target published!"
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)