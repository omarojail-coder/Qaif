"""Download fixed, auditable public reference inputs; never fetch during simulation."""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path


POWER_PARAMETERS = (
    "T2M", "WS10M", "ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN", "PRECTOTCORR"
)
WEATHER_EPISODES = {
    "red_sea_coast_winter_2024": (24.0, 38.0, "20240101", "20240107"),
    "red_sea_coast_summer_2024": (24.0, 38.0, "20240701", "20240707"),
    "inland_desert_winter_2024": (22.0, 54.0, "20240101", "20240107"),
    "inland_desert_summer_2024": (22.0, 54.0, "20240701", "20240707"),
    "red_sea_coast_rain_2024": (24.0, 38.0, "20240326", "20240401"),
    "inland_desert_rain_2024": (22.0, 54.0, "20240413", "20240419"),
    "red_sea_coast_year_2024": (24.0, 38.0, "20240101", "20241231"),
    "inland_desert_year_2024": (22.0, 54.0, "20240101", "20241231"),
}
TRR_BASE = "https://raw.githubusercontent.com/TRR154/InstationaryGasNetworks/main/GasLib-134"
GASLIB_NETWORK_URL = "https://gaslib.zib.de/download/data/GasLib-134-v2-20211129.net"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_reference_sources(directory: str | Path, *, insecure_gaslib: bool = False,
                            append: bool = False) -> dict:
    """Fetch pinned episodes and exact benchmark files into an empty directory.

    insecure_gaslib is only for hosts lacking a working CA store. It affects a
    single read-only XML download and is recorded in the manifest.
    """
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()) and not append:
        raise FileExistsError(f"source directory is not empty: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "source_manifest.json"
    if append and manifest_path.is_file():
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
        for entry in entries.values():
            path = directory / entry["path"]
            if not path.is_file() or _sha256(path.read_bytes()) != entry["sha256"]:
                raise ValueError(f"existing source is missing or changed: {path}")
    elif append and any(directory.iterdir()):
        raise ValueError("cannot append without a source_manifest.json")
    else:
        entries = {}
    try:
        for name, (latitude, longitude, start, end) in WEATHER_EPISODES.items():
            if name in entries:
                continue
            params = urllib.parse.urlencode({
                "parameters": ",".join(POWER_PARAMETERS), "community": "RE",
                "latitude": latitude, "longitude": longitude, "start": start,
                "end": end, "format": "JSON", "time-standard": "UTC",
            })
            url = "https://power.larc.nasa.gov/api/temporal/hourly/point?" + params
            data = urllib.request.urlopen(url, timeout=90).read()
            payload = json.loads(data)
            if payload.get("messages") or set(POWER_PARAMETERS) - set(payload.get("parameters", {})):
                raise ValueError(f"NASA POWER returned missing parameters or messages for {name}")
            path = directory / f"{name}.json"
            path.write_bytes(data)
            entries[name] = {
                "path": path.name, "url": url, "sha256": _sha256(data),
                "kind": "NASA POWER hourly gridded archive, UTC",
                "latitude": latitude, "longitude": longitude,
                "start": start, "end": end,
            }
        for name, filename in (
            ("trr_boundary", "GasLib-134-sinus-InputData.bcd.gz"),
            ("trr_initial", "GasLib-134-sinus_5000_60-initial.state.gz"),
        ):
            if name in entries:
                continue
            url = f"{TRR_BASE}/{filename}"
            data = urllib.request.urlopen(url, timeout=90).read()
            path = directory / filename
            path.write_bytes(data)
            entries[name] = {
                "path": path.name, "url": url, "sha256": _sha256(data),
                "kind": "TRR154 benchmark, Apache-2.0; not field measurements",
            }
        if "gaslib_network" not in entries:
            context = ssl._create_unverified_context() if insecure_gaslib else None
            data = urllib.request.urlopen(GASLIB_NETWORK_URL, context=context, timeout=90).read()
            path = directory / "GasLib-134-v2-20211129.net"
            path.write_bytes(data)
            entries["gaslib_network"] = {
                "path": path.name, "url": GASLIB_NETWORK_URL, "sha256": _sha256(data),
                "kind": "GasLib-134-v2 network, CC BY 3.0; Greek benchmark",
                "tls_verification_disabled_for_download": insecure_gaslib,
            }
        manifest = {
            "schema_version": "1", "entries": entries,
            "source_notes": [
                "POWER coordinates identify archive grid data, not pipe-side station measurements.",
                "TRR154 transient data are benchmark boundary conditions and an initial state.",
                "GasLib-134 is a Greek network benchmark, not a Saudi pipeline.",
            ],
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return manifest
    except Exception:
        # Leave downloaded files in place for diagnosis; no automatic overwrite.
        raise
