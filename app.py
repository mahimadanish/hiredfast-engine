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
        requests.get(f"https://www.google.com/ping?sitemap={sitemap_url}", timeout=