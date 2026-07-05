"""
Small end-to-end demo: process a couple of scenes (windowed for speed),
accumulate unique colors, and report. Proves the full pipeline before the
exhaustive harvest.
"""

import time
from s2colors import get_catalog, search_scenes, patches_from_visual
from store import Palette


def run():
    cat = get_catalog()
    # A few visually diverse spots so the demo palette isn't monochrome.
    targets = [
        ("San Francisco Bay", [-122.55, 37.65, -122.25, 37.85], "2023-07-01/2023-09-30"),
        ("Sahara / Nile delta", [30.8, 30.8, 31.1, 31.1], "2023-06-01/2023-08-31"),
    ]
    pal = Palette("data_demo")
    t0 = time.time()
    for name, bbox, dt in targets:
        items = search_scenes(cat, bbox, dt, max_items=1, cloud_lt=10)
        if not items:
            print(f"[demo] no scenes for {name}")
            continue
        it = items[0]
        date = it.properties["datetime"][:10]
        print(f"[demo] {name}: {it.id} ({date}) cloud={it.properties.get('eo:cloud_cover'):.1f}")
        added = 0
        # Read only a 1024x1024 corner for the demo => fast.
        for r, g, b, lon, lat, patch in patches_from_visual(
            it.assets["visual"].href, max_dim=1024
        ):
            if pal.add(r, g, b, lon, lat, patch, it.id, date):
                added += 1
        print(f"[demo]   +{added} new unique colors (total {len(pal)})")
    pal.save()
    print(f"[demo] done in {time.time()-t0:.1f}s, {len(pal)} unique colors -> data_demo/")


if __name__ == "__main__":
    run()
