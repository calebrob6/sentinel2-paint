"""
Persistent, append-only palette store.

Keeps exactly one 32x32 thumbnail + metadata per unique quantized (R,G,B).
Designed for long harvests: saves append only the *new* records, so a save is
O(new) not O(total), and resuming never loads patch pixels into RAM.

Files (in a data dir):
  patches.bin   raw uint8, one 32*32*3 = 3072-byte record per unique color
  meta.jsonl    one JSON object per line: {r,g,b,lon,lat,scene,date}
"""

import os
import json
import numpy as np

PATCH = 32
REC = PATCH * PATCH * 3  # 3072 bytes per thumbnail


class Palette:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.bin_path = os.path.join(data_dir, "patches.bin")
        self.meta_path = os.path.join(data_dir, "meta.jsonl")
        self.seen = set()            # packed color keys
        self.n = 0                   # total unique colors on disk + buffered
        self._buf_patches = []       # bytes not yet flushed
        self._buf_meta = []          # str (json lines) not yet flushed
        self._load()

    def _load(self):
        if os.path.exists(self.meta_path):
            with open(self.meta_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    it = json.loads(line)
                    self.seen.add((it["r"] << 16) | (it["g"] << 8) | it["b"])
                    self.n += 1
            print(f"[store] resumed with {self.n} unique colors")

    def __len__(self):
        return self.n

    def add(self, r, g, b, lon, lat, patch, scene, date):
        key = (int(r) << 16) | (int(g) << 8) | int(b)
        if key in self.seen:
            return False
        self.seen.add(key)
        self._buf_patches.append(np.ascontiguousarray(patch, dtype=np.uint8).tobytes())
        self._buf_meta.append(json.dumps({
            "r": int(r), "g": int(g), "b": int(b),
            "lon": round(float(lon), 6), "lat": round(float(lat), 6),
            "scene": scene, "date": date,
        }))
        self.n += 1
        return True

    def save(self):
        if not self._buf_patches:
            return
        with open(self.bin_path, "ab") as f:
            f.write(b"".join(self._buf_patches))
        with open(self.meta_path, "a") as f:
            f.write("\n".join(self._buf_meta) + "\n")
        self._buf_patches.clear()
        self._buf_meta.clear()


def load_all(data_dir):
    """Read a saved palette back for packaging: (patches[N,32,32,3], items[N]).

    Tolerant of being called while a harvest is mid-append: drops a trailing
    malformed line and clamps N to what the .bin file actually holds.
    """
    meta_path = os.path.join(data_dir, "meta.jsonl")
    bin_path = os.path.join(data_dir, "patches.bin")
    items = []
    for l in open(meta_path):
        l = l.strip()
        if not l:
            continue
        try:
            items.append(json.loads(l))
        except json.JSONDecodeError:
            break  # partial trailing line from a concurrent writer
    n_on_disk = os.path.getsize(bin_path) // REC
    n = min(len(items), n_on_disk)
    items = items[:n]
    patches = np.memmap(bin_path, dtype=np.uint8, mode="r",
                        shape=(n, PATCH, PATCH, 3))
    return patches, items
