from flask import Flask, render_template, request, jsonify
import os, json, csv, subprocess, threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

BASE_DIR = "/home/dylan/marketing/programs"
MAIN_DIR = os.path.join(BASE_DIR, "main")
CRON_DIR = os.path.join(BASE_DIR, "cron")
POST_DIR = os.path.join(BASE_DIR, "postProcessing")

SESSIONS_FILE = os.path.join(MAIN_DIR, "sessions.json")
RESULTS_FILE = os.path.join(POST_DIR, "results.csv")
CRON_LOG = os.path.join(CRON_DIR, "cron.log")
PAUSED_FILE = os.path.join(CRON_DIR, ".paused")

import pytz

def get_country_timezone(cc):
    try:
        zones = pytz.country_timezones(cc.upper())
        if zones:
            return zones[0]
    except Exception:
        pass
    return "UTC"

BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17

scheduler = BackgroundScheduler()

def run_bot_for_country(country_code):
    """Runs main.py for a specific country code."""
    if os.path.exists(PAUSED_FILE):
        return
    
    os.makedirs(CRON_DIR, exist_ok=True)
    log_file = open(CRON_LOG, "a")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"\n--- [{timestamp}] Scheduler triggered for {country_code} ---\n")
    log_file.flush()
    
    subprocess.Popen(
        ["python3", "-u", os.path.join(MAIN_DIR, "main.py"), "--country", country_code.lower()],
        stdout=log_file,
        stderr=subprocess.STDOUT
    )

def sync_scheduler():
    """Reads sessions.json and ensures one scheduled job exists per unique country_code."""
    try:
        config = read_json(SESSIONS_FILE)
    except Exception:
        return
    
    active_countries = set()
    for s in config.get("sessions", []):
        if s.get("active", False):
            cc = s.get("country_code", "").upper()
            if cc:
                active_countries.add(cc)
    
    existing_jobs = {job.id for job in scheduler.get_jobs()}
    
    for cc in active_countries:
        job_id = f"bot_{cc}"
        if job_id not in existing_jobs:
            tz_name = get_country_timezone(cc)
            scheduler.add_job(
                id=job_id,
                func=run_bot_for_country,
                args=[cc],
                trigger=CronTrigger(
                    minute="*/5",
                    hour=f"{BUSINESS_START_HOUR}-{BUSINESS_END_HOUR - 1}",
                    timezone=tz_name
                ),
                replace_existing=True,
                misfire_grace_time=120
            )
            print(f"Scheduled job {job_id}: every 5 min, {BUSINESS_START_HOUR}:00–{BUSINESS_END_HOUR}:00 ({tz_name})")
    
    for job_id in existing_jobs:
        if job_id.startswith("bot_"):
            cc = job_id.replace("bot_", "")
            if cc not in active_countries:
                scheduler.remove_job(job_id)
                print(f"Removed job {job_id}: no active sessions for {cc}")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/overview")
