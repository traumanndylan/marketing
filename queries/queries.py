#!/usr/bin/env python3
import argparse
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_DIR = os.path.join(SCRIPT_DIR, "..", "scraper")


def load_lines(filepath: str) -> list[str]:
    with open(filepath, encoding="utf-8") as f:
        lines = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]
    return lines


def generate_queries(cities: list[str], types: list[str]) -> list[str]:
    return [f"{t} en {c}" for t in types for c in cities]


def main():
    parser = argparse.ArgumentParser(
        description="Generate scraper queries from a list of cities and business types."
    )
    parser.add_argument(
        "--cities",
        default=os.path.join(SCRIPT_DIR, "cities.txt"),
        help="Path to the cities file (one 'City, Country' per line). Default: cities.txt",
    )
    parser.add_argument(
        "--types",
        default=os.path.join(SCRIPT_DIR, "types.txt"),
        help="Path to the business types file (one type per line). Default: types.txt",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(SCRAPER_DIR, "queries.txt"),
        help="Output file for generated queries. Default: queries.txt",
    )
    args = parser.parse_args()

    cities = load_lines(args.cities)
    types = load_lines(args.types)

    if not cities:
        print(f"[ERROR] No cities found in '{args.cities}'.")
        return
    if not types:
        print(f"[ERROR] No business types found in '{args.types}'.")
        return

    queries = generate_queries(cities, types)
    total = len(queries)

    with open(args.output, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(q + "\n")

    print(f"Generated {total} queries ({len(types)} types × {len(cities)} cities)")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
