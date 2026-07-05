"""
Core pipeline for the Sentinel-2 color painter.

Given a Sentinel-2 L2A scene from the Planetary Computer, read its 8-bit RGB
"visual" asset, grid it into non-overlapping 32x32 patches, take the mean color
of each patch, and keep the geolocation + thumbnail for every *unique* mean
(R,G,B) we encounter.

The harvested data is a "palette": a mapping from a quantized (R,G,B) to a real
32x32 Sentinel-2 image chip and the place/time it came from.
"""

import numpy as np
import rasterio
from pyproj import Transformer
import planetary_computer as pc
from pystac_client import Client

PATCH = 32
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# GDAL knobs that make reading remote COGs reliable + reasonably fast.
GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MULTIRANGE="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="1",
    VSI_CACHE="TRUE",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
)


def get_catalog():
    return Client.open(STAC_URL, modifier=pc.sign_inplace)


def search_scenes(catalog, bbox, datetime, max_items=10, cloud_lt=20):
    """Return a list of STAC items, lowest cloud cover first."""
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=datetime,
        query={"eo:cloud_cover": {"lt": cloud_lt}},
        max_items=max_items,
        sortby=[{"field": "eo:cloud_cover", "direction": "asc"}],
    )
    return list(search.items())


def patches_from_visual(href, max_patches=None, max_dim=None):
    """
    Read a signed 'visual' COG href and yield per-patch results.

    Yields tuples: (r, g, b, lon, lat, patch_uint8[32,32,3])
    Only patches with no nodata (black, off-swath) pixels are emitted.

    max_dim: if set, only read the top-left max_dim x max_dim pixels (for fast
             demos). None reads the full tile.
    """
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(href) as ds:
            H, W = ds.height, ds.width
            if max_dim is not None:
                H, W = min(H, max_dim), min(W, max_dim)
            # Crop to a whole number of 32x32 patches.
            nrows, ncols = H // PATCH, W // PATCH
            H, W = nrows * PATCH, ncols * PATCH
            window = rasterio.windows.Window(0, 0, W, H)
            arr = ds.read([1, 2, 3], window=window)  # (3, H, W) uint8
            transform = ds.transform
            to_wgs84 = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)

    # (3, H, W) -> (nrows, ncols, 32, 32, 3). reshape on the transposed view
    # materializes one copy (~360MB for a full tile); we avoid a second copy.
    arr = np.transpose(arr, (1, 2, 0))  # H, W, 3 (view)
    grid = arr.reshape(nrows, PATCH, ncols, PATCH, 3).transpose(0, 2, 1, 3, 4)
    # grid is now a view shaped (nrows, ncols, 32, 32, 3).

    # A patch is valid if it has no fully-black (nodata / off-swath) pixels.
    black = np.all(grid == 0, axis=4)  # (nrows, ncols, 32, 32) bool
    valid = ~black.any(axis=(2, 3))    # (nrows, ncols)

    # Memory-safe mean: reduce with an integer sum (no giant float temporary).
    means = grid.sum(axis=(2, 3), dtype=np.uint32) / (PATCH * PATCH)
    means = np.rint(means).astype(np.uint8)  # (nrows, ncols, 3)

    count = 0
    rr, cc = np.nonzero(valid)
    for pr, pc_ in zip(rr.tolist(), cc.tolist()):
        r, g, b = means[pr, pc_]
        # Center pixel of the patch -> map coords -> lon/lat.
        px = pc_ * PATCH + PATCH / 2.0
        py = pr * PATCH + PATCH / 2.0
        x, y = transform * (px, py)
        lon, lat = to_wgs84.transform(x, y)
        yield int(r), int(g), int(b), float(lon), float(lat), grid[pr, pc_]
        count += 1
        if max_patches is not None and count >= max_patches:
            return
