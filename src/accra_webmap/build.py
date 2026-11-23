"""Assemble the Leaflet map (via folium) into one self-contained HTML file."""

from __future__ import annotations

import argparse
import html
import json
import logging
from pathlib import Path

import folium
import yaml
from folium.plugins import Fullscreen

from .rasters import build_overlay

log = logging.getLogger("accra_webmap")

CSS = """
<style>
  .panel { position: fixed; z-index: 1000; background: rgba(255,255,255,0.95); border-radius: 6px;
           box-shadow: 0 1px 6px rgba(0,0,0,0.25); font: 13px/1.35 system-ui, -apple-system, Segoe UI, sans-serif;
           color: #222; }
  #title-box { top: 10px; left: 56px; padding: 8px 12px; max-width: 420px; }
  #title-box h1 { font-size: 15px; margin: 0 0 2px 0; }
  #title-box p { margin: 0; color: #555; font-size: 12px; }
  #legend-box { bottom: 64px; left: 10px; padding: 8px 10px; max-width: 280px; max-height: 60vh; overflow-y: auto; }
  .lg-block + .lg-block { margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e5e5; }
  .lg-title { font-weight: 600; margin-bottom: 4px; }
  .lg-row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
  .lg-sw { width: 14px; height: 14px; border: 1px solid #999; border-radius: 2px; flex: none; }
  .lg-grad { height: 12px; border: 1px solid #999; border-radius: 2px; }
  .lg-scale { display: flex; justify-content: space-between; font-size: 11px; color: #555; }
  .lg-note { font-size: 11px; color: #666; margin-top: 3px; }
  .lg-empty { color: #666; font-style: italic; }
</style>
"""


def _facilities_layer(cfg: dict, base_dir: Path) -> folium.FeatureGroup:
    fc = cfg["facilities"]
    data = json.loads((base_dir / fc["source"]).read_text(encoding="utf-8"))
    group = folium.FeatureGroup(name=fc["name"], show=True)
    for feat in data["features"]:
        lon, lat = feat["geometry"]["coordinates"][:2]
        p = feat.get("properties", {})
        hosp = bool(p.get("is_hospital"))
        kind = p.get("amenity") or p.get("healthcare") or "health facility"
        name = p.get("name") or "(unnamed)"
        popup = f"<b>{html.escape(str(name))}</b><br>{html.escape(str(kind)).capitalize()}"
        folium.CircleMarker(
            location=[lat, lon], radius=6 if hosp else 4, weight=1, color="white",
            fill=True, fill_opacity=0.95, fill_color=fc["hospital_color"] if hosp else fc["other_color"],
            popup=folium.Popup(popup, max_width=250), tooltip=html.escape(str(name)),
        ).add_to(group)
    return group, {"hospital": fc["hospital_color"], "other": fc["other_color"], "n": len(data["features"])}


def build(config_path: str) -> Path:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    base_dir = Path(config_path).resolve().parent
    alpha = int(round(255 * float(cfg.get("opacity", 0.75))))

    m = folium.Map(location=cfg["center"], zoom_start=cfg["zoom"], tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, HERE, Garmin, © OpenStreetMap contributors", name="Light basemap", max_zoom=16,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, Maxar, Earthstar Geographics", name="Satellite imagery", show=False,
    ).add_to(m)

    legends: dict[str, str] = {}
    active: list[str] = []
    for layer in cfg["layers"]:
        layer = dict(layer, source=str(base_dir / layer["source"]))
        log.info("Rendering %s", layer["name"])
        ov, legend = build_overlay(layer, alpha)
        show = bool(layer.get("show", False))
        folium.raster_layers.ImageOverlay(
            image=ov.rgba, bounds=[list(ov.bounds[0]), list(ov.bounds[1])], name=layer["name"],
            show=show, mercator_project=False, origin="upper", interactive=False, zindex=2,
        ).add_to(m)
        legends[layer["name"]] = legend
        if show:
            active.append(layer["name"])

    fac_group, fac_style = _facilities_layer(cfg, base_dir)
    fac_group.add_to(m)
    fname = cfg["facilities"]["name"]
    legends[fname] = (
        f'<div class="lg-block"><div class="lg-title">{html.escape(fname)}</div>'
        f'<div class="lg-row"><span class="lg-sw" style="background:{fac_style["hospital"]};border-radius:50%"></span>Hospital</div>'
        f'<div class="lg-row"><span class="lg-sw" style="background:{fac_style["other"]};border-radius:50%"></span>'
        f'Clinic / health centre / doctor</div><div class="lg-note">{fac_style["n"]} facilities · click a point for its name</div></div>'
    )
    active.append(fname)

    folium.LayerControl(collapsed=False, position="topright").add_to(m)
    Fullscreen(position="topleft").add_to(m)

    root = m.get_root()
    root.header.add_child(folium.Element(CSS))
    root.html.add_child(folium.Element(
        f'<div id="title-box" class="panel"><h1>{html.escape(cfg["title"])}</h1>'
        "<p>Toggle layers on the right · legend updates automatically · click facilities for details</p></div>"
        '<div id="legend-box" class="panel"></div>'
    ))
    # Run after the page has loaded: folium defines the map object later in the same script block.
    root.script.add_child(folium.Element(f"""
      window.addEventListener('load', function() {{
        var legends = {json.dumps(legends)};
        var order = {json.dumps(list(legends))};
        var active = {json.dumps(active)};
        var box = document.getElementById('legend-box');
        function render() {{
          var shown = order.filter(function(n) {{ return active.indexOf(n) !== -1; }});
          box.innerHTML = shown.length ? shown.map(function(n) {{ return legends[n]; }}).join('')
                                       : '<div class="lg-empty">Turn on a layer to see its legend</div>';
        }}
        {m.get_name()}.on('overlayadd', function(e) {{ if (active.indexOf(e.name) === -1) active.push(e.name); render(); }});
        {m.get_name()}.on('overlayremove', function(e) {{ active = active.filter(function(n) {{ return n !== e.name; }}); render(); }});
        render();
      }});
    """))

    out = base_dir / cfg["output"]
    out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out))
    log.info("Wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Build the Accra interactive web map")
    p.add_argument("--config", default="config.yaml")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    build(args.config)


if __name__ == "__main__":
    main()
