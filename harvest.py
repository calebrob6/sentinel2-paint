"""
Exhaustive harvest: sample many Sentinel-2 scenes and accumulate as many unique
mean-(R,G,B) 32x32 patches as possible.

Strategy for maximum color diversity:
  1. CURATED targets — places/seasons engineered for vivid, rare colors:
     salt-evaporation ponds (pink/orange/green), tulip fields, deserts, ice,
     coral lagoons, autumn foliage, geothermal pools, red mine tailings...
  2. RANDOM land sampling — random points inside continental land boxes across
     random months/years, to fill in the long tail of natural colors.

Runs incrementally and resumably: append-only to a Palette in --data-dir.
Each scene's full 10980x10980 visual asset is gridded (=> ~117k patches/scene).

Usage:
  python harvest.py --data-dir data --minutes 600
  python harvest.py --data-dir data --scenes 400
"""

import argparse
import random
import time
import traceback

from s2colors import get_catalog, search_scenes, patches_from_visual
from store import Palette

# --- 1. Curated, color-rich targets: (name, [W,S,E,N], "start/end", cloud_lt) ---
CURATED = [
    # Salt-evaporation ponds — the richest artificial colors on Earth
    ("SF Bay salt ponds",      [-122.15, 37.45, -122.0, 37.55], "2023-07-01/2023-10-15", 8),
    ("Great Salt Lake (pink)", [-112.7, 41.0, -112.2, 41.5],    "2023-07-01/2023-09-30", 10),
    ("Owens Lake dust ponds",  [-118.0, 36.3, -117.8, 36.5],    "2023-06-01/2023-09-30", 8),
    ("Sečovlje salt pans",     [13.58, 45.48, 13.66, 45.53],    "2023-06-01/2023-09-15", 10),
    ("Aigues-Mortes salt",     [4.15, 43.5, 4.25, 43.58],       "2023-06-01/2023-09-15", 10),
    # Deserts & dunes — oranges, reds, ochres
    ("Namib dunes",            [15.0, -25.0, 15.6, -24.5],      "2023-05-01/2023-09-30", 5),
    ("Sahara erg",             [8.0, 26.5, 9.0, 27.5],          "2023-04-01/2023-09-30", 5),
    ("Australian outback red", [133.0, -25.5, 134.0, -24.5],    "2023-05-01/2023-10-30", 8),
    ("Grand Canyon",           [-112.3, 36.0, -112.0, 36.3],    "2023-06-01/2023-10-15", 8),
    # Salt flats — bright whites
    ("Salar de Uyuni",         [-67.8, -20.5, -67.3, -20.0],    "2023-07-01/2023-10-30", 5),
    ("Bonneville flats",       [-114.0, 40.7, -113.7, 41.0],    "2023-06-01/2023-09-30", 8),
    # Ice & glaciers — whites, blues
    ("Greenland margin",       [-50.0, 66.5, -49.0, 67.0],      "2023-06-15/2023-08-31", 20),
    ("Iceland glaciers",       [-18.0, 64.0, -17.0, 64.5],      "2023-06-15/2023-09-15", 25),
    # Tropical shallows — turquoise/cyan
    ("Bahama banks",           [-78.5, 23.5, -77.5, 24.5],      "2023-04-01/2023-09-30", 8),
    ("Great Barrier Reef",     [146.0, -19.0, 147.0, -18.0],    "2023-06-01/2023-11-30", 10),
    ("Maldives atolls",        [73.0, 3.5, 73.5, 4.5],          "2023-01-01/2023-04-30", 12),
    # Vivid vegetation & farming
    ("Netherlands tulips",     [4.5, 52.2, 4.7, 52.45],         "2023-04-10/2023-05-05", 15),
    ("US Midwest crops",       [-94.0, 41.5, -93.0, 42.5],      "2023-06-15/2023-09-15", 10),
    ("Amazon canopy",          [-62.0, -4.0, -61.0, -3.0],      "2023-06-01/2023-09-30", 15),
    ("New England autumn",     [-72.5, 43.5, -71.5, 44.5],      "2023-10-01/2023-10-25", 15),
    ("Siberian larch autumn",  [100.0, 60.0, 101.5, 61.0],      "2023-09-10/2023-10-05", 20),
    # Geothermal / volcanic / mineral — yellows, oranges, blacks, reds
    ("Yellowstone springs",    [-110.9, 44.4, -110.7, 44.6],    "2023-07-01/2023-09-30", 8),
    ("Dallol Ethiopia",        [40.25, 14.2, 40.35, 14.3],      "2023-01-01/2023-12-31", 10),
    ("Rio Tinto red river",    [-6.7, 37.6, -6.5, 37.8],        "2023-05-01/2023-09-30", 8),
    ("Kilauea lava fields",    [-155.3, 19.3, -155.0, 19.5],    "2023-01-01/2023-09-30", 12),
    ("Lake Natron red",        [36.0, -2.5, 36.2, -2.3],        "2023-06-01/2023-11-30", 10),
    # Cities — grays & built materials
    ("Dubai urban",            [55.1, 25.0, 55.4, 25.3],        "2023-05-01/2023-09-30", 5),
    ("Tokyo urban",            [139.6, 35.5, 139.9, 35.8],      "2023-10-01/2023-12-15", 10),
]

