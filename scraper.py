#!/usr/bin/env python3
import os
import sys
import csv
import shutil
import subprocess
import time
from datetime import datetime
from tqdm import tqdm

def main():
    start_time = time.time()
    
    projects_dir = os.path.expanduser('~/marketing')
    scraper_dir = os.path.join(projects_dir, 'scraper')
    output_dir = os.path.join(scraper_dir, 'gmaps-output')
    results_file = os.path.join(output_dir, 'results.csv')
    queries_csv = os.path.join(scraper_dir, 'queries.csv')
    temp_queries = os.path.join(scraper_dir, 'temp_queries.txt')
    temp_results = os.path.join(output_dir, 'temp_city_results.csv')
    
    container_name = "gmaps-scraper"
    concurrency = "8"
    
    os.makedirs(output_dir, exist_ok=True)

    print("Generating Queries...")
    queries_script = os.path.join(projects_dir, 'queries', 'queries.py')
    subprocess.run([sys.executable, queries_script], check=True)

    if not os.path.exists(queries_csv):
        print(f"[ERROR] The file {queries_csv} was not generated. Aborting.")
        sys.exit(1)

    grouped_cities = {}
    with open(queries_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row['City']
            if city not in grouped_cities:
                grouped_cities[city] = {
                    'lat': row['Latitude'],
                    'lon': row['Longitude'],
                    'radius': row['Radius'],
                    'queries': []
                }
            grouped_cities[city]['queries'].append(row['Query'])

    total_cities = len(grouped_cities)
    if total_cities == 0:
        print("[WARNING] No cities found in queries.csv. Aborting.")
        sys.exit(0)

    if os.path.exists(results_file) and os.path.getsize(results_file) > 0:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(output_dir, f'results_backup_{timestamp}.csv')
        shutil.copy2(results_file, backup_file)
        
        with open(results_file, 'r', encoding='utf-8') as f:
            backup_lines = sum(1 for _ in f)
            
        print(f"Backed up {backup_lines} lines to {os.path.basename(backup_file)}")
        os.remove(results_file)

    subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("\nRunning Scraper...")
    interrupted = False
    
    pbar = tqdm(grouped_cities.items(), total=total_cities, desc="Scraping", unit="city", colour="green")
    
    try:
        for city, data in pbar:
            pbar.set_postfix(city=city)
            
            with open(temp_queries, 'w', encoding='utf-8') as tq:
                for q in data['queries']:
                    tq.write(f"{q}\n")
            
            if os.path.exists(temp_results):
                os.remove(temp_results)
                
            cmd = [
                "podman", "run",
                "--name", container_name,
                "-v", "gmaps-playwright-cache:/opt",
                "-v", f"{os.path.abspath(temp_queries)}:/queries.txt:ro",
                "-v", f"{os.path.abspath(output_dir)}:/out",
                "docker.io/gosom/google-maps-scraper",
                "-input", "/queries.txt",
                "-results", "/out/temp_city_results.csv",
                "-depth", "1",
                "-fast-mode",
                "-geo", f"{data['lat']},{data['lon']}",
                "-radius", data['radius'],
                "-c", concurrency,
                "-exit-on-inactivity", "3m"
            ]
            
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(temp_results) and os.path.getsize(temp_results) > 0:
                with open(temp_results, 'r', encoding='utf-8') as tr:
                    lines = tr.readlines()
                    if lines:
                        write_header = not os.path.exists(results_file)
                        with open(results_file, 'a', encoding='utf-8') as rf:
                            if write_header:
                                rf.write(lines[0])  # Write header
                            rf.writelines(lines[1:]) # Write data
                            
            subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except KeyboardInterrupt:
        interrupted = True
        tqdm.write("\n\nCaught interrupt — stopping scraper gracefully...")
        subprocess.run(["podman", "stop", "-t", "10", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["podman", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        pbar.close()

    if os.path.exists(temp_queries): os.remove(temp_queries)
    if os.path.exists(temp_results): os.remove(temp_results)

    if os.path.exists(results_file):
        with open(results_file, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f)
        print(f"\nMaster File: {results_file} - {total_lines} lines.")

    if not interrupted:
        print("\nPost Processing")
        post_script = os.path.join(projects_dir, 'postProcessing', 'main.py')
        subprocess.run([sys.executable, post_script])
    else:
        print("\nScraper finished with interruptions. Skipping Post-Processing.")

    elapsed_seconds = int(time.time() - start_time)
    minutes = elapsed_seconds // 60
    seconds = elapsed_seconds % 60

    print("")
    if minutes > 0:
        print(f"Total Execution Time: {minutes} minute(s) and {seconds} second(s).")
    else:
        print(f"Total Execution Time: {elapsed_seconds} second(s).")
    print("")

if __name__ == "__main__":
    main()