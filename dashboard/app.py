from flask import Flask, render_template, request, jsonify
import os, json, csv, subprocess, threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

BASE_DIR = "/home/dylan/marketing"
MAIN_DIR = os.path.join(BASE_DIR, "main")
CRON_DIR = os.path.join(BASE_DIR, "cron")
POST_DIR = os.path.join(BASE_DIR, "postProcessing")

SESSIONS_FILE = os.path.join(MAIN_DIR, "sessions.json")
RESULTS_FILE = os.path.join(POST_DIR, "results.csv")
CRON_LOG = os.path.join(CRON_DIR, "cron.log")
PAUSED_FILE = os.path.join(CRON_DIR, ".paused")

COUNTRY_TIMEZONES = {
    "NI": "America/Managua",     
    "CR": "America/Costa_Rica",   
    "HN": "America/Tegucigalpa",  
    "SV": "America/El_Salvador", 
    "GT": "America/Guatemala",    
    "PA": "America/Panama",       
    "EC": "America/Guayaquil",    
    "MX": "America/Mexico_City",  
    "CO": "America/Bogota",       
    "PE": "America/Lima",         
    "CL": "America/Santiago",     
    "AR": "America/Argentina/Buenos_Aires",  
    "VE": "America/Caracas",      
    "DO": "America/Santo_Domingo",
    "BO": "America/La_Paz",       
    "PY": "America/Asuncion",     
    "UY": "America/Montevideo",   
}

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
            tz_name = COUNTRY_TIMEZONES.get(cc, "America/Mexico_City")
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
        data = {"sent": 0, "queued": 0, "failed": 0, "skipped": 0, "suspended_sessions": 0}
        db_file = os.path.join(MAIN_DIR, "leads.db")
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
            conn.close()
        
        sessions = read_json(SESSIONS_FILE).get("sessions", [])
        data["suspended_sessions"] = sum(1 for s in sessions if not s.get("active", True))
        
        return jsonify(data)
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
            
            # Re-sync scheduler to pick up the new country
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
        # Find the country_code for this session and trigger a run
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

if __name__ == "__main__":
    scheduler.start()
    sync_scheduler()
    print("Scheduler started. Jobs will run automatically during business hours.")
    app.run(host="0.0.0.0", port=5001)