# --- 2. Continental land boxes for random sampling (W,S,E,N) ---
LAND_BOXES = [
    [-120, 32, -75, 49],    # CONUS
    [-110, 18, -88, 31],    # Mexico
    [-72, -38, -45, -10],   # S. America (Andes/Brazil)
    [-10, 36, 28, 60],      # Europe
    [-12, 8, 35, 33],       # N/W Africa + Sahel
    [22, -34, 48, 5],       # E/S Africa
    [68, 8, 90, 33],        # India
    [95, 20, 125, 45],      # E. Asia
    [113, -38, 150, -18],   # Australia
    [60, 45, 100, 62],      # Central Asia / Siberia steppe
]
YEARS = ["2021", "2022", "2023", "2024"]
SEASON = ["01-01/02-28", "03-01/04-30", "05-01/06-30",
          "07-01/08-31", "09-01/10-31", "11-01/12-31"]


def random_target(rng):
    box = rng.choice(LAND_BOXES)
    w, s, e, n = box
    # ~0.25 deg window (well inside a single S2 tile)
    lon = rng.uniform(w, e - 0.25)
    lat = rng.uniform(s, n - 0.25)
    bbox = [lon, lat, lon + 0.2, lat + 0.2]
    yr = rng.choice(YEARS)
    sea = rng.choice(SEASON)
    dt = f"{yr}-{sea.split('/')[0]}/{yr}-{sea.split('/')[1]}"
    cloud = rng.choice([5, 10, 20, 35])  # some cloud => whites/grays too
    return (f"random {lat:.1f},{lon:.1f}", bbox, dt, cloud)


def process_scene(pal, item, log):
    date = item.properties["datetime"][:10]
    added = 0
    try:
        for r, g, b, lon, lat, patch in patches_from_visual(item.assets["visual"].href):
            if pal.add(r, g, b, lon, lat, patch, item.id, date):
                added += 1
    except Exception as e:
        log(f"    ! read failed: {e}")
        return 0
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--minutes", type=float, default=720)
    ap.add_argument("--scenes", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--save-every", type=int, default=5)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    cat = get_catalog()
    pal = Palette(args.data_dir)

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

    # Build a work queue: every curated target first, then endless random ones.
    queue = list(CURATED)
    rng.shuffle(queue)

    t0 = time.time()
    deadline = t0 + args.minutes * 60
    n_scenes = 0
    last_unique = len(pal)

    while time.time() < deadline and n_scenes < args.scenes:
        if queue:
            name, bbox, dt, cloud = queue.pop(0)
        else:
            name, bbox, dt, cloud = random_target(rng)
        try:
            items = search_scenes(cat, bbox, dt, max_items=2, cloud_lt=cloud)
        except Exception as e:
            log(f"search failed for {name}: {e}")
            continue
        if not items:
            continue
        for it in items:
            if time.time() >= deadline:
                break
            n_scenes += 1
            added = process_scene(pal, it, log)
            elapsed = time.time() - t0
            log(f"#{n_scenes:<4} {name[:26]:26} +{added:<6} unique={len(pal):<7} "
                f"({len(pal)/max(1,elapsed)*60:.0f}/min) {it.id}")
            if n_scenes % args.save_every == 0:
                pal.save()
                log(f"    saved ({len(pal)} unique, +{len(pal)-last_unique} since last save)")
                last_unique = len(pal)

    pal.save()
    log(f"DONE: {n_scenes} scenes, {len(pal)} unique colors in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
