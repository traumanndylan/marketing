#!/usr/bin/env python3
import csv, os, sys, time, random, requests, json, argparse

API_URL = "http://openwa:2785/api"
try:
    requests.get(f"{API_URL}/health", timeout=1)
except requests.exceptions.ConnectionError:
    API_URL = "http://localhost:2785/api"

API_KEY = "dev-admin-key"

def load_sessions_config():
    config_path = os.path.join(os.path.dirname(__file__), 'sessions.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"Error loading sessions.json: {e}")

def save_sessions_config(config):
    config_path = os.path.join(os.path.dirname(__file__), 'sessions.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

def get_message(country_code, category="default"):
    dir_path = os.path.join(os.path.dirname(__file__), "messages")
    
    paths_to_check = [
        os.path.join(dir_path, country_code, f"message.{category}.txt"),
        os.path.join(dir_path, "default", f"message.{category}.txt"),
        os.path.join(dir_path, country_code, "message.default.txt"),
        os.path.join(dir_path, "default", "message.default.txt")
    ]
    
    for path in paths_to_check:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading message from {path}: {e}"
                
    return "Error: No message template found."

def get_session_status(session_id):
    try:
        res = requests.get(
            f"{API_URL}/sessions/{session_id}",
            headers={"X-API-Key": API_KEY},
            timeout=5
        )
        if res.status_code == 200:
            return res.json().get("status", "UNKNOWN")
        return "ERROR"
    except Exception:
        return "ERROR"

def send_message(session_id, phone, text):
    try:
        res = requests.post(
            f"{API_URL}/sessions/{session_id}/messages/send-text",
            json={"chatId": f"{phone}@c.us", "text": text},
            headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
            timeout=10
        )
        return res.status_code in (200, 201), res.text
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--country', type=str, default=None,
                        help='Country code to process (e.g. ni, mx, ec). If omitted, processes all.')
    args = parser.parse_args()
    target_country = args.country.upper() if args.country else None

    config = load_sessions_config()
    MESSAGE_LIMIT = config.get("message_limit_per_session", 15)
    
    sessions_to_use = []
    for session in config.get("sessions", []):
        if not session.get("active", False):
            continue
        # Filter by country code if specified
        if target_country and session.get("country_code", "").upper() != target_country:
            continue
        status = get_session_status(session["session_id"])
        if status.upper() in ("BANNED", "SUSPENDED"):
            print(f"Alert: Session for {session['country']} is {status}. Marking as inactive.")
            session["active"] = False
            continue
        session["current_status"] = status
        sessions_to_use.append(session)
        
    save_sessions_config(config)

    if not sessions_to_use:
        country_label = target_country if target_country else "any country"
        print(f"No active sessions found for {country_label}.")
        return

    db_file = '/home/dylan/marketing/main/leads.db'
    if not os.path.exists(db_file):
        sys.exit(f"Error: {db_file} not found. Run scraper first.")
        
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # --- STAGE 1: ALLOCATION ---
    for session in sessions_to_use:
        country = session["country"]
        session_id = session["session_id"]
        
        c.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'Queued' AND assigned_session = ?", (session_id,))
        currently_queued = c.fetchone()['cnt']
        needed = max(0, MESSAGE_LIMIT - currently_queued)
        
        if needed > 0:
            c.execute("SELECT phone FROM leads WHERE country = ? AND status = '' LIMIT ?", (country, needed))
            eligible = c.fetchall()
            for r in eligible:
                c.execute("UPDATE leads SET status = 'Queued', assigned_session = ? WHERE phone = ?", (session_id, r['phone']))
            conn.commit()

    # --- STAGE 2: EXECUTION ---
    total_messages_sent = 0
    for session in sessions_to_use:
        country = session["country"]
        session_id = session["session_id"]
        country_code = session["country_code"]
        current_status = session.get("current_status")
        
        c.execute("SELECT * FROM leads WHERE status = 'Queued' AND assigned_session = ?", (session_id,))
        my_queue = c.fetchall()
        
        if not my_queue:
            continue
            
        print(f"\nProcessing {country} (Session: {session_id} - {current_status})")
        
        if current_status.upper() != "READY":
            print(f"Session not READY. {len(my_queue)} messages remain in queue.")
            continue
            
        limit = min(MESSAGE_LIMIT, len(my_queue))
        messages_sent_for_session = 0
        
        for row in my_queue:
            phone = row['phone']
            name = row['name']
            
            if not phone:
                c.execute("UPDATE leads SET status = 'Skipped' WHERE phone = ?", (phone,))
                conn.commit()
                continue
                
            categories = ['default', 'clinica', 'academia', 'agencia', 'tecnologia']
            message_category = random.choice(categories)
            message_text = get_message(country_code, category=message_category)
            
            if messages_sent_for_session >= limit:
                break
                
            print(f"[{messages_sent_for_session + 1}/{limit}] Sending message to {name} at {phone} in {country}...")
            
            success, reason = send_message(session_id, phone, message_text)
            
            if not success and "banned" in reason.lower():
                print(f"CRITICAL: Session {session_id} banned while sending! Suspending {country}.")
                for s in config["sessions"]:
                    if s["session_id"] == session_id:
                        s["active"] = False
                save_sessions_config(config)
                break
                
            new_status = 'Sent' if success else 'Failed'
            c.execute("UPDATE leads SET status = ? WHERE phone = ?", (new_status, phone))
            conn.commit()
            print("Done" if success else f"Failed: {reason}")
            
            if success:
                messages_sent_for_session += 1
                total_messages_sent += 1
                
            if messages_sent_for_session >= limit:
                break
                
            if success:
                time.sleep(random.randint(15, 45))
            else:
                time.sleep(2)

    conn.close()
    print(f"\nFinished run. Sent {total_messages_sent} total messages.")

if __name__ == '__main__':
    main()