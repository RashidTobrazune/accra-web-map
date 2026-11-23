"""Turn GeoTIFFs into transparent PNG overlays (Web Mercator) plus matching HTML legends."""

from __future__ import annotations

import html
from dataclasses import dataclass

import matplotlib
import numpy as np
import rasterio
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

WEB_MERCATOR = "EPSG:3857"


@dataclass
class Overlay:
    rgba: np.ndarray                                           # (rows, cols, 4) uint8
    bounds: tuple[tuple[float, float], tuple[float, float]]    # ((south, west), (north, east)) for Leaflet


def hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def to_web_mercator(path: str, categorical: bool) -> tuple[np.ndarray, tuple]:
    """Reproject band 1 to EPSG:3857 (so Leaflet places it exactly). Nodata -> NaN."""
    with rasterio.open(path) as src:
        data = src.read(1).astype("float64")
        if src.nodata is not None and not np.isnan(src.nodata):
            data[data == src.nodata] = np.nan
        transform, width, height = calculate_default_transform(src.crs, WEB_MERCATOR, src.width, src.height,
                                                               *src.bounds)
        out = np.full((height, width), np.nan)
        reproject(data, out, src_transform=src.transform, src_crs=src.crs, dst_transform=transform,
                  dst_crs=WEB_MERCATOR, src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=Resampling.nearest if categorical else Resampling.bilinear)
    w, s, e, n = transform_bounds(WEB_MERCATOR, "EPSG:4326", *array_bounds(height, width, transform))
    return out, ((s, w), (n, e))


def colorize_continuous(arr: np.ndarray, cmap: str, vmin: float, vmax: float, alpha: int = 255) -> np.ndarray:
    norm = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    rgba = (matplotlib.colormaps[cmap](np.nan_to_num(norm)) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(arr), alpha, 0)
    return rgba


def colorize_categorical(arr: np.ndarray, classes: dict[int, tuple[str, str]], alpha: int = 255) -> np.ndarray:
    """Classes not listed (and NaN / 0) become fully transparent."""
    rgba = np.zeros(arr.shape + (4,), dtype="uint8")
    for code, (_, color) in classes.items():
        rgba[arr == code] = hex_to_rgba(color, alpha)
    return rgba


def colorize_binned(arr: np.ndarray, breaks: list[float], colors: list[str], alpha: int = 255) -> np.ndarray:
    """Bin 1 = value <= breaks[0], ..., last bin = value > breaks[-1]. Infinite values go in the last bin."""
    if len(colors) != len(breaks) + 1:
        raise ValueError("binned layers need len(colors) == len(breaks) + 1")
    rgba = np.zeros(arr.shape + (4,), dtype="uint8")
    valid = ~np.isnan(arr)
    idx = np.digitize(np.where(valid, arr, 0), breaks, right=True)
    for i, color in enumerate(colors):
        rgba[valid & (idx == i)] = hex_to_rgba(color, alpha)
    return rgba


# --- legends ---------------------------------------------------------------

def _swatch(color: str, label: str) -> str:
    return (f'<div class="lg-row"><span class="lg-sw" style="background:{color}"></span>'
            f"{html.escape(label)}</div>")


def legend_categorical(title: str, classes: dict[int, tuple[str, str]], note: str = "") -> str:
    rows = "".join(_swatch(c, n) for n, c in classes.values())
    return _legend_block(title, rows, note)


def legend_binned(title: str, breaks: list[float], colors: list[str], unit: str, note: str = "") -> str:
    edges = [0, *breaks]
    labels = [f"{a:g}–{b:g} {unit}" for a, b in zip(edges[:-1], edges[1:])] + [f"> {breaks[-1]:g} {unit}"]
    return _legend_block(title, "".join(_swatch(c, lab) for c, lab in zip(colors, labels)), note)


def legend_continuous(title: str, cmap: str, vmin: float, vmax: float, unit: str, note: str = "") -> str:
    cm = matplotlib.colormaps[cmap]
    stops = ", ".join(matplotlib.colors.to_hex(cm(x)) for x in np.linspace(0, 1, 7))
    bar = (f'<div class="lg-grad" style="background:linear-gradient(to right, {stops})"></div>'
           f'<div class="lg-scale"><span>≤ {vmin:g} {unit}</span><span>≥ {vmax:g} {unit}</span></div>')
    return _legend_block(title, bar, note)


def _legend_block(title: str, body: str, note: str) -> str:
    note_html = f'<div class="lg-note">{html.escape(note)}</div>' if note else ""
    return f'<div class="lg-block"><div class="lg-title">{html.escape(title)}</div>{body}{note_html}</div>'


def build_overlay(layer: dict, opacity_alpha: int = 255) -> tuple[Overlay, str]:
    """Render one configured layer to an Overlay and its legend HTML."""
    kind = layer["kind"]
    arr, bounds = to_web_mercator(layer["source"], categorical=kind in ("categorical", "binned"))
    note = layer.get("note", "")
    if kind == "continuous":
        rgba = colorize_continuous(arr, layer["cmap"], layer["vmin"], layer["vmax"], opacity_alpha)
        legend = legend_continuous(layer["name"], layer["cmap"], layer["vmin"], layer["vmax"], layer.get("unit", ""),
                                   note)
    elif kind == "categorical":
        classes = {int(k): tuple(v) for k, v in layer["classes"].items()}
        rgba = colorize_categorical(arr, classes, opacity_alpha)
        legend = legend_categorical(layer["name"], classes, note)
    elif kind == "binned":
        rgba = colorize_binned(arr, layer["breaks"], layer["colors"], opacity_alpha)
        legend = legend_binned(layer["name"], layer["breaks"], layer["colors"], layer.get("unit", ""), note)
    else:
        raise ValueError(f"unknown layer kind: {kind}")
    return Overlay(rgba, bounds), legend
