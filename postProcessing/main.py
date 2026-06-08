#!/usr/bin/env python3
import csv
import json
import os
import sys

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
        'NI': '505',
        'CR': '506',
        'HN': '504',
        'SV': '503',
        'GT': '502',
        'PA': '507',
        'MX': '52'
    }

    fieldnames = ['Name', 'City', 'Country', 'Phone #', 'Status']
    existing_rows = []
    existing_phones = set()

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
                if row.get('website', '').strip():
                    continue
                
                title_lower = row.get('title', '').lower()
                if any(p in title_lower for p in blacklist):
                    continue
                    
                name = row.get('title', '').title().split(' • ')[0].split(' - ')[0].strip()
                
                city, country = '', ''
                if addr_raw := row.get('complete_address'):
                    try:
                        addr_data = json.loads(addr_raw)
                        city = addr_data.get('city', '')
                        country = addr_data.get('country', '')
                    except json.JSONDecodeError:
                        pass
                        
                phone = row.get('phone', '').strip().replace(' ', '').lstrip('+')
                if not phone:
                    continue
                
                prefix = country_prefixes.get(country, '')
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
                    'Country': country,
                    'Phone #': phone,
                    'Status': ''
                })

        print(f"New contacts: {len(new_rows)} | Duplicates skipped: {skipped_dup}")

        with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)
            writer.writerows(new_rows)
            
        print(f"Done. Total contacts: {len(existing_rows) + len(new_rows)}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()