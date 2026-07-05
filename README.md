# s2-paint — Paint with Sentinel-2

**Jump to: [Live site](https://calebrob.com/static/s2-paint/) | [Quick start](#quick-start) | [How it works](#how-it-works) | [The app](#the-app) | [Scripts](#scripts) | [Repo layout](#repo-layout) | [Citation](#citation)**

Search the Sentinel-2 archive for 32×32 image patches whose **mean color** covers as much of the RGB gamut as possible, then **paint** with real satellite imagery: pick a color and every brush tile becomes the actual 32×32 chip of Earth whose average color is closest — and you can trace each tile back to the exact place it came from on the globe. A harvest of ~370 curated + random Sentinel-2 scenes yields ~93k unique Earth colors, each backed by a georeferenced thumbnail. **Live demo: [calebrob.com/static/s2-paint](https://calebrob.com/static/s2-paint/).**

<p align="center">
  <img src="images/s2-paint.png" width="49%" alt="Canvas view: the NASA logo rebuilt from thousands of Sentinel-2 patches">
  <img src="images/pallete-view.png" width="49%" alt="Map view: where on Earth each palette color was sampled from">
</p>

**Figure 1.** The single-page [webapp](https://calebrob.com/static/s2-paint/). (**Left**) *Canvas* view — the NASA logo re-created entirely from real Sentinel-2 patches, nearest-color per cell; the panel traces the tile under the cursor back to its source scene and lat/lon. (**Right**) *Map* view — a Leaflet globe (Esri World Imagery) showing where each palette color was actually observed; picking a color flies to the exact place Sentinel-2 saw it. The reachable gamut (bright zones in the picker) is exactly what Sentinel-2 actually contains, and any pick snaps to the nearest real Earth patch.

## Quick start

```bash
git clone https://github.com/calebrob6/s2-paint.git
cd s2-paint
pip install -r requirements.txt

# 1. tiny end-to-end demo (~2 windowed scenes) -> data_demo/
python demo.py

# 2. pack the demo palette into the web app -> web/
python build_web.py data_demo

# 3. serve it
cd web && python -m http.server 8745   # open http://localhost:8745
```

The demo reads only a 1024×1024 corner of two scenes, so it finishes in a few seconds and produces a small palette. For a full palette, run the exhaustive harvest below.

## How it works

1. **Sample** Sentinel-2 L2A scenes from the Microsoft Planetary Computer — a curated set of color-rich places/seasons (salt-evaporation ponds, tulip fields, deserts, glaciers, coral lagoons, autumn foliage, geothermal pools, red mine tailings…) plus random global land sampling for the long tail.
2. **Download** each scene's 8-bit RGB `visual` COG.
3. **Grid** it into non-overlapping 32×32 patches (~117k per full 10980×10980 tile).
4. **Mean** each patch → quantized (R,G,B). Keep one thumbnail + geolocation per *unique* color (off-swath/nodata patches are dropped).
5. **Pack** the palette into sprite-atlas JPEGs + a compact index, and serve a single-page app that does nearest-color lookup to paint with real Earth.

The store is append-only, so a harvest can run for hours and be resumed at any time. Each unique color costs 3072 bytes on disk (`patches.bin`); metadata is one JSON line per color (`meta.jsonl`). You can rebuild `web/` and refresh the app at any time to watch the palette grow.

## The app

The webapp ([`web/index.html`](web/index.html)) is a single static HTML file — a **shared pigment picker** (saturation/value square + hue slider + R/G/B/hex) driving two tabs. The picker only allows colors Sentinel-2 actually contains: regions of the gamut with no real imagery are **dimmed**, and any pick **snaps** to the nearest real Earth patch (the snap ΔRGB is shown).

- **◍ Map tab** — a Leaflet globe over Esri World Imagery. Picking a color flies to the exact place Sentinel-2 saw it and drops a highlighted pin; a colored ambient field samples the whole palette across the planet (click any point to grab that color).
- **▦ Canvas tab** — paint with real satellite chips: **Brush / Erase / Eyedrop / Fill**, adjustable grid, random mosaic, PNG export. Every distinct painted tile pins its origin on the globe; hovering a tile traces it back to Earth.
  - **Image → mosaic**: upload any image (or click a built-in example) and it is re-created entirely from available Sentinel-2 patches (nearest-color per cell; adjustable detail, with an async progress bar). A **Random** slider picks at random among patches within a bounded ΔRGB of the best match — breaking up repeated chips in flat areas — and **Re-roll** re-shuffles without re-uploading.

## Scripts

### `harvest.py`

Exhaustive, resumable harvest: every curated color-rich target first, then endless random continental-land sampling to fill the long tail. Appends new unique colors to a `Palette` in `--data-dir`.

```bash
python harvest.py --data-dir data --minutes 360 --scenes 2000
```

| Flag | Description |
| --- | --- |
| `--data-dir` | Palette directory to append to (created if missing). Default `data`. |
| `--minutes` | Wall-clock budget before stopping. Default `720`. |
| `--scenes` | Max number of scenes to process. Default `100000`. |
| `--seed` | RNG seed for the random-sampling queue. Default `1`. |
| `--save-every` | Flush the store to disk every N scenes. Default `5`. |

### `build_web.py`

Packs a harvested palette into web assets: sprite-atlas JPEGs (`web/atlas_*.jpg`, 64 patches per row) plus a compact `web/colors.json` index (color → atlas coords + lon/lat + source scene).

```bash
python build_web.py data            # pack the full palette -> web/
python build_web.py data 80000      # cap to ~80k colors for browser performance
```

The optional second argument caps the palette via a **coverage-maximizing** downsample: it quantizes RGB at increasing resolution and keeps one color per occupied cell, so the colors most spread across the gamut survive (rare vivid colors are kept instead of being out-voted by dense regions).

### `demo.py`

Small end-to-end run (two windowed scenes → `data_demo/`) that exercises the full pipeline before committing to a long harvest. See [Quick start](#quick-start).

## Repo layout

```
s2colors.py        core pipeline: STAC search, read visual COG, grid -> mean -> geo
store.py           append-only palette store (patches.bin + meta.jsonl)
demo.py            small end-to-end run (2 windowed scenes) -> data_demo/
harvest.py         exhaustive search: curated + random scenes -> data/
build_web.py       pack a palette into web/atlas_*.jpg + web/colors.json
web/index.html     the single-page painting app (Leaflet globe + RGB picker)
web/examples/      built-in example images for the "image -> mosaic" feature
images/            figures embedded in this README
```

`data/`, `data_demo/`, and the built `web/atlas_*.jpg` + `web/colors.json` are gitignored — regenerate them locally with `harvest.py` / `demo.py` and `build_web.py`. The hosted [live site](https://calebrob.com/static/s2-paint/) is served from a pre-built palette.

## Citation

If you use this repo, please cite it:

```bibtex
@misc{robinson2026s2paint,
  author       = {Robinson, Caleb},
  title        = {{s2-paint}: paint with {Sentinel-2}},
  year         = {2026},
  howpublished = {\url{https://github.com/calebrob6/s2-paint}}
}
```

## License

MIT. See [`LICENSE`](LICENSE).
