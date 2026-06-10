#!/usr/bin/env python3
import csv
import json
import os
import sys
import sqlite3
import re
from tqdm import tqdm

QUERY_FIND_NEAREST_CITY = """
SELECT name, country_code 
FROM cities 
WHERE latitude BETWEEN ? AND ? 
  AND longitude BETWEEN ? AND ?
ORDER BY population DESC 
LIMIT 1;
"""

QUERY_CREATE_LEADS_TABLE = """
CREATE TABLE IF NOT EXISTS leads (
    phone TEXT PRIMARY KEY,
    name TEXT,
    city TEXT,
    country TEXT,
    status TEXT DEFAULT '',
    assigned_session TEXT DEFAULT ''
);
"""

QUERY_INSERT_LEAD = """
INSERT OR IGNORE INTO leads (phone, name, city, country, status, assigned_session)
VALUES (?, ?, ?, ?, ?, ?);
"""

def load_dynamic_country_data(filepath: str) -> tuple[dict, dict]:
    prefixes = {}
    display_map = {}
    
    if not os.path.exists(filepath):
        print(f"[WARNING] {filepath} not found. Country prefix processing will be unavailable.")
        return prefixes, display_map

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            
            parts = line.split('\t')
            if len(parts) > 12:
                code = parts[0].strip().upper()
                name = parts[4].strip()
                phone_prefix = parts[12].strip().replace('+', '')
                
                if code:
                    display_map[code] = name
                    if phone_prefix:
                        prefixes[code] = phone_prefix
                        
    return prefixes, display_map

def main():
    input_file = os.path.expanduser('~/marketing/scraper/gmaps-output/results.csv')
    output_file = os.path.expanduser('~/marketing/postProcessing/results.csv')
    cities_db_path = os.path.expanduser('~/marketing/queries/cities.db')
    country_info_path = os.path.expanduser('~/marketing/queries/countryInfo.txt')
    leads_db_path = os.path.expanduser('~/marketing/main/leads.db')

    print(f"Reading from {input_file}")
    
    blacklist_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blacklist.json')
    blacklist_regex = None
    if os.path.exists(blacklist_file):
        try:
            with open(blacklist_file, 'r', encoding='utf-8') as bf:
                raw_blacklist = json.load(bf)
                if isinstance(raw_blacklist, list):
                    clean_blacklist = [re.escape(str(item).strip().lower()) for item in raw_blacklist if str(item).strip()]
                    if clean_blacklist:
                        blacklist_regex = re.compile('|'.join(clean_blacklist))
        except Exception as e:
            print(f"Warning: Failed to load blacklist.json: {e}")

    print("Building country metadata maps dynamically...")
    country_prefixes, country_display_map = load_dynamic_country_data(country_info_path)
    print(f"Loaded metadata rules for {len(country_display_map)} countries.")

    fieldnames = ['Name', 'City', 'Country', 'Phone #', 'Status', 'Assigned Session']
    existing_phones = set()
    output_exists = os.path.exists(output_file) and os.path.getsize(output_file) > 0

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    if output_exists:
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                phone = row.get('Phone #', '').strip()
                if phone:
                    existing_phones.add(phone)

    print(f"Existing contacts loaded: {len(existing_phones)} unique phones\n")

    cities_conn = None
    cities_cursor = None
    if os.path.exists(cities_db_path):
        cities_conn = sqlite3.connect(cities_db_path)
        cities_cursor = cities_conn.cursor()

    coord_cache = {}

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            total_rows = sum(1 for _ in f) - 1
            if total_rows < 1:
                total_rows = 1

        with open(input_file, 'r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            new_rows = []
            skipped_dup = 0
            
            # THE TQDM MAGIC: Wraps the loop in a beautiful loading bar
            for row in tqdm(reader, total=total_rows, desc="Processing Leads", unit="lead", colour="green"):

                if row.get('website', '').strip():
                    continue
                
                title_lower = row.get('title', '').lower() if row.get('title') else ''
                if blacklist_regex and blacklist_regex.search(title_lower):
                    continue
                    
                name = row.get('title', '').title().split(' • ')[0].split(' - ')[0].strip() if row.get('title') else 'Unknown'
                city, country_lookup = '', 'NI'
                
                lat_str = row.get('latitude', '').strip() if row.get('latitude') else ''
                lon_str = row.get('longitude', '').strip() if row.get('longitude') else ''
                
                if lat_str and lon_str:
                    coord_key = (lat_str, lon_str)
                    if coord_key in coord_cache:
                        city, country_lookup = coord_cache[coord_key]
                    elif cities_cursor:
                        try:
                            lat = float(lat_str)
                            lon = float(lon_str)
                            
                            cities_cursor.execute(QUERY_FIND_NEAREST_CITY, (lat - 0.15, lat + 0.15, lon - 0.15, lon + 0.15))
                            db_match = cities_cursor.fetchone()
                            if db_match:
                                city = db_match[0].title()
                                country_lookup = db_match[1].upper()
                            coord_cache[coord_key] = (city, country_lookup)
                        except Exception:
                            pass
                
                country_display = country_display_map.get(country_lookup, country_lookup)

                raw_phone = row.get('phone', '')
                phone = re.sub(r'\D', '', raw_phone)
                
                if not phone:
                    continue
                
                prefix = country_prefixes.get(country_lookup, '')
                
                if prefix and phone.startswith(prefix) and len(phone) > len(prefix):
                    phone = phone[len(prefix):]
                
                if len(phone) < 7 or len(phone) > 10:
                    continue
                
                if prefix:
                    phone = prefix + phone

                if phone in existing_phones:
                    skipped_dup += 1
                    continue

                existing_phones.add(phone)
                new_rows.append({
                    'Name': name,
                    'City': city,
                    'Country': country_display,
                    'Phone #': phone,
                    'Status': '',
                    'Assigned Session': ''
                })
        
        if cities_conn:
            cities_conn.close()

        print(f"\nNew contacts processed: {len(new_rows)} | Duplicates skipped: {skipped_dup}")

        write_mode = 'a' if output_exists else 'w'
        with open(output_file, write_mode, encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            if not output_exists:
                writer.writeheader()
            if new_rows:
                writer.writerows(new_rows)
            
        os.makedirs(os.path.dirname(leads_db_path), exist_ok=True)
        conn = sqlite3.connect(leads_db_path)
        c = conn.cursor()
        
        c.execute(QUERY_CREATE_LEADS_TABLE)
        
        if new_rows:
            db_data = [
                (r['Phone #'], r['Name'], r['City'], r['Country'], r.get('Status', ''), r.get('Assigned Session', ''))
                for r in new_rows
            ]
            c.executemany(QUERY_INSERT_LEAD, db_data)
            sync_count = c.rowcount
        else:
            sync_count = 0
            
        conn.commit()
        conn.close()
        print(f"Synced {sync_count} new leads to database.")
        
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()