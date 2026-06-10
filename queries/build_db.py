import sqlite3
import zipfile
import os

ZIP_FILE = 'allCountries.zip'
DB_FILE = 'cities.db'

def build_database():
    if not os.path.exists(ZIP_FILE):
        print(f"[ERROR] {ZIP_FILE} not found in the current directory.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    print("Creating database schema...")
    cursor.execute('DROP TABLE IF EXISTS cities')
    cursor.execute('''
        CREATE TABLE cities (
            name TEXT,
            country_code TEXT,
            latitude REAL,
            longitude REAL,
            population INTEGER
        )
    ''')

    print(f"Reading {ZIP_FILE} and filtering for cities... (This may take a minute or two)")
    
    insert_query = '''
        INSERT INTO cities (name, country_code, latitude, longitude, population)
        VALUES (?, ?, ?, ?, ?)
    '''
    
    batch = []
    count = 0

    with zipfile.ZipFile(ZIP_FILE) as z:
        with z.open('allCountries.txt') as f:
            for line in f:
                parts = line.decode('utf-8').split('\t')

                if parts[6] == 'P':
                    name = parts[1].lower()
                    lat = float(parts[4])
                    lon = float(parts[5])
                    country_code = parts[8].lower()
                    pop = int(parts[14]) if parts[14].strip() else 0

                    batch.append((name, country_code, lat, lon, pop))
                    count += 1

                    if len(batch) >= 100000:
                        cursor.executemany(insert_query, batch)
                        batch = []

    if batch:
        cursor.executemany(insert_query, batch)

    print(f"Inserted {count} cities. Creating search index...")
    cursor.execute('CREATE INDEX idx_name_country ON cities(name, country_code)')

    conn.commit()
    conn.close()
    print("Database built successfully!")

if __name__ == "__main__":
    build_database()