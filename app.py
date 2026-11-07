import os
import re
import time
import random
import threading
import requests
import feedparser
import openai
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, render_template_string, Response

app = Flask(__name__)

# --- CONFIGURATION & CREDENTIALS ---
ADMIN_API_KEY = "hf_secret_key_98234729"
INDEXNOW_KEY = "hf_indexnow_key_778899"

HIREDFAST_DOMAIN = "hiredfast.online"
HIREDFAST_BASE_URL = f"https://{HIREDFAST_DOMAIN}"

JAPAAN_DOMAIN = "japaan.net"
JAPAAN_BASE_URL = f"https://{JAPAAN_DOMAIN}"

GOOGLE_SERVICE_ACCOUNT_KEY_PATH = "google_credentials.json"
openai.api_key = os.environ.get("OPENAI_API_KEY")

# In-memory stores
jobs_db = []      # Stores hiredfast.online JobPosting entries
japaan_db = []    # Stores japaan.net NewsArticle entries

JOB_LOCATIONS = ["Remote", "New York, NY", "Austin, TX", "London, UK", "San Francisco, CA"]
SALARY_RANGES = ["$90,000 - $120,000", "$130,000 - $160,000", "$170,000 - $210,000"]

# Multi-topic RSS feeds mapped to specific categories for japaan.net
RSS_FEEDS = [
    {"url": "https://news.yahoo.co.jp/rss/topics/it.xml", "category": "Tech"},
    {"url": "https://news.yahoo.co.jp/rss/topics/business.xml", "category": "Business"},
    {"url": "https://news.yahoo.co.jp/rss/topics/sports.xml", "category": "Sports"},
    {"url": "https://news.yahoo.co.jp/rss/topics/world.xml", "category": "World"},
    {"url": "https://techcrunch.com/feed/", "category": "Tech"}
]

EMULATED_FETCHERS = [
    "Mozilla/5.0 (compatible; Google-InspectionTool/1.0; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Chrome-Lighthouse",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Twitterbot/1.0"
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

def fetch_and_publish_rss_articles():
    """Ingests RSS feeds, translates/spins items via OpenAI into unique Japanese articles, and auto-publishes."""
    global japaan_db
    
    for feed_info in RSS_FEEDS:
        try:
            parsed_feed = feedparser.parse(feed_info["url"])
            category = feed_info["category"]
            
            for entry in parsed_feed.entries[:2]:
                original_title = entry.get('title', '')
                original_summary = entry.get('summary', entry.get('description', ''))
                target_url = entry.get('link', JAPAAN_BASE_URL)
                
                # Prevent duplicate ingestion
                if any(article.get('source_rss_link') == target_url for article in japaan_db):
                    continue

                prompt = f"""
                Translate and rewrite the following {category} news story into a professional, unique 3-paragraph Japanese news report.
                Category: {category}
                Title: {original_title}
                Summary: {original_summary}
                
                Format requirement:
                Line 1: Japanese Headline starting with 【{category}速報】
                Line 2 onwards: Body text in Japanese.
                """
                
                response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                
                content = response.choices[0].message.content.strip()
                parts = content.split("\n", 1)
                title_jp = parts[0].replace("#", "").strip()
                body_jp = parts[1].strip() if len(parts) > 1 else "最新のニュース・技術動向に関する詳細リポートです。"
                
                timestamp = int(time.time())
                jp_slug = f"{category.lower()}-" + re.sub(r'[^a-z0-9]+', '-', original_title.lower()).strip('-')[:25] + f"-{timestamp}"
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
                
                # Dispatch background broadcast pings for the new article
                threading.Thread(target=run_full_broadcast_pipeline, args=(None, japaan_url)).start()
                
        except Exception as e:
            print(f"Error parsing feed {feed_info['url']}: {e}")

def clean_expired_jobs():
    global jobs_db, japaan_db
    seven_days_ago = time.time() - (7 * 86400)
    jobs_db = [j for j in jobs_db if j['created_at'] > seven_days_ago]
    japaan_db = [a for a in japaan_db if a['created_at'] > seven_days_ago]

def get_google_access_token():
    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_KEY_PATH):
        return None
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        scopes = ["https://www.googleapis.com/auth/indexing"]
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_KEY_PATH, scopes=scopes
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        return creds.token
    except Exception:
        return None

