#!/usr/bin/env python3
import argparse
import os
import csv
import sqlite3
import unicodedata
import difflib
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_DIR = os.path.join(SCRIPT_DIR, "..", "..", "scraper")
DB_PATH = os.path.join(SCRIPT_DIR, "..", "db", "cities.db")
COUNTRY_INFO_PATH = os.path.join(SCRIPT_DIR, "..", "db", "countryInfo.txt")

DEFAULT_RADIUS = 20000 

def remove_accents(input_str: str) -> str:
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()

def load_lines(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8") as f:
        lines = []
        for line in f:
            clean_line = line.split('#')[0].strip()
            if clean_line:
                lines.append(clean_line)
    return lines

def load_country_mapping() -> dict:
    mapping = {}
    if not os.path.exists(COUNTRY_INFO_PATH):
        return mapping
        
    with open(COUNTRY_INFO_PATH, encoding="utf-8") as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) > 4:
                code = parts[0].strip().lower()
                name = remove_accents(parts[4].strip())
                mapping[name] = code
    
    mapping['mexico'] = 'mx'
    mapping['panama'] = 'pa'
    mapping['republica dominicana'] = 'do'
    mapping['estados unidos'] = 'us'
    
    return mapping

def get_coordinates(city_string: str, cursor, country_mapping: dict) -> tuple:
    parts = [p.strip() for p in city_string.split(',')]
    
    raw_city = parts[0].lower()
    search_city = remove_accents(parts[0])
    country_code = None
    
    if len(parts) > 1:
        search_country = remove_accents(parts[1])
        country_code = country_mapping.get(search_country)

    if not hasattr(get_coordinates, "country_cities_cache"):
        get_coordinates.country_cities_cache = {}

    if country_code:
        cursor.execute('''
            SELECT latitude, longitude FROM cities
            WHERE name = ? AND country_code = ?
            ORDER BY population DESC LIMIT 1
        ''', (raw_city, country_code))
    else:
        cursor.execute('''
            SELECT latitude, longitude FROM cities
            WHERE name = ?
            ORDER BY population DESC LIMIT 1
        ''', (raw_city,))
        
    result = cursor.fetchone()
    if result:
        return result[0], result[1]

    if country_code:
        if country_code not in get_coordinates.country_cities_cache:
            cursor.execute('''
                SELECT name, latitude, longitude FROM cities
                WHERE country_code = ?
                ORDER BY population DESC LIMIT 5000
            ''', (country_code,))
            
            country_cities = cursor.fetchall()
            get_coordinates.country_cities_cache[country_code] = {remove_accents(row[0]): (row[1], row[2]) for row in country_cities}
            
        city_dict = get_coordinates.country_cities_cache[country_code]
        matches = difflib.get_close_matches(search_city, city_dict.keys(), n=1, cutoff=0.75)
        
        if matches:
            best_match = matches[0]
            return city_dict[best_match]

    return None, None

def main():
    parser = argparse.ArgumentParser(description="Generate scraper queries.")
    parser.add_argument("--cities", default=os.path.join(SCRIPT_DIR, "cities.txt"))
    parser.add_argument("--types", default=os.path.join(SCRIPT_DIR, "types.txt"))
    parser.add_argument("--output", default=os.path.join(SCRAPER_DIR, "queries.csv"))
    args = parser.parse_args()

    cities = load_lines(args.cities)
    types = load_lines(args.types)

    if not cities or not types:
        print("Missing cities or types data")
        return

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    country_mapping = load_country_mapping()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    city_data = {}
    
    for city in tqdm(cities, desc="Resolving Coordinates", unit="city", colour="green", ncols=110):
        lat, lon = get_coordinates(city, cursor, country_mapping)
        if lat and lon:
            city_data[city] = (lat, lon)
        else:
            tqdm.write(f"No coordinates found for: {city}")

    conn.close()

    rows = []
    for city, (lat, lon) in city_data.items():
        for t in types:
            query = f"{t} en {city}"
            rows.append([city, lat, lon, DEFAULT_RADIUS, query])

    total_queries = len(rows)

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["City", "Latitude", "Longitude", "Radius", "Query"])
        writer.writerows(rows)

    print(f"Cities Generated:  {len(city_data)}/{len(cities)}")
    print(f"Queries Generated: {total_queries}")
    print(f"Results Saved in:  {args.output}\n")

if __name__ == "__main__":
    main()