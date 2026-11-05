import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import unquote
from flask import Flask, render_template_string, render_template, request, Response
from google.oauth2 import service_account
from google.auth.transport.requests import Request

app = Flask(__name__)

# CONFIGURATION
DOMAIN = "hiredfast.online"
SITE_URL = f"https://{DOMAIN}"
KEY_FILE = "indexing_key.json"
INDEXNOW_KEY = "hiredfast_indexnow_secret_key"

# HTML DASHBOARD TEMPLATE
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>HiredFast Automated Control Panel</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #f4f6f9; color: #333; }
        .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        textarea { width: 100%; height: 180px; padding: 12px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 14px; margin-bottom: 20px; box-sizing: border-box; }
        button { background: #007bff; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .logs { background: #1e1e1e; color: #00ff66; padding: 15px; border-radius: 4px; font-family: monospace; margin-top: 20px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
        h1 { color: #111; margin-top: 0; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🚀 HiredFast Indexing Control Panel</h1>
        <p>Paste your third-party target URLs below (one per line). Submitting will instantly update your hub, inject schemas, and fire all indexing APIs automatically.</p>
        
        <form method="POST" action="/broadcast">
            <textarea name="urls" placeholder="https://example.com/target-url-1\nhttps://example.com/target-url-2"></textarea><br>
            <button type="submit">Broadcast & Trigger Indexing</button>
        </form>

        {% if logs %}
            <div class="logs"><strong>Execution Log:</strong>\n{{ logs }}</div>
        {% endif %}
    </div>
</body>
</html>
"""

def generate_job_schema(title, description, target_url):
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "datePosted": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "HiredFast Global Network",
            "sameAs": SITE_URL
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Remote",
                "addressCountry": "US"
            }
        },
        "directApply": True,
        "url": target_url
    }
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'

def build_bridge_assets(target_urls):
    html_items = ""
    for idx, url in enumerate(target_urls, 1):
        title = f"Verified Career Opportunity #{idx} – Direct Gateway"
        desc = f"Access verified details and direct tracking resources for listing: {url}"
        schema_json = generate_job_schema(title, desc, url)
        
        html_items += f"""
        <article style="border: 1px solid #ccc; padding: 15px; margin-bottom: 15px; border-radius: 5px;">
            {schema_json}
            <h2>{title}</h2>
            <p>{desc}</p>
            <p><a href="{url}" target="_blank" rel="noopener">Access Listing Direct</a></p>
        </article>
        """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>HiredFast Verification Feed</title></head>
<body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px;">
    <h1>HiredFast Network - Dynamic Crawl Hub</h1>
    <p>Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    <hr style="margin-bottom: 20px;">
    {html_items}
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(full_html)

    # Generate RSS Feed
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "HiredFast Indexing Signal Feed"
    ET.SubElement(channel, "link").text = SITE_URL
    
    for idx, url in enumerate(target_urls, 1):
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"Verified Gateway #{idx}"
        ET.SubElement(item, "link").text = url

    ET.ElementTree(rss).write("feed.xml", encoding="utf-8", xml_declaration=True)

def trigger_google_indexing(hub_url):
    if not os.path.exists(KEY_FILE):
        return "[-] Error: indexing_key.json missing!"
    try:
        scopes = ["https://www.googleapis.com/auth/indexing"]
        credentials = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=scopes)
        credentials.refresh(Request())
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {credentials.token}"}
        payload = {"url": hub_url, "type": "URL_UPDATED"}
        res = requests.post("https://indexing.googleapis.com/v3/urlNotifications:publish", headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            return f"[+] Google Indexing API Success: {hub_url}"
        return f"[-] Google API Error: {res.text}"
    except Exception as e:
        return f"[-] Google Exception: {e}"

def trigger_indexnow(urls):
    try:
        payload = {
            "host": DOMAIN,
            "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": urls
        }
        res = requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=10)
        return f"[+] IndexNow Response Code: {res.status_code}"
    except Exception as e:
        return f"[-] IndexNow Exception: {e}"

@app.route("/")
def index():
    return render_template_string(HTML_UI, logs="")

@app.route("/broadcast", methods=["POST"])
def broadcast():
    raw_text = request.form.get("urls", "")
    target_urls = [line.strip() for line in raw_text.splitlines() if line.strip()]
    
    if not target_urls:
        return render_template_string(HTML_UI, logs="[-] No URLs provided.")

    log_output = f"[+] Processing {len(target_urls)} target URLs...\n"
    
    # 1. Build local files
    build_bridge_assets(target_urls)
    log_output += "[+] Generated local index.html & feed.xml with Job Schemas.\n"
    
    # 2. Trigger Google Indexing API
    hub_url = f"{SITE_URL}/index.html"
    log_output += trigger_google_indexing(hub_url) + "\n"
    
    # 3. Trigger IndexNow
    bridge_urls = [hub_url, f"{SITE_URL}/feed.xml"] + target_urls
    log_output += trigger_indexnow(bridge_urls) + "\n"
    
    log_output += "\n[✔] Pipeline complete! Re-upload index.html and feed.xml to Cloudflare Pages."

    return render_template_string(HTML_UI, logs=log_output)

# --- NEW ADDITIONS FOR THE DYNAMIC ENGINE ---

@app.route('/gateway/<path:target_slug>')
def dynamic_gateway(target_slug):
    """
    Dynamically renders a bridge page using templates/bridge.html on the fly.
    Example: http://127.0.0.1:5000/gateway/telegra.ph/Your-Sample-Target-Link-123
    """
    target_url = unquote(target_slug)
    
    if not target_url.startswith('http://') and not target_url.startswith('https://'):
        target_url = 'https://' + target_url

    return render_template('bridge.html', target_url=target_url)

if __name__ == "__main__":
    app.run(debug=True, port=5000)