def overview():
    try:
        data = {"sent": 0, "queued": 0, "failed": 0, "skipped": 0, "suspended_sessions": 0, "total_leads": 0, "country_stats": {}}
        db_file = os.path.join(BASE_DIR, "db", "leads.db")
        if os.path.exists(db_file):
            import sqlite3
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute("SELECT status, COUNT(*) FROM leads GROUP BY status")
            rows = c.fetchall()
            for r in rows:
                st = r[0].strip() if r[0] else ''
                if st == 'Sent': data["sent"] += r[1]
                elif st == 'Queued': data["queued"] += r[1]
                elif st == 'Failed': data["failed"] += r[1]
                elif st == 'Skipped': data["skipped"] += r[1]
            
            c.execute("SELECT COUNT(*) FROM leads")
            data["total_leads"] = c.fetchone()[0]

            c.execute("SELECT country, COUNT(*) FROM leads GROUP BY country")
            for r in c.fetchall():
                data["country_stats"][r[0] if r[0] else "Unknown"] = r[1]

            conn.close()
        
        sessions = read_json(SESSIONS_FILE).get("sessions", [])
        data["suspended_sessions"] = sum(1 for s in sessions if not s.get("active", True))
        
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/upload-leads", methods=["POST"])
def upload_leads():
    try:
        leads = request.json.get("leads", [])
        if not leads:
            return jsonify({"success": False, "error": "No leads provided"}), 400
            
        db_file = os.path.join(BASE_DIR, "db", "leads.db")
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        
        import sqlite3
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                phone TEXT PRIMARY KEY,
                name TEXT,
                city TEXT,
                country TEXT,
                status TEXT DEFAULT '',
                assigned_session TEXT DEFAULT '',
                category TEXT DEFAULT 'Default'
            );
        """)
        
        # Add category column if missing
        try:
            c.execute("ALTER TABLE leads ADD COLUMN category TEXT DEFAULT 'Default'")
        except sqlite3.OperationalError:
            pass
        
        db_data = [
            (r['phone'], r['name'], r['city'], r['country'], r.get('status', ''), r.get('assigned_session', ''), r.get('category', 'Default'))
            for r in leads
        ]
        
        c.executemany("""
            INSERT OR IGNORE INTO leads (phone, name, city, country, status, assigned_session, category)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, db_data)
        
        sync_count = c.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "synced": sync_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_session_status(session_id):
    import requests
    try:
        res = requests.get(
            f"http://openwa:2785/api/sessions/{session_id}",
            headers={"X-API-Key": "dev-admin-key"},
            timeout=2
        )
        if res.status_code == 200:
            return res.json().get("status", "UNKNOWN")
        return "DISCONNECTED"
    except Exception:
        return "OFFLINE"

@app.route("/api/sessions", methods=["GET", "POST"])
def manage_sessions():
    if request.method == "GET":
        try:
            config = read_json(SESSIONS_FILE)
            for s in config.get("sessions", []):
                if s.get("active", True):
                    s["status"] = get_session_status(s["session_id"])
                else:
                    s["status"] = "SUSPENDED"
            return jsonify(config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    elif request.method == "POST":
        try:
            new_session = request.json
            config = read_json(SESSIONS_FILE)
            config["sessions"].append(new_session)
            write_json(SESSIONS_FILE, config)
            
            cc = new_session.get("country_code")
            if cc:
                cc_dir = os.path.join(MAIN_DIR, "messages", cc)
                os.makedirs(cc_dir, exist_ok=True)
                msg_path = os.path.join(cc_dir, "message.default.txt")
                if not os.path.exists(msg_path):
                    with open(msg_path, "w", encoding="utf-8") as f:
                        f.write("")
            
            sync_scheduler()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/sessions/<session_id>", methods=["DELETE", "PUT"])
def session_detail(session_id):
    if request.method == "DELETE":
        try:
            config = read_json(SESSIONS_FILE)
            config["sessions"] = [s for s in config["sessions"] if s["session_id"] != session_id]
            write_json(SESSIONS_FILE, config)
            sync_scheduler()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    elif request.method == "PUT":
        try:
            update_data = request.json
            config = read_json(SESSIONS_FILE)
            for s in config["sessions"]:
                if s["session_id"] == session_id:
                    s["name"] = update_data.get("name", s.get("name", ""))
                    s["country"] = update_data.get("country", s["country"])
                    s["country_code"] = update_data.get("country_code", s["country_code"])
                    s["session_id"] = update_data.get("session_id", s["session_id"])
                    s["active"] = update_data.get("active", s.get("active", True))
                    break
            write_json(SESSIONS_FILE, config)
            sync_scheduler()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/sessions/<session_id>/start", methods=["POST"])
def restart_session(session_id):
    import requests
    try:
        res = requests.post(
            f"http://openwa:2785/api/sessions/{session_id}/start",
            headers={"X-API-Key": "dev-admin-key"},
            timeout=5
        )
        return jsonify({"success": res.status_code in (200, 201)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook/session", methods=["POST"])
def session_webhook():
    data = request.json
    session_id = data.get("sessionId")
    new_status = data.get("status")
    
    if new_status == "READY":
        try:
            config = read_json(SESSIONS_FILE)
            for s in config.get("sessions", []):
                if s["session_id"] == session_id:
                    cc = s.get("country_code", "")
                    if cc:
                        threading.Thread(target=run_bot_for_country, args=(cc,)).start()
                    break
        except Exception:
            pass
    elif new_status in ("BANNED", "SUSPENDED"):
        mark_session_suspended(session_id)
        
    return "", 200

def mark_session_suspended(session_id):
    try:
        config = read_json(SESSIONS_FILE)
        for s in config["sessions"]:
            if s["session_id"] == session_id:
                s["active"] = False
        write_json(SESSIONS_FILE, config)
        sync_scheduler()
    except Exception:
        pass

@app.route("/api/run", methods=["POST"])
def run_now():
    action = request.json.get("action")
    country = request.json.get("country")
    if action == "run":
        if country:
            threading.Thread(target=run_bot_for_country, args=(country,)).start()
        else:
            try:
                config = read_json(SESSIONS_FILE)
                countries = set()
                for s in config.get("sessions", []):
                    if s.get("active", False):
                        cc = s.get("country_code", "").upper()
                        if cc:
                            countries.add(cc)
                for cc in countries:
                    threading.Thread(target=run_bot_for_country, args=(cc,)).start()
            except Exception:
                pass
        return jsonify({"success": True})
    elif action == "pause":
        with open(PAUSED_FILE, "w") as f: f.write("")
        return jsonify({"success": True})
    elif action == "resume":
        if os.path.exists(PAUSED_FILE):
            os.remove(PAUSED_FILE)
        return jsonify({"success": True})
    
@app.route("/api/status")
def status():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time) if job.next_run_time else "paused"
        })
    return jsonify({
        "paused": os.path.exists(PAUSED_FILE),
        "scheduled_jobs": jobs
    })

