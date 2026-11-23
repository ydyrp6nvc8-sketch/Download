#!/usr/bin/env python3
"""List Steam games that are single-player ONLY (no multiplayer of any kind).

Step 1 (fast):  asks Steam for single-player games and excludes anything
                tagged multiplayer / co-op / PvP / local multiplayer.
Step 2 (slow, optional): python3 steam_singleplayer.py --verify
                double-checks every game against Steam's official category
                list and drops any that still have a multiplayer feature.
                It saves progress, so you can stop (Ctrl+C) and resume.

Needs:  pip3 install requests
"""
import csv
import html
import json
import os
import re
import sys
import time

import requests

SEARCH_URL = "https://store.steampowered.com/search/results/"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
PAGE = 100
DELAY = 1.5

# Steam user-tag IDs: Multiplayer, Co-op, Online Co-Op, PvP, Local Multiplayer,
# Local Co-Op, MMORPG, Massively Multiplayer
NEG_TAGS = "3859,1685,3843,1775,7368,4508,3859,128"

# Official Steam category IDs that mean "has multiplayer of some kind"
MULTI_CATEGORIES = {1, 9, 20, 24, 27, 36, 37, 38, 39, 47, 48, 49}

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
    raise SystemExit("Too many failures, stopping.")


def fetch_candidates():
    params = {
        "query": "", "infinite": 1, "ndl": 1, "count": PAGE, "start": 0,
        "category1": 998,        # games only (no DLC/software/soundtracks)
        "category2": 2,          # single-player
        "negtagids": NEG_TAGS,   # exclude multiplayer-ish tags
    }
    games, total = {}, None
    while total is None or params["start"] < total:
        data = get_json(SEARCH_URL, params)
        total = data.get("total_count", 0)
        for row in re.split(r'<a href="', data.get("results_html", ""))[1:]:
            m_id = re.search(r'data-ds-appid="(\d+)', row)
            m_name = re.search(r'<span class="title">(.*?)</span>', row, re.S)
            m_date = re.search(r'search_released[^>]*>\s*(.*?)\s*</div>', row, re.S)
            if m_id and m_name:
                appid = int(m_id.group(1))
                games[appid] = {
                    "appid": appid,
                    "name": html.unescape(m_name.group(1)).strip(),
                    "released": html.unescape(m_date.group(1)).strip() if m_date else "",
                    "url": f"https://store.steampowered.com/app/{appid}/",
                }
        params["start"] += PAGE
        print(f"{min(params['start'], total)}/{total}  ({len(games)} found)")
        time.sleep(DELAY)
    return games


def verify(games):
    cache_file = "verified_cache.json"
    cache = json.load(open(cache_file)) if os.path.exists(cache_file) else {}
    ids = [a for a in games if str(a) not in cache]
    print(f"Verifying {len(ids)} games (resumable)...")
    try:
        for i, appid in enumerate(ids, 1):
            data = get_json(DETAILS_URL, {"appids": appid, "filters": "categories"})
            entry = data.get(str(appid), {})
            if entry.get("success"):
                cats = {c["id"] for c in entry["data"].get("categories", [])}
                cache[str(appid)] = not (cats & MULTI_CATEGORIES)
            else:
                cache[str(appid)] = True  # unknown: keep
            if i % 25 == 0:
                json.dump(cache, open(cache_file, "w"))
                print(f"  {i}/{len(ids)}")
            time.sleep(1.6)  # Steam allows ~200 requests per 5 minutes
    except KeyboardInterrupt:
        print("Stopped; progress saved. Run again to resume.")
    json.dump(cache, open(cache_file, "w"))
    return {a: g for a, g in games.items() if cache.get(str(a), True)}


def main():
    games = fetch_candidates()
    if "--verify" in sys.argv:
        games = verify(games)
    rows = sorted(games.values(), key=lambda g: g["name"].lower())
    with open("steam_singleplayer.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open("steam_singleplayer.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["appid", "name", "released", "url"])
        w.writeheader()
        w.writerows(rows)
    print(f"Done: {len(rows)} single-player-only games saved.")


main()
