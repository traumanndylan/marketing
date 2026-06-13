#!/usr/bin/env python3
import os
import sys
import csv
import shutil
import subprocess
import time
from datetime import datetime

needs_restart = False
for package in ["tqdm", "requests"]:
    try:
        __import__(package)
    except ImportError:
        print(f"{package} not found. Auto-installing")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "--user", "--break-system-packages", package
        ])
        needs_restart = True

if needs_restart:
    print("Restarting script to load new packages")
    os.execv(sys.executable, [sys.executable] + sys.argv)

from tqdm import tqdm

def main():
    start_time = time.time()
    
    projects_dir = os.path.dirname(os.path.abspath(__file__))
    scraper_dir = os.path.join(projects_dir, 'scraper')
    output_dir = os.path.join(scraper_dir, 'gmaps-output')
    results_file = os.path.join(output_dir, 'results.csv')
    queries_csv = os.path.join(scraper_dir, 'queries.csv')
    temp_queries = os.path.join(scraper_dir, 'temp_queries.txt')
    temp_results = os.path.join(output_dir, 'temp_city_results.csv')
    
    container_name = "gmaps-scraper"
    concurrency = "8"
    
    os.makedirs(output_dir, exist_ok=True)

    print("Generating Queries")
    
    env_file = os.path.join(projects_dir, '.env')
    server_ip = None
    if os.path.exists(env_file):
        with open(env_file, 'r') as ef:
            for line in ef:
                if line.strip().startswith('SERVER_IP='):
                    server_ip = line.strip().split('=', 1)[1].strip()
                    
    if server_ip:
        import requests
        print(f"Syncing scraper configuration from server ({server_ip})...")
        try:
            for filename in ['cities.txt', 'types.txt']:
                res = requests.get(f"http://{server_ip}:5001/api/config/{filename}", timeout=5)
                if res.status_code == 200:
                    text = res.json().get('text', '')
                    if text:
                        file_path = os.path.join(projects_dir, 'backend', 'config', filename)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(text)
        except Exception as e:
            print(f"Warning: Failed to sync config from server: {e}")
    
    db_path = os.path.join(projects_dir, 'backend', 'db', 'cities.db')
    if not os.path.exists(db_path):
        print("cities.db not found. Building database")
        build_db_script = os.path.join(projects_dir, 'backend', 'db', 'build_db.py')
        subprocess.run([sys.executable, build_db_script], cwd=os.path.dirname(build_db_script), check=True)
        
    queries_script = os.path.join(projects_dir, 'backend', 'config', 'queries.py')
    subprocess.run([sys.executable, queries_script], check=True)

    if not os.path.exists(queries_csv):
        print(f"queries.csv was not generated. Aborting.")
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
        print("No cities found in queries.csv")
        sys.exit(0)

    if os.path.exists(results_file) and os.path.getsize(results_file) > 0:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(output_dir, f'results_backup_{timestamp}.csv')
        shutil.copy2(results_file, backup_file)
        
        with open(results_file, 'r', encoding='utf-8') as f:
            backup_lines = sum(1 for _ in f)
            
        print(f"Backed up {backup_lines} lines to {os.path.basename(backup_file)}")
        os.remove(results_file)

    subprocess.run(["podman", "--remote", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("\nRunning Scraper")
    interrupted = False
    
    pbar = tqdm(grouped_cities.items(), total=total_cities, desc="Scraping", unit="city", colour="green", ncols=110)
    
    try:
        import json
        with open(os.path.join(scraper_dir, 'eta.txt'), 'w') as ef:
            json.dump({"status": "calculating", "progress": 0, "total": total_cities}, ef)
    except:
        pass

    try:
        completed = 0
        loop_start_time = time.time()
        for city, data in pbar:
            pbar.set_postfix_str(f"city={city[:30]:<30}")
            
            with open(temp_queries, 'w', encoding='utf-8') as tq:
                for q in data['queries']:
                    tq.write(f"{q}\n")
            
            if os.path.exists(temp_results):
                os.remove(temp_results)
                
            cmd = [
                "podman", "--remote", "run",
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
                                rf.write(lines[0])
                            rf.writelines(lines[1:])
                            
            subprocess.run(["podman", "--remote", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            completed += 1
            avg_time = (time.time() - loop_start_time) / completed
            remaining_cities = total_cities - completed
            eta_seconds = int(avg_time * remaining_cities)
            try:
                import json
                with open(os.path.join(scraper_dir, 'eta.txt'), 'w') as ef:
                    json.dump({"status": "running", "eta": eta_seconds, "progress": completed, "total": total_cities}, ef)
            except Exception:
                pass


    except KeyboardInterrupt:
        interrupted = True
        tqdm.write("\n\n Programm Interrupted")
        subprocess.run(["podman", "--remote", "stop", "-t", "10", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["podman", "--remote", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        post_script = os.path.join(projects_dir, 'backend', 'post_processing', 'main.py')
        subprocess.run([sys.executable, post_script])
    else:
        print("\nPost Processing Skipped")

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