import os
import re
import time
import random
import threading
import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, render_template_string, Response

app = Flask(__name__)

# --- CONFIGURATION & CREDENTIALS ---
ADMIN_API_KEY = "hf_secret_key_98234729"
INDEXNOW_KEY = "hf_indexnow_key_778899"
DOMAIN = "hiredfast.online"
BASE_URL = f"https://{DOMAIN}"
GOOGLE_SERVICE_ACCOUNT_KEY_PATH = "google_credentials.json"

# In-memory store (Retains posts for active crawl rotation)
jobs_db = []

JOB_LOCATIONS = ["Remote", "New York, NY", "Austin, TX", "London, UK", "San Francisco, CA"]
SALARY_RANGES = ["$90,000 - $120,000", "$130,000 - $160,000", "$170,000 - $210,000"]

# User-Agent list for Tier 7 (Emulated User-Triggered Crawlers)
EMULATED_FETCHERS = [
    "Mozilla/5.0 (compatible; Google-InspectionTool/1.0; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Chrome-Lighthouse",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Twitterbot/1.0"
]

# --- HELPER FUNCTIONS ---
def generate_synthetic_job_title(target_url):
    """Generates a clean synthetic job title based on target domain to pass schema validation."""
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

def clean_expired_jobs():
    """Removes posts older than 7 days to maintain dynamic link budget."""
    global jobs_db
    seven_days_ago = time.time() - (7 * 86400)
    jobs_db = [j for j in jobs_db if j['created_at'] > seven_days_ago]

def get_google_access_token():
    """Fetches OAuth2 token for Google Indexing API."""
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

# --- BACKGROUND BROADCAST ENGINE (TIERS 1-7) ---
def run_full_broadcast_pipeline(job_url):
    """Executes the full 7-tier asynchronous discovery pipeline."""
    
    # Tier 1: Google Indexing API (Official Direct Push)
    token = get_google_access_token()
    if token:
        try:
            requests.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"url": job_url, "type": "URL_UPDATED"},
                timeout=3
            )
        except Exception: pass

    # Tier 2: Bing / IndexNow
    try:
        requests.post("https://api.indexnow.org/indexnow", json={
            "host": DOMAIN,
            "key": INDEXNOW_KEY,
            "keyLocation": f"{BASE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": [job_url]
        }, timeout=3)
    except Exception: pass

    # Tier 3: WebSub (PubSubHubbub)
    try:
        requests.post("https://pubsubhubbub.appspot.com/", data={
            "hub.mode": "publish",
            "hub.url": f"{BASE_URL}/feed.xml"
        }, timeout=3)
    except Exception: pass

    # Tier 4: Sitemap & XML-RPC Pings
    try:
        sitemap_url = f"{BASE_URL}/sitemap.xml"
        google_ping = f"https://www.google.com/ping?sitemap={sitemap_url}"
        bing_ping = f"https://www.bing.com/ping?sitemap={sitemap_url}"
        
        requests.get(google_ping, timeout=3)
        requests.get(bing_ping, timeout=3)

        ping_xml = f"""<?xml version="1.0"?>
        <methodCall>
            <methodName>weblogUpdates.ping</methodName>
            <params>
                <param><value><string>HiredFast Careers</string></value></param>
                <param><value><string>{BASE_URL}</string></value></param>
            </params>
        </methodCall>"""
        requests.post("https://rpc.pingomatic.com/", data=ping_xml, headers={"Content-Type": "text/xml"}, timeout=3)
    except Exception: pass

    # Tier 5: Wayback Machine Snapshot
    try:
        requests.get(f"https://web.archive.org/save/{job_url}", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }, timeout=4)
    except Exception: pass

    # Tier 6 & 7: Emulated User-Triggered Crawlers & Diagnostic Fetchers
    for ua in EMULATED_FETCHERS:
        try:
            requests.get(job_url, headers={"User-Agent": ua}, timeout=3)
        except Exception: pass


# --- ROUTES & VIEWS ---