@app.route("/api/messages/<country_code>", methods=["GET", "POST"])
@app.route("/api/messages/<country_code>/<category>", methods=["GET", "POST"])
def manage_message(country_code, category="default"):
    cc_dir = os.path.join(MAIN_DIR, "messages", country_code)
    os.makedirs(cc_dir, exist_ok=True)
    path = os.path.join(cc_dir, f"message.{category}.txt")
    if request.method == "GET":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return jsonify({"text": f.read()})
        return jsonify({"text": ""})
    elif request.method == "POST":
        text = request.json.get("text", "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return jsonify({"success": True})

@app.route("/api/generate-cities", methods=["POST"])
def generate_cities():
    data = request.json
    countries = [c.upper() for c in data.get("countries", [])]
    population = int(data.get("population", 50000))
    
    if not countries:
        return jsonify({"error": "No countries selected"}), 400
        
    db_path = os.path.join(BASE_DIR, "db", "cities.db")
    if not os.path.exists(db_path):
        import subprocess
        import sys
        build_script = os.path.join(BASE_DIR, "db", "build_db.py")
        try:
            subprocess.run([sys.executable, build_script], cwd=os.path.dirname(build_script), check=True)
        except Exception as e:
            return jsonify({"error": f"Failed to build cities.db automatically: {str(e)}"}), 500
        
        if not os.path.exists(db_path):
            return jsonify({"error": "Failed to create cities.db. Please check the logs."}), 500
        
    import sqlite3
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    placeholders = ",".join("?" * len(countries))
    query = f"""
        SELECT country_code, name, population, latitude, longitude 
        FROM cities 
        WHERE UPPER(country_code) IN ({placeholders}) AND population >= ? 
        ORDER BY country_code, population DESC
    """
    
    c.execute(query, (*countries, population))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return jsonify({"error": "No cities found matching these criteria."}), 404
        
    country_names = {}
    country_info_path = os.path.join(BASE_DIR, "db", "countryInfo.txt")
    if os.path.exists(country_info_path):
        with open(country_info_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#") and line.strip():
                    parts = line.split("\t")
                    if len(parts) > 4:
                        country_names[parts[0].upper()] = parts[4]
                        
    output = []
    markers = []
    current_cc = None
    
    for cc, name, pop, lat, lon in rows:
        cname = country_names.get(cc.upper(), cc.upper())
        
        if cc != current_cc:
            if current_cc is not None:
                output.append("")
            output.append(f"#{cname}")
            current_cc = cc
            
        output.append(f"{name.title()}, {cname}")
        
        markers.append({"name": name.title(), "coords": [lat, lon]})
        
    final_text = "\n".join(output).strip() + "\n"
    return jsonify({"text": final_text, "count": len(rows), "markers": markers})

@app.route("/api/config/<filename>", methods=["GET", "POST"])
def manage_config_file(filename):
    if filename not in ["cities.txt", "types.txt", "categories.json"]:
        return jsonify({"error": "Invalid file"}), 400
        
    filepath = os.path.join(BASE_DIR, "queries", filename)
    if request.method == "GET":
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return jsonify({"text": f.read()})
        return jsonify({"text": ""})
    elif request.method == "POST":
        text = request.json.get("text", "")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)
        return jsonify({"success": True})

@app.route("/api/categories", methods=["GET"])
def get_categories():
    filepath = os.path.join(BASE_DIR, "queries", "categories.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"categories": []})

@app.route("/api/logs")
def get_logs():
    try:
        if os.path.exists(CRON_LOG):
            with open(CRON_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()[-100:]
            return jsonify({"logs": lines})
        return jsonify({"logs": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scraper/config", methods=["POST"])
def configure_scraper():
    ip = request.json.get("server_ip", "")
    env_file = os.path.expanduser("~/marketing/.env")
    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            lines = f.readlines()
    
    with open(env_file, "w") as f:
        for line in lines:
            if not line.startswith("SERVER_IP="):
                f.write(line)
        f.write(f"SERVER_IP={ip}\n")
    return jsonify({"success": True})

@app.route("/api/scraper/run", methods=["POST"])
def run_scraper_endpoint():
    target = request.json.get("target", "local")
    scraper_script = os.path.expanduser("~/marketing/scraper.py")
    
    try:
        # Clear old ETA
        eta_file = os.path.expanduser("~/marketing/scraper/eta.txt")
        if os.path.exists(eta_file):
            os.remove(eta_file)
            
        log_file_path = os.path.expanduser("~/marketing/scraper/scraper.log")
        log_file = open(log_file_path, "w")
        
        if target == "local":
            subprocess.Popen(["python3", scraper_script], cwd=os.path.expanduser("~/marketing"), stdout=log_file, stderr=subprocess.STDOUT)
        else:
            subprocess.Popen(["python3", scraper_script], cwd=os.path.expanduser("~/marketing"), stdout=log_file, stderr=subprocess.STDOUT)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scraper/eta")
def get_scraper_eta():
    try:
        eta_file = os.path.expanduser("~/marketing/scraper/eta.txt")
        if os.path.exists(eta_file):
            with open(eta_file, "r") as f:
                return jsonify({"eta": f.read().strip()})
        return jsonify({"eta": None})
    except Exception:
        return jsonify({"eta": None})

@app.route("/api/scraper/logs")
def get_scraper_logs():
    try:
        log_file = os.path.expanduser("~/marketing/scraper/scraper.log")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                # Read last 100 lines to avoid massive payloads
                lines = f.readlines()
                return jsonify({"logs": lines[-100:]})
        return jsonify({"logs": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    scheduler.start()
    sync_scheduler()
    print("Scheduler started")
    app.run(host="0.0.0.0", port=5001)