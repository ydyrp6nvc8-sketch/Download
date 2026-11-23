#!/usr/bin/env python3
"""List Steam games that are single-player ONLY, in batches, then merge.

- Saves a numbered CSV every BATCH_SIZE games into the folder "steam_batches".
- After MAX_FILES files it stops fetching and merges everything into one
  file: steam_singleplayer_all.csv (duplicates removed, sorted by name).
- Stop any time with Ctrl+C: nothing already saved is lost, and the merge
  still runs on whatever files exist. Run it again to resume where it left off.

Needs:  requests  (on CachyOS: sudo pacman -S python-requests)
"""
import csv
import glob
import html
import json
import os
import re
import time

import requests

# ---- settings you can change ----
BATCH_SIZE = 2000  # games per saved file
MAX_FILES = 3      # stop after this many files (3 x 2000 = 6,000 games). None = no limit
DELAY = 1.5        # seconds between requests. Raise it if Steam rate limits you.
# ---------------------------------

SEARCH_URL = "https://store.steampowered.com/search/results/"
PAGE = 100
OUT_DIR = "steam_batches"
STATE_FILE = os.path.join(OUT_DIR, "progress.json")
MERGED_FILE = "steam_singleplayer_all.csv"
FIELDS = ["appid", "name", "released", "url"]

# Steam user-tag IDs: Multiplayer, Co-op, Online Co-Op, PvP, Local Multiplayer,
# Local Co-Op, MMORPG, Massively Multiplayer
NEG_TAGS = "3859,1685,3843,1775,7368,4508,3859,128"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (steam-singleplayer-lister)"


def get_json(url, params):
    for attempt in range(5):
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s ({e})")
            time.sleep(wait)
    raise SystemExit("Too many failures. Wait a few minutes and run it again; it will resume.")


def parse_rows(results_html):
    games = []
    for row in re.split(r'<a href="', results_html)[1:]:
        m_id = re.search(r'data-ds-appid="(\d+)', row)
        m_name = re.search(r'<span class="title">(.*?)</span>', row, re.S)
        m_date = re.search(r'search_released[^>]*>\s*(.*?)\s*</div>', row, re.S)
        if m_id and m_name:
            appid = int(m_id.group(1))
            games.append({
                "appid": appid,
                "name": html.unescape(m_name.group(1)).strip(),
                "released": html.unescape(m_date.group(1)).strip() if m_date else "",
                "url": f"https://store.steampowered.com/app/{appid}/",
            })
    return games


def save_batch(batch, part):
    path = os.path.join(OUT_DIR, f"steam_sp_part_{part:04d}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(batch)
    print(f"  saved {path} ({len(batch)} games)")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"start": 0, "part": 0, "seen": []}


def save_state(start, part, seen):
    with open(STATE_FILE, "w") as f:
        json.dump({"start": start, "part": part, "seen": sorted(seen)}, f)


def merge():
    files = sorted(glob.glob(os.path.join(OUT_DIR, "steam_sp_part_*.csv")))
    if not files:
        print("No part files to merge yet.")
        return
    games = {}
    for path in files:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                games[row["appid"]] = row
    rows = sorted(games.values(), key=lambda g: g["name"].lower())
    with open(MERGED_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Merged {len(rows)} games from {len(files)} files into {MERGED_FILE}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state = load_state()
    seen = set(state["seen"])
    start, part = state["start"], state["part"]
    batch, total = [], None
    if start:
        print(f"Resuming from result {start}, next file is part {part + 1}.")

    hit_limit = False
    try:
        while (total is None or start < total) and not hit_limit:
            params = {
                "query": "", "infinite": 1, "ndl": 1, "count": PAGE, "start": start,
                "category1": 998,       # games only
                "category2": 2,         # single-player
                "negtagids": NEG_TAGS,  # exclude multiplayer-ish tags
            }
            data = get_json(SEARCH_URL, params)
            total = data.get("total_count", 0)
            for g in parse_rows(data.get("results_html", "")):
                if g["appid"] not in seen:
                    seen.add(g["appid"])
                    batch.append(g)
            start += PAGE
            print(f"{min(start, total)}/{total}")

            while len(batch) >= BATCH_SIZE:
                part += 1
                save_batch(batch[:BATCH_SIZE], part)
                batch = batch[BATCH_SIZE:]
                if MAX_FILES and part >= MAX_FILES:
                    hit_limit = True
                    break
            if not batch:
                save_state(start, part, seen)
            time.sleep(DELAY)
    except KeyboardInterrupt:
        print("\nStopped.")

    if batch and not hit_limit:  # save leftovers so nothing is lost
        part += 1
        save_batch(batch, part)
        batch = []
    if not batch:
        save_state(start, part, seen)
    print(f"Fetching done: {part} files in the '{OUT_DIR}' folder.")
    merge()


main()
