from flask import Flask, render_template_string, request, jsonify, abort
from bs4 import BeautifulSoup
import json, re, time, random, requests

app = Flask(__name__)

EXPIRY_SECONDS = 3 * 3600  # 3 Hours TTL
ADMIN_API_KEY = "hf_secret_key_98234729"

jobs_db = []

JOB_PREFIXES = ["Senior", "Lead", "Associate", "Principal", "Remote", "Global"]
JOB_ROLES = [
    "Operations Specialist", "Digital Marketing Specialist", "Systems Analyst",
    "Customer Success Manager", "Technical Project Coordinator", "Data Analyst",
    "Content Strategist", "Business Development Executive", "Software Engineer"
]
JOB_LOCATIONS = ["Remote", "Hybrid - New York", "Remote - US", "Hybrid - London", "Remote - Canada"]
SALARY_RANGES = ["$55,000 - $70,000 / year", "$65,000 - $85,000 / year", "$80,000 - $105,000 / year"]

def clean_expired_jobs():
    current_time = time.time()
    global jobs_db
    jobs_db = [j for j in jobs_db if (current_time - j['created_at']) < EXPIRY_SECONDS]

def generate_synthetic_job_title(url):
    slug_part = url.rstrip('/').split('/')[-1]
    clean_words = re.sub(r'[^a-zA-Z0-9]+', ' ', slug_part).title().strip()
    if len(clean_words) > 3 and not clean_words.isnumeric():
        prefix = random.choice(["Hiring:", "Urgent Opening:", "Remote Role:"])
        return f"{prefix} {clean_words} Specialist"
    return f"{random.choice(JOB_PREFIXES)} {random.choice(JOB_ROLES)}"

def fetch_or_generate_title(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=4, allow_redirects=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                return og_title["content"].strip()
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
                if len(title) > 5:
                    return title
    except Exception:
        pass
    return generate_synthetic_job_title(url)

HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>HiredFast - Active Career Opportunities</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 2rem; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: white; padding: 1.5rem; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #e2e8f0; }
        .badge { background: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 4px; font-size: 0.85rem; font-weight: 600; }
        a.btn { display: inline-block; background: #2563eb; color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Latest Open Positions</h1>
        {% if jobs %}
            {% for job in jobs %}
            <div class="card">
                <span class="badge">{{ job.location }}</span>
                <h2>{{ job.title }}</h2>
                <p><strong>Compensation:</strong> {{ job.salary }}</p>
                <a class="btn" href="{{ job.target_url }}" target="_blank">View Listing & Apply &rarr;</a>
            </div>
            {% endfor %}
        {% else %}
            <p>No active openings at this moment.</p>
        {% endif %}
    </div>
</body>
</html>
"""

JOB_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ job.title }} - HiredFast Careers</title>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "JobPosting",
      "title": "{{ job.title }}",
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
        "value": "{{ job.salary }}"
      }
    }
    </script>
</head>
<body>
    <h1>{{ job.title }}</h1>
    <p>Location: {{ job.location }}</p>
    <p>Compensation: {{ job.salary }}</p>
    <a href="{{ job.target_url }}">Apply on Partner Site</a>
</body>
</html>
"""

@app.route('/')
def home():
    clean_expired_jobs()
    return render_template_string(HOME_TEMPLATE, jobs=jobs_db)

@app.route('/robots.txt')
def robots():
    content = "User-agent: *\nAllow: /\nSitemap: https://hiredfast.online/feed.xml"
    return content, 200, {'Content-Type': 'text/plain'}

@app.route('/api/broadcast', methods=['POST'])
def api_broadcast():
    clean_expired_jobs()
    
    provided_key = request.headers.get("X-API-KEY") or request.args.get("key")
    if provided_key != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    target_url = data.get('target_url')
    if not target_url:
        return jsonify({"error": "target_url required"}), 400

    title = data.get('title') or fetch_or_generate_title(target_url)
    location = data.get('location') or random.choice(JOB_LOCATIONS)
    salary = data.get('salary') or random.choice(SALARY_RANGES)
    
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') + f"-{int(time.time())}"
    
    new_job = {
        "id": f"job-{int(time.time())}",
        "title": title,
        "target_url": target_url,
        "location": location,
        "salary": salary,
        "slug": slug,
        "created_at": time.time()
    }
    jobs_db.insert(0, new_job)

    # Trigger background WebSub / PubSubHubbub notification ping to Google
    try:
        requests.post("https://pubsubhubbub.appspot.com/", data={
            "hub.mode": "publish",
            "hub.url": "https://hiredfast.online/feed.xml"
        }, timeout=2)
    except Exception:
        pass

    return jsonify({
        "status": "success",
        "generated_title": title,
        "job_url": f"https://hiredfast.online/jobs/{slug}",
        "target_url": target_url
    }), 200

@app.route('/jobs/<slug>')
def job_page(slug):
    clean_expired_jobs()
    job = next((j for j in jobs_db if j['slug'] == slug), None)
    if not job:
        abort(410)
    return render_template_string(JOB_PAGE_TEMPLATE, job=job)

@app.route('/feed.xml')
def rss_feed():
    clean_expired_jobs()
    items_xml = ""
    for j in jobs_db:
        items_xml += f"""
        <item>
            <title>{j['title']}</title>
            <link>{j['target_url']}</link>
        </item>"""
    
    # RSS Feed with WebSub link header included for instant Google indexing alerts
    rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>HiredFast Career Feed</title>
            <link>https://hiredfast.online</link>
            {items_xml}
        </channel>
    </rss>"""
    
    headers = {
        'Content-Type': 'application/xml',
        'Link': '<https://pubsubhubbub.appspot.com/>; rel="hub", <https://hiredfast.online/feed.xml>; rel="self"'
    }
    return rss_content, 200, headers