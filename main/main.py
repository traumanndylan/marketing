#!/usr/bin/env python3
import csv, os, sys, time, random, requests, json

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

def get_message(country_code):
    dir_path = os.path.dirname(__file__)
    path = os.path.join(dir_path, f"message.{country_code}.txt")
    fallback = os.path.join(dir_path, "message.default.txt")
    target = path if os.path.exists(path) else fallback
    try:
        with open(target, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading message: {e}"

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

def check_number_exists(session_id, phone):
    try:
        res = requests.get(
            f"{API_URL}/sessions/{session_id}/contacts/check/{phone}",
            headers={"X-API-Key": API_KEY},
            timeout=5
        )
        if res.status_code == 200:
            return res.json().get("exists", False)
        return True
    except Exception:
        return True

def main():
    config = load_sessions_config()
    MESSAGE_LIMIT = config.get("message_limit_per_session", 1)
    
    sessions_to_use = []
    for session in config.get("sessions", []):
        if not session.get("active", False):
            continue
        status = get_session_status(session["session_id"])
        if status.upper() in ("BANNED", "SUSPENDED"):
            print(f"Alert: Session for {session['country']} is {status}. Marking as inactive.")
            session["active"] = False
            continue
        session["current_status"] = status
        sessions_to_use.append(session)
        
    save_sessions_config(config)

    csv_file = '/home/dylan/marketing/postProcessing/results.csv'
    if not os.path.exists(csv_file):
        sys.exit(f"Error: {csv_file} not found")
        
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if 'Status' not in fieldnames:
        sys.exit("Error: No 'Status' column.")
        
    total_messages_sent = 0
    for session in sessions_to_use:
        country = session["country"]
        session_id = session["session_id"]
        country_code = session["country_code"]
        current_status = session.get("current_status")
        
        country_rows = [r for r in rows if r.get('Country', '').strip() == country]
        eligible_rows = [r for r in country_rows if r.get('Status', '').strip() in ('', 'Queued') and r.get('Phone #', '').strip()]
        
        if not eligible_rows:
            continue
            
        print(f"\nProcessing {country} (Session: {current_status})")
        
        limit = min(MESSAGE_LIMIT, len(eligible_rows))
        messages_sent_for_session = 0
        
        message_text = get_message(country_code)
        
        for row in rows:
            if row.get('Country', '').strip() != country:
                continue
            if row.get('Status', '').strip() not in ('', 'Queued'):
                continue
                
            phone = row.get('Phone #', '').strip()
            name = row.get('Name', '').strip()
            
            if not phone:
                row['Status'] = 'Skipped'
                with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                continue
                
            if messages_sent_for_session >= limit:
                break
                
            if current_status.upper() != "READY":
                if row.get('Status') != 'Queued':
                    row['Status'] = 'Queued'
                    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
                print(f"Session not READY. Queued message to {name} at {phone}.")
                continue
                
            print(f"[{messages_sent_for_session + 1}/{limit}] Sending message to {name} at {phone} in {country}...")
            
            if not check_number_exists(session_id, phone):
                print(f"Failed: Number does not exist on WhatsApp.")
                row['Status'] = 'Skipped'
                with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                time.sleep(1)
                continue
            
            success, reason = send_message(session_id, phone, message_text)
            
            if not success and "banned" in reason.lower():
                print(f"CRITICAL: Session {session_id} banned while sending! Suspending {country}.")
                row['Status'] = 'Queued'
                for s in config["sessions"]:
                    if s["session_id"] == session_id:
                        s["active"] = False
                save_sessions_config(config)
                with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                break
                
            row['Status'] = 'Sent' if success else 'Failed'
            print("Done" if success else f"Failed: {reason}")
            
            if success:
                messages_sent_for_session += 1
                total_messages_sent += 1
                
            with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                
            if messages_sent_for_session >= limit:
                break
                
            if success:
                time.sleep(random.randint(15, 45))
            else:
                time.sleep(2)

    print(f"\nFinished run. Sent {total_messages_sent} total messages.")

if __name__ == '__main__':
    main()