# IndexNow Key Verification Endpoint
@app.route(f'/{INDEXNOW_KEY}.txt')
def indexnow_key():
    return Response(INDEXNOW_KEY, mimetype='text/plain')

# 1. HOMEPAGE HUB (Passes PageRank internally down to recent posts)
@app.route('/')
def homepage():
    clean_expired_jobs()
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

# 2. DEDICATED BRIDGE PAGE (Contains Schema & Direct Outbound Target Link)
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
        <meta name="description" content="View position details for {{ job.title }} located in {{ job.location }}.">
        
        <!-- OpenGraph Meta Tags -->
        <meta property="og:title" content="{{ job.title }}">
        <meta property="og:description" content="View application details and external resources.">
        <meta property="og:url" content="{{ base_url }}/jobs/{{ job.slug }}">
        
        <!-- Google JSON-LD JobPosting Schema -->
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
          },
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "USD",
            "value": {
              "@type": "QuantitativeValue",
              "value": 140000,
              "unitText": "YEAR"
            }
          }
        }
        </script>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; line-height: 1.5;">
        <h2>{{ job.title }}</h2>
        <p><strong>Location:</strong> {{ job.location }} | <strong>Salary:</strong> {{ job.salary }}</p>
        
        <!-- VISIBLE HTML LINK PASSING AUTHORITY TO TARGET URL -->
        <div style="background: #f4f4f4; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #ddd;">
            <p style="margin-top:0;">To access the primary resource documentation directly, follow the link below:</p>
            <a href="{{ job.target_url }}" target="_blank" rel="noopener follow" style="font-weight: bold; color: #0066cc; font-size: 16px;">
                Access Direct Target Resource ({{ job.target_url }})
            </a>
        </div>

        <!-- Embedded iFrame -->
        <iframe src="{{ job.target_url }}" style="width: 100%; height: 600px; border: 1px solid #ccc; border-radius: 4px;"></iframe>
    </body>
    </html>
    """
    return render_template_string(html, job=job, base_url=BASE_URL)

# 3. DYNAMIC SITEMAP
@app.route('/sitemap.xml')
def sitemap():
    clean_expired_jobs()
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    
    url_elm = ET.SubElement(urlset, "url")
    ET.SubElement(url_elm, "loc").text = BASE_URL
    ET.SubElement(url_elm, "changefreq").text = "always"
    
    for job in jobs_db:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = f"{BASE_URL}/jobs/{job['slug']}"
        ET.SubElement(u, "changefreq").text = "hourly"
        
    xml_str = ET.tostring(urlset, encoding='utf-8', method='xml')
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str, mimetype='text/xml')

# 4. DYNAMIC RSS FEED
@app.route('/feed.xml')
def rss_feed():
    clean_expired_jobs()
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "HiredFast Indexing Feed"
    ET.SubElement(channel, "link").text = BASE_URL
    
    for job in jobs_db:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = job['title']
        ET.SubElement(item, "link").text = f"{BASE_URL}/jobs/{job['slug']}"
        ET.SubElement(item, "guid").text = f"{BASE_URL}/jobs/{job['slug']}"
        
    xml_str = ET.tostring(rss, encoding='utf-8', method='xml')
    return Response(b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str, mimetype='text/xml')

# 5. SUBMISSION API ENDPOINT
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

    title = generate_synthetic_job_title(target_url)
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') + f"-{int(time.time())}"
    job_url = f"{BASE_URL}/jobs/{slug}"
    
    new_job = {
        "id": f"job-{int(time.time())}",
        "title": title,
        "target_url": target_url,
        "location": random.choice(JOB_LOCATIONS),
        "salary": random.choice(SALARY_RANGES),
        "slug": slug,
        "created_at": time.time()
    }
    jobs_db.insert(0, new_job)

    # Launch all 7 broadcast tiers asynchronously in a background thread
    threading.Thread(target=run_full_broadcast_pipeline, args=(job_url,)).start()

    return jsonify({
        "status": "success",
        "job_url": job_url,
        "target_url": target_url,
        "message": "Page published, added to Homepage/Sitemap feeds, and full 7-tier broadcast dispatched."
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)