#!/usr/bin/env python3
import csv
import json
import os
import sys
import sqlite3
import re
import reverse_geocoder as rg

def main():
    input_file = os.path.expanduser('~/marketing/scraper/gmaps-output/results.csv')
    output_file = os.path.expanduser('~/marketing/postProcessing/results.csv')

    print(f"Reading from {input_file}")
    
    blacklist_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blacklist.json')
    blacklist = []
    if os.path.exists(blacklist_file):
        try:
            with open(blacklist_file, 'r', encoding='utf-8') as bf:
                raw_blacklist = json.load(bf)
                if isinstance(raw_blacklist, list):
                    blacklist = [str(item).strip().lower() for item in raw_blacklist if item]
        except Exception as e:
            print(f"Warning: Failed to load blacklist.json: {e}")
            
    country_prefixes = {
        'NI': '505', 'NICARAGUA': '505',
        'CR': '506', 'COSTA RICA': '506',
        'HN': '504', 'HONDURAS': '504',
        'SV': '503', 'EL SALVADOR': '503',
        'GT': '502', 'GUATEMALA': '502',
        'PA': '507', 'PANAMA': '507', 'PANAMÁ': '507',
        'MX': '52',  'MEXICO': '52',  'MÉXICO': '52'
    }

    fieldnames = ['Name', 'City', 'Country', 'Phone #', 'Status', 'Assigned Session']
    existing_rows = []
    existing_phones = set()

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows.append(row)
                phone = row.get('Phone #', '').strip()
                if phone:
                    existing_phones.add(phone)

    print(f"Existing contacts: {len(existing_rows)} ({len(existing_phones)} unique phones)")

    try:
        with open(input_file, 'r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            new_rows = []
            skipped_dup = 0
            
            for row in reader:
                # 1. Skip if it has a website
                if row.get('website', '').strip():
                    continue
                
                # 2. Blacklist check
                title_lower = row.get('title', '').lower()
                if any(p in title_lower for p in blacklist):
                    continue
                    
                # Clean up business name
                name = row.get('title', '').title().split(' • ')[0].split(' - ')[0].strip()
                
                city, country_lookup = '', ''
                
                # 3. GPS Coordinates via reverse_geocoder
                lat_str = row.get('latitude', '').strip()
                lon_str = row.get('longitude', '').strip()
                
                if lat_str and lon_str:
                    try:
                        lat = float(lat_str)
                        lon = float(lon_str)
                        location_data = rg.search((lat, lon), verbose=False)[0]
                        city = location_data.get('name', '')       
                        country_lookup = location_data.get('cc', '').upper() 
                    except Exception:
                        pass 
                
                if not country_lookup:
                    country_lookup = 'NI'
                
                country_display = country_lookup
                if country_lookup == 'NI': country_display = 'Nicaragua'
                elif country_lookup == 'CR': country_display = 'Costa Rica'
                elif country_lookup == 'HN': country_display = 'Honduras'
                elif country_lookup == 'SV': country_display = 'El Salvador'
                elif country_lookup == 'GT': country_display = 'Guatemala'
                elif country_lookup == 'PA': country_display = 'Panama'
                elif country_lookup == 'MX': country_display = 'Mexico'

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

        print(f"New contacts: {len(new_rows)} | Duplicates skipped: {skipped_dup}")

        with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)
            writer.writerows(new_rows)
            
        print(f"Done. Total contacts: {len(existing_rows) + len(new_rows)}")
        
        db_path = os.path.expanduser('~/marketing/main/leads.db')
        
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                phone TEXT PRIMARY KEY,
                name TEXT,
                city TEXT,
                country TEXT,
                status TEXT DEFAULT '',
                assigned_session TEXT DEFAULT ''
            )
        ''')
        
        if new_rows:
            db_data = [
                (r['Phone #'], r['Name'], r['City'], r['Country'], r.get('Status', ''), r.get('Assigned Session', ''))
                for r in new_rows
            ]
            
            c.executemany('''
                INSERT OR IGNORE INTO leads (phone, name, city, country, status, assigned_session)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', db_data)
            
            sync_count = c.rowcount
        else:
            sync_count = 0
            
        conn.commit()
        conn.close()
        print(f"Synced {sync_count} new leads to database.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()