# --- BACKGROUND BROADCAST ENGINE ---
def run_full_broadcast_pipeline(job_url=None, japaan_url=None):
    # Tier 1: Google Indexing API
    token = get_google_access_token()
    if token and job_url:
        try:
            requests.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"url": job_url, "type": "URL_UPDATED"},
                timeout=3
            )
        except Exception: pass

    # Tier 2: Bing / IndexNow
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

    # Tier 3: WebSub
    try:
        requests.post("https://pubsubhubbub.appspot.com/", data={
            "hub.mode": "publish",
            "hub.url": f"{HIREDFAST_BASE_URL}/feed.xml"
        }, timeout=3)
    except Exception: pass

    # Tier 4: Sitemap & XML-RPC Pings
    try:
        if job_url:
            sitemap_url = f"{HIREDFAST_BASE_URL}/sitemap.xml"
            requests.get(f"https://www.google.com/ping?sitemap={sitemap_url}", timeout=3)
            requests.get(f"https://www.bing.com/ping?sitemap={sitemap_url}", timeout=3)

        if japaan_url:
            japaan_sitemap = f"{JAPAAN_BASE_URL}/news-sitemap.xml"
            requests.get(f"https://www.google.com/ping?sitemap={japaan_sitemap}", timeout=3)

        ping_xml = f"""<?xml version="1.0"?>
        <methodCall>
            <methodName>weblogUpdates.ping</methodName>
            <params>
                <param><value><string>HiredFast Careers</string></value></param>
                <param><value><string>{HIREDFAST_BASE_URL}</string></value></param>
            </params>
        </methodCall>"""
        requests.post("https://rpc.pingomatic.com/", data=ping_xml, headers={"Content-Type": "text/xml"}, timeout=3)
    except Exception: pass

    # Tier 5: Wayback Machine Snapshot
    if job_url:
        try:
            requests.get(f"https://web.archive.org/save/{job_url}", headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        except Exception: pass

    # Tier 6 & 7: Emulated Fetchers
    for ua in EMULATED_FETCHERS:
        try:
            if job_url: requests.get(job_url, headers={"User-Agent": ua}, timeout=3)
            if japaan_url: requests.get(japaan_url, headers={"User-Agent": ua}, timeout=3)
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
            <title>Japaan Tech News & Media Network</title>
        </head>
        <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6;">
            <nav style="margin-bottom: 20px; background: #f0f0f0; padding: 10px; border-radius: 4px;">
                <a href="/" style="margin-right: 15px; font-weight: bold;">Top</a>
                <a href="/category/tech" style="margin-right: 15px;">Tech</a>
                <a href="/category/business" style="margin-right: 15px;">Business</a>
                <a href="/category/sports" style="margin-right: 15px;">Sports</a>
                <a href="/category/world">World</a>
            </nav>
            <h1>最新テクノロジー・ニュース速報</h1>
            <p>Japaan 編集部による自動収集・翻訳ニュースフィード:</p>
            <hr>
            <ul>
                {% for article in articles %}
                <li style="margin-bottom: 12px;">
                    <span style="background: #0066cc; color: #fff; padding: 2px 6px; font-size: 11px; border-radius: 3px; margin-right: 6px;">{{ article.category }}</span>
                    <a href="/news/{{ article.slug }}"><strong>{{ article.title_jp }}</strong></a>
                </li>
                {% endfor %}
            </ul>
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
        <title>HiredFast Engineering & Tech Jobs Hub</title>
    </head>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6;">
        <h1>Latest Technical Roles & Application Portals</h1>
        <p>Active positions updated in real-time. Select a job entry to view direct specifications:</p>
        <hr>
        <ul>
            {% for job in jobs %}
            <li style="margin-bottom: 12px;">
                <a href="/jobs/{{ job.slug }}"><strong>{{ job.title }}</strong></a> 
                &mdash; {{ job.location }} ({{ job.salary }})
            </li>
            {% endfor %}
        </ul>
    </body>
    </html>
    """
    return render_template_string(html, jobs=jobs_db[:50])

# CATEGORY FILTER ROUTE FOR JAPAAN.NET
@app.route('/category/<cat_name>')
def japaan_category_page(cat_name):
    clean_expired_jobs()
    filtered = [a for a in japaan_db if a.get('category', '').lower() == cat_name.lower()]
    
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>{{ cat_name | capitalize }} News - Japaan Network</title>
    </head>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6;">
        <nav style="margin-bottom: 20px; background: #f0f0f0; padding: 10px; border-radius: 4px;">
            <a href="/" style="margin-right: 15px;">Top</a>
            <a href="/category/tech" style="margin-right: 15px;">Tech</a>
            <a href="/category/business" style="margin-right: 15px;">Business</a>
            <a href="/category/sports" style="margin-right: 15px;">Sports</a>
            <a href="/category/world">World</a>
        </nav>
        <h1>{{ cat_name | capitalize }} ニュース一覧</h1>
        <hr>
        <ul>
            {% for article in articles %}
            <li style="margin-bottom: 12px;">
                <a href="/news/{{ article.slug }}"><strong>{{ article.title_jp }}</strong></a>
            </li>
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
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "JobPosting",
          "title": "{{ job.title }}",
          "description": "Full specifications and documentation hosted on the primary verification platform.",
          "datePosted": "2026-03-01",
          "validThrough": "2026-12-31",
          "employmentType": "FULL_TIME",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "HiredFast Global",
            "sameAs": "{{ job.target_url }}"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "{{ job.location }}"
            }
          }
        }
        </script>
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
    return render_template_string(html, job=job, base_url=HIREDFAST_BASE_URL)

# JAPAAN.NET NEWS ARTICLE PAGE (With NewsArticle Schema & articleSection)
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
        <title>{{ article.title_jp }} - Japaan Tech</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "NewsArticle",
          "headline": "{{ article.title_jp }}",
          "articleSection": "{{ article.category }}",
          "datePublished": "2026-03-01T08:00:00+09:00",
          "author": {
            "@type": "Organization",
            "name": "Japaan News Editorial"
          }
        }
        </script>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; line-height: 1.8;">
        <p><a href="/" style="color: #666; text-decoration: none;">&larr; トップページに戻る</a> | <span style="background: #eee; padding: 2px 6px; border-radius: 3px;">{{ article.category }}</span></p>
        <h2>{{ article.title_jp }}</h2>
        <hr>
        <p>{{ article.body_jp }}</p>
        <div style="background: #f9f9f9; padding: 15px; border-left: 4px solid #ff4500; margin-top: 30px;">
            <p style="margin-top:0; font-weight: bold;">参照・検証元ソース:</p>
            <a href="{{ article.target_url }}" target="_blank" rel="noopener follow" style="color: #0044cc; font-weight: bold;">
                {{ article.target_url }}
            </a>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, article=article)

# SITEMAPS
@app.route('/sitemap.xml')
def sitemap():
    clean_expired_jobs()
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    url_elm = ET.SubElement(urlset, "url")
    ET.SubElement(url_elm, "loc").text = HIREDFAST_BASE_URL
    for job in jobs_db:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = f"{HIREDFAST_BASE_URL}/jobs/{job['slug']}"
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding='utf-8', method='xml'), mimetype='text/xml')

@app.route('/news-sitemap.xml')
def news_sitemap():
    clean_expired_jobs()
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for article in japaan_db:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = f"{JAPAAN_BASE_URL}/news/{article['slug']}"
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding='utf-8', method='xml'), mimetype='text/xml')

# CRON ENDPOINT FOR AUTOMATED RSS FETCHING
@app.route('/api/cron-fetch-rss', methods=['GET', 'POST'])
def cron_fetch_rss():
    provided_key = request.headers.get("X-API-KEY") or request.args.get("key")
    if provided_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    fetch_and_publish_rss_articles()
    return jsonify({
        "status": "success",
        "message": "RSS feeds ingested, translated, spun, and auto-published to japaan.net!",
        "total_articles": len(japaan_db)
    }), 200

# UNIFIED BROADCAST ENDPOINT (HiredFast Target Submission)
@app.route('/api/broadcast', methods=['POST'])
def api_broadcast():
    clean_expired_jobs()
    
    provided_key = request.headers.get("X-API-KEY") or request.args.get("key")
    if provided_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

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

    threading.Thread(target=run_full_broadcast_pipeline, args=(job_url, None)).start()

    return jsonify({
        "status": "success",
        "hiredfast_url": job_url,
        "target_url": target_url,
        "message": "Target published to hiredfast.online and indexing broadcast pipeline dispatched!"
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)