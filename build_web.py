"""
Pack a harvested palette (patches.npy + meta.json) into web assets:

  web/atlas_000.png ...   sprite sheets, 64 patches per row, 32px cells
  web/colors.json         compact index: colors, atlas coords, geo + scene refs

Usage:  python build_web.py <data_dir>   (default: data_demo)
"""

import os
import sys
import json
import numpy as np
from PIL import Image
from store import load_all

PATCH = 32
ATLAS_COLS = 64                 # patches per atlas row  -> 2048px wide
ROWS_PER_PAGE = 256             # 256*32 = 8192px tall pages
PER_PAGE = ATLAS_COLS * ROWS_PER_PAGE


def select_diverse(colors, limit):
    """Pick <=limit indices that MAXIMIZE color-space coverage (not density).

    Quantize RGB at resolution Q and keep one color per occupied cell. Finer Q =>
    more distinct cells. Pick the largest Q whose distinct-cell count still fits
    the budget, so the kept colors are spread as widely across the gamut as the
    budget allows (rare vivid colors survive instead of being out-voted)."""
    rgb = np.array([[c["r"], c["g"], c["b"]] for c in colors], dtype=np.int32)
    best_keys, best_Q = None, 0
    for Q in [16, 24, 32, 48, 64, 80, 96, 112, 128, 144, 160, 192, 224, 256]:
        keys = ((rgb * Q) // 256).clip(0, Q - 1)
        flat = (keys[:, 0] * Q + keys[:, 1]) * Q + keys[:, 2]
        _, first = np.unique(flat, return_index=True)
        if len(first) <= limit:
            best_keys, best_Q = first, Q
        else:
            break
    if best_keys is None:           # even coarsest exceeds limit; just truncate
        best_keys = np.arange(limit)
    idx = np.sort(best_keys)
    print(f"[build] coverage-max select: {len(idx)} colors at Q={best_Q}")
    return idx


def build(data_dir, out_dir="web", limit=None):
    patches, items = load_all(data_dir)       # memmap (N,32,32,3), list[dict]
    if limit and len(items) > limit:
        idx = select_diverse(items, limit)
        patches = patches[idx]
        items = [items[i] for i in idx]
    n = len(items)
    os.makedirs(out_dir, exist_ok=True)

    # Dedupe scene+date strings into a table to keep colors.json small.
    scene_tab, scene_idx = [], {}
    def scene_ref(scene, date):
        key = (scene, date)
        if key not in scene_idx:
            scene_idx[key] = len(scene_tab)
            scene_tab.append([scene, date])
        return scene_idx[key]

    pages = []
    n_pages = (n + PER_PAGE - 1) // PER_PAGE
    for p in range(n_pages):
        start = p * PER_PAGE
        end = min(start + PER_PAGE, n)
        rows = (end - start + ATLAS_COLS - 1) // ATLAS_COLS
        atlas = np.zeros((rows * PATCH, ATLAS_COLS * PATCH, 3), dtype=np.uint8)
        for i in range(start, end):
            local = i - start
            ry, cx = local // ATLAS_COLS, local % ATLAS_COLS
            atlas[ry*PATCH:(ry+1)*PATCH, cx*PATCH:(cx+1)*PATCH] = patches[i]
        # JPEG (quality 90, no chroma subsampling) — ~6x smaller than PNG for these
        # photographic patches; matching is unaffected (uses exact colors.json values).
        fname = f"atlas_{p:03d}.jpg"
        Image.fromarray(atlas).save(os.path.join(out_dir, fname), quality=90, subsampling=0)
        pages.append(fname)
        print(f"[build] {fname}  {ATLAS_COLS*PATCH}x{rows*PATCH}  ({end-start} patches)")

    colors = []
    for i, it in enumerate(items):
        colors.append([
            it["r"], it["g"], it["b"],
            i // PER_PAGE, i % PER_PAGE,
            it["lon"], it["lat"],
            scene_ref(it["scene"], it["date"]),
        ])

    out = {
        "patch": PATCH,
        "atlas_cols": ATLAS_COLS,
        "per_page": PER_PAGE,
        "pages": pages,
        "scenes": scene_tab,
        # [r, g, b, page, idx_in_page, lon, lat, scene_ref]
        "colors": colors,
    }
    json.dump(out, open(os.path.join(out_dir, "colors.json"), "w"))
    print(f"[build] colors.json  {n} unique colors, {len(scene_tab)} scenes -> {out_dir}/")


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data_demo"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    build(data_dir, limit=limit)
