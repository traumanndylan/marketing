#!/usr/bin/env python3
import argparse
import json
import os
import random
import sqlite3
import sys
import time

import requests

API_KEY = "dev-admin-key"

def _resolve_api_url():
    try:
        requests.get("http://openwa:2785/api/health", timeout=1)
        return "http://openwa:2785/api"
    except requests.exceptions.ConnectionError:
        return "http://localhost:2785/api"

API_URL = _resolve_api_url()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
SESSIONS_FILE = os.path.join(BASE_DIR, "config", "sessions.json")
MESSAGES_DIR = os.path.join(BASE_DIR, "config", "messages")
DB_FILE = os.path.join(BASE_DIR, "db", "leads.db")
SENT_NUMBERS_FILE = os.path.join(BASE_DIR, "db", "sent_numbers.txt")


def check_number_exists(session_id, phone):
    try:
        res = requests.get(
            f"{API_URL}/sessions/{session_id}/contacts/check/{phone}",
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        if res.status_code == 200:
            return res.json().get("exists", False)
        return False
    except Exception:
        return False

def create_contact(session_id, name, surname, phone):
    try:
        res = requests.post(
            f"{API_URL}/sessions/{session_id}/contacts/create",
            json={"name": name, "surname": surname, "phone": phone},
            headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
            timeout=15,
        )
        return res.status_code == 200
    except Exception as e:
        print(f"  Warning: create_contact failed {e}")
        return False

def load_sessions_config():
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"Error loading sessions.json: {e}")


def save_sessions_config(config):
    """Persist updated sessions configuration to disk."""
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_message(country_code, category="default"):
    paths_to_check = [
        os.path.join(MESSAGES_DIR, country_code, f"message.{category}.txt"),
        os.path.join(MESSAGES_DIR, "default", f"message.{category}.txt"),
        os.path.join(MESSAGES_DIR, country_code, "message.default.txt"),
        os.path.join(MESSAGES_DIR, "default", "message.default.txt"),
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
            timeout=5,
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
            timeout=10,
        )
        return res.status_code in (200, 201), res.text
    except Exception as e:
        return False, str(e)

def main():
    parser = argparse.ArgumentParser(description="Send queued WhatsApp messages.")
    parser.add_argument("--country", type=str, default=None,
                        help="Country code to process (e.g. ni, mx, ec)")
    args = parser.parse_args()
    target_country = args.country.upper() if args.country else None

    config = load_sessions_config()
    message_limit = config.get("message_limit_per_session", 15)

    sessions_to_use = []
    for session in config.get("sessions", []):
        if not session.get("active", False):
            continue
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
        label = target_country if target_country else "any country"
        print(f"No active sessions found for {label}.")
        return

    if not os.path.exists(DB_FILE):
        sys.exit(f"Error: {DB_FILE} not found. Run scraper first.")

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for session in sessions_to_use:
        session_id = session["session_id"]
        country = session["country"]

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM leads WHERE status = 'Queued' AND assigned_session = ?",
            (session_id,),
        )
        currently_queued = cur.fetchone()["cnt"]
        needed = max(0, message_limit - currently_queued)

        if needed > 0:
            cur.execute(
                "SELECT phone FROM leads WHERE country = ? AND status = '' LIMIT ?",
                (country, needed),
            )
            phones = [row["phone"] for row in cur.fetchall()]
            if phones:
                placeholders = ",".join("?" * len(phones))
                cur.execute(
                    f"UPDATE leads SET status = 'Queued', assigned_session = ? WHERE phone IN ({placeholders})",
                    [session_id] + phones,
                )
            conn.commit()

    total_sent = 0

    for session in sessions_to_use:
        country = session["country"]
        session_id = session["session_id"]
        country_code = session["country_code"]
        current_status = session.get("current_status", "UNKNOWN")

        cur.execute(
            "SELECT * FROM leads WHERE status = 'Queued' AND assigned_session = ?",
            (session_id,),
        )
        queue = cur.fetchall()

        if not queue:
            continue

        print(f"\nProcessing {country} (Session: {session_id} - {current_status})")

        if current_status.upper() != "READY":
            print(f"  Session not READY. {len(queue)} messages remain in queue.")
            continue

        limit = min(message_limit, len(queue))
        sent_count = 0

        for row in queue:
            phone = row["phone"]
            name = row["name"]

            if not phone:
                cur.execute("UPDATE leads SET status = 'Skipped' WHERE phone = ?", (phone,))
                conn.commit()
                continue

            if sent_count >= limit:
                break

            lead_category = row["category"] if row["category"] else "default"
            message_text = get_message(country_code, category=lead_category)

            print(f"  [{sent_count + 1}/{limit}] Sending to {name} ({phone})...")
            
            city = row["city"] if row["city"] else "Unknown City"
            lead_country = row["country"] if row["country"] else country
            surname = f"{city}, {lead_country}"
            
            print(f"  [{sent_count + 1}/{limit}] Checking if {phone} is on WhatsApp...")
            if not check_number_exists(session_id, phone):
                print(f"  Skipped: Number is not registered on WhatsApp")
                cur.execute("UPDATE leads SET status = 'Skipped' WHERE phone = ?", (phone,))
                conn.commit()
                with open(SENT_NUMBERS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{phone}\n")
                continue

            print(f"  [{sent_count + 1}/{limit}] Creating contact for {name} ({surname})...")
            create_contact(session_id, name, surname, phone)

            success, reason = send_message(session_id, phone, message_text)

            if not success and "banned" in reason.lower():
                print(f"  CRITICAL: Session {session_id} banned! Suspending {country}.")
                for s in config["sessions"]:
                    if s["session_id"] == session_id:
                        s["active"] = False
                save_sessions_config(config)
                break

            new_status = "Sent" if success else "Failed"
            cur.execute("UPDATE leads SET status = ? WHERE phone = ?", (new_status, phone))
            conn.commit()
            print(f"  {'Done' if success else f'Failed: {reason}'}")

            if success:
                sent_count += 1
                total_sent += 1
                with open(SENT_NUMBERS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{phone}\n")
                time.sleep(random.randint(15, 45))
            else:
                with open(SENT_NUMBERS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{phone}\n")
                time.sleep(2)

    conn.close()
    print(f"\nFinished. Sent {total_sent} total messages.")


if __name__ == "__main__":
    main()