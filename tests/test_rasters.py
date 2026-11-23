import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from accra_webmap.rasters import (
    build_overlay,
    colorize_binned,
    colorize_categorical,
    colorize_continuous,
    hex_to_rgba,
    legend_binned,
    legend_categorical,
    legend_continuous,
)


def test_hex_to_rgba():
    assert hex_to_rgba("#ff8000") == (255, 128, 0, 255)
    assert hex_to_rgba("00ff00", 100) == (0, 255, 0, 100)


def test_colorize_continuous_transparent_nodata_and_clipping():
    arr = np.array([[np.nan, 0.0, 50.0, 100.0]])
    rgba = colorize_continuous(arr, "Greys", 0, 10, alpha=200)
    assert rgba[0, 0, 3] == 0
    assert (rgba[0, 1:, 3] == 200).all()
    assert (rgba[0, 2, :3] == rgba[0, 3, :3]).all()  # both clipped to vmax


def test_colorize_categorical_unlisted_is_transparent():
    arr = np.array([[0, 1, 2, np.nan]])
    rgba = colorize_categorical(arr, {1: ("A", "#ff0000")})
    assert tuple(rgba[0, 1]) == (255, 0, 0, 255)
    assert rgba[0, 0, 3] == 0 and rgba[0, 2, 3] == 0 and rgba[0, 3, 3] == 0


def test_colorize_binned_edges_and_infinity():
    arr = np.array([[5, 15, 16, 30, 45, 61, np.inf, np.nan]], dtype=float)
    cols = ["#000001", "#000002", "#000003", "#000004"]
    rgba = colorize_binned(arr, [15, 30, 60], cols)
    blue = rgba[0, :, 2].tolist()
    assert blue[:7] == [1, 1, 2, 2, 3, 4, 4]
    assert rgba[0, 7, 3] == 0
    with pytest.raises(ValueError):
        colorize_binned(arr, [15, 30], cols)


def test_legends_escape_and_label():
    assert "&lt;b&gt;" in legend_categorical("<b>", {1: ("x", "#000000")})
    lb = legend_binned("T", [15, 30], ["#1", "#2", "#3"], "min")
    assert "0–15 min" in lb and "&gt; 30 min" in lb
    assert "linear-gradient" in legend_continuous("LST", "YlOrRd", 30, 40, "°C")


def test_build_overlay_reprojects_and_bounds(tmp_path):
    path = tmp_path / "t.tif"
    data = np.array([[1, 2], [3, 0]], dtype="uint8")
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(-0.2, 5.7, 0.01, 0.01), nodata=0) as dst:
        dst.write(data, 1)
    layer = {"name": "x", "source": str(path), "kind": "categorical",
             "classes": {1: ["a", "#ff0000"], 2: ["b", "#00ff00"], 3: ["c", "#0000ff"]}}
    ov, legend = build_overlay(layer)
    (s, w), (n, e) = ov.bounds
    assert w == pytest.approx(-0.2, abs=1e-3) and e == pytest.approx(-0.18, abs=1e-3)
    assert s == pytest.approx(5.68, abs=1e-3) and n == pytest.approx(5.70, abs=1e-3)
    assert ov.rgba.shape[2] == 4 and (ov.rgba[..., 3] > 0).any()
    assert "a" in legend
