from flask import Flask, render_template, request, jsonify
import os, json, csv, subprocess, threading
from datetime import datetime

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
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get("Status", "").strip()
                    if status == "Sent": data["sent"] += 1
                    elif status == "Queued": data["queued"] += 1
                    elif status == "Failed": data["failed"] += 1
                    elif status == "Skipped": data["skipped"] += 1
        
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
                msg_path = os.path.join(MAIN_DIR, f"message.{cc}.txt")
                if not os.path.exists(msg_path):
                    with open(msg_path, "w", encoding="utf-8") as f:
                        f.write("")
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
        threading.Thread(target=retry_queued, args=(session_id,)).start()
    elif new_status in ("BANNED", "SUSPENDED"):
        mark_session_suspended(session_id)
        
    return "", 200

def retry_queued(session_id):
    subprocess.Popen(["python3", os.path.join(MAIN_DIR, "main.py")])

def mark_session_suspended(session_id):
    try:
        config = read_json(SESSIONS_FILE)
        for s in config["sessions"]:
            if s["session_id"] == session_id:
                s["active"] = False
        write_json(SESSIONS_FILE, config)
    except Exception:
        pass

@app.route("/api/run", methods=["POST"])
def run_now():
    action = request.json.get("action")
    if action == "run":
        subprocess.Popen(["python3", os.path.join(MAIN_DIR, "main.py")])
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
    return jsonify({
        "paused": os.path.exists(PAUSED_FILE)
    })

@app.route("/api/messages/<country_code>", methods=["GET", "POST"])
def manage_message(country_code):
    path = os.path.join(MAIN_DIR, f"message.{country_code}.txt")
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
    app.run(host="0.0.0.0", port=5001)
