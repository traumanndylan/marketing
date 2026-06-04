#!/usr/bin/env python3
import csv, os, sys, time, random, requests

API_URL = "http://localhost:2785/api"
API_KEY = "dev-admin-key"
SESSION_ID = "3b09b399-6e93-4672-8da3-e845b1e7fbe2"
MESSAGE_LIMIT = 15

def get_message():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'message.txt'), 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        sys.exit(f"Error reading message.txt: {e}")

def send_message(phone, text):
    try:
        res = requests.post(
            f"{API_URL}/sessions/{SESSION_ID}/messages/send-text",
            json={"chatId": f"{phone}@c.us", "text": text},
            headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
        )
        return res.status_code in (200, 201), res.text
    except Exception as e:
        return False, str(e)

def main():
    csv_file = os.path.expanduser('~/marketing/postProcessing/results.csv')
    if not os.path.exists(csv_file):
        sys.exit(f"Error: {csv_file} not found")

    message_text = get_message()
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if 'Status' not in fieldnames:
        sys.exit("Error: No 'Status' column.")

    remaining_eligible = sum(1 for row in rows if not row.get('Status', '').strip() and row.get('Phone #', '').strip())
    
    if remaining_eligible == 0:
        print("No pending contacts to message.")
        return

    limit = min(MESSAGE_LIMIT, remaining_eligible)
    if limit < MESSAGE_LIMIT:
        print(f"Only {limit} free contacts available (limit is {MESSAGE_LIMIT}), sending all {limit}.")
    else:
        print(f"Sending {limit} messages.")

    messages_sent = 0
    
    for row in rows:
        if messages_sent >= limit:
            print(f"\nReached the requested limit of {limit} messages.")
            break
            
        if row.get('Status', '').strip():
            continue
            
        phone = row.get('Phone #', '').strip()
        name = row.get('Name', '').strip()
        
        if not phone:
            row['Status'] = 'Skipped'
            continue

        print(f"[{messages_sent + 1}/{limit}] Sending message to {name} at {phone}...")
        success, reason = send_message(phone, message_text)
        
        row['Status'] = 'Sent' if success else 'Failed'
        print("Done" if success else f"Failed: {reason}")
        
        if success:
            messages_sent += 1
            
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        if messages_sent >= limit:
            break

        if success:
            time.sleep(random.randint(15, 45))
        else:
            time.sleep(2)

    print(f"\nSent {messages_sent} messages.")

if __name__ == '__main__':
    main()