#!/usr/bin/env python3
"""
Lake County AirBio — daily data fetcher.

Pulls REAL weather (temperature, humidity, wind, rainfall) and REAL air-quality
(US AQI) for every Lake County, IL municipality plotted on the map, using the
free, keyless Open-Meteo API:

  - Weather:      https://open-meteo.com/en/docs            (no API key needed)
  - Air quality:  https://open-meteo.com/en/docs/air-quality-api

Open-Meteo blends national weather-service models (NOAA/NWS for the US) rather
than being a primary government source itself, which is why this script is the
"intended full-feed" swap described in the site's About page: if you later get
a free EPA AirNow API key (https://docs.airnowapi.org/), swap fetch_aqi() to
call it instead — the JSON shape below is what index.html expects either way.

Pollen and mold are NOT available from any free, keyless public API, so they
stay MODELED here — computed from real humidity/temperature/rainfall using a
simple, documented heuristic (see model_pollen_and_mold below). They are
labeled "modeled" in the output JSON so the frontend can be honest about it.

Usage:
    python scripts/fetch_data.py            # writes ./data.json
    python scripts/fetch_data.py --out X     # writes to X instead

Runs on a schedule via .github/workflows/update-data.yml — see that file and
README.md for the GitHub Actions setup.
"""
import argparse
import datetime
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
HISTORY_DAYS = 7  # today + 6 preceding days

# Lake County, IL municipalities plotted on the map, with approximate
# municipal-center coordinates. Add or remove entries here to change the map —
# index.html reads whatever city list is present in data.json.
CITIES = {
    "Antioch": (42.4753, -88.0967),
    "Bannockburn": (42.1994, -87.8534),
    "Barrington": (42.1544, -88.1339),
    "Beach Park": (42.4128, -87.8595),
    "Buffalo Grove": (42.1667, -87.9598),
    "Deerfield": (42.1711, -87.8445),
    "Deer Park": (42.1725, -88.0759),
    "Fox Lake": (42.3925, -88.1809),
    "Grayslake": (42.3453, -88.0334),
    "Green Oaks": (42.2967, -87.9298),
    "Gurnee": (42.3706, -87.9020),
    "Hainesville": (42.3306, -88.0475),
    "Hawthorn Woods": (42.2381, -88.0928),
    "Highland Park": (42.1817, -87.8003),
    "Highwood": (42.1961, -87.8087),
    "Island Lake": (42.2892, -88.1856),
    "Kildeer": (42.1898, -88.0470),
    "Lake Barrington": (42.2144, -88.1289),
    "Lake Bluff": (42.2717, -87.8334),
    "Lake Forest": (42.2411, -87.8406),
    "Lake Villa": (42.4142, -88.0717),
    "Lake Zurich": (42.1961, -88.0934),
    "Libertyville": (42.2839, -87.9548),
    "Lincolnshire": (42.1994, -87.9098),
    "Lindenhurst": (42.4267, -88.0184),
    "Long Grove": (42.1972, -88.0128),
    "Mettawa": (42.2350, -87.9276),
    "Mundelein": (42.2726, -88.0021),
    "North Barrington": (42.2211, -88.1206),
    "North Chicago": (42.3253, -87.8412),
    "Old Mill Creek": (42.4183, -87.9420),
    "Park City": (42.3389, -87.8792),
    "Riverwoods": (42.1697, -87.8887),
    "Round Lake": (42.3595, -88.0928),
    "Round Lake Beach": (42.3781, -88.0784),
    "Round Lake Heights": (42.3639, -88.0834),
    "Round Lake Park": (42.3486, -88.0917),
    "Third Lake": (42.3536, -88.0270),
    "Tower Lakes": (42.2325, -88.1131),
    "Vernon Hills": (42.3370, -87.9695),
    "Volo": (42.3378, -88.1445),
    "Wadsworth": (42.4239, -87.9328),
    "Wauconda": (42.2586, -88.1370),
    "Waukegan": (42.3636, -87.8448),
    "Wheeling": (42.1392, -87.9287),
    "Winthrop Harbor": (42.4756, -87.8290),
    "Zion": (42.4247, -87.8384),
}

# The "Countywide" default view mirrors this city (the county seat).
COUNTYWIDE_ANCHOR = "Waukegan"


def http_get_json(url, params, retries=3):
    qs = urllib.parse.urlencode(params)
    full_url = url + "?" + qs
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full_url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {full_url}: {last_err}")


def pick_noon(hourly, field, day):
    """Pull the value closest to local noon for a given YYYY-MM-DD day."""
    target = day + "T12:00"
    times = hourly.get("time", [])
    values = hourly.get(field, [])
    if target in times:
        return values[times.index(target)]
    # fall back to the closest available hour that day
    same_day = [i for i, t in enumerate(times) if t.startswith(day)]
    if not same_day:
        return None
    mid = same_day[len(same_day) // 2]
    return values[mid]


def fetch_weather(lat, lon):
    data = http_get_json(WEATHER_URL, {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "daily": "precipitation_sum",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "past_days": HISTORY_DAYS - 1,
        "forecast_days": 1,
        "timezone": "America/Chicago",
    })
    return data


def fetch_aqi(lat, lon):
    data = http_get_json(AQI_URL, {
        "latitude": lat,
        "longitude": lon,
        "current": "us_aqi",
        "hourly": "us_aqi",
        "past_days": HISTORY_DAYS - 1,
        "forecast_days": 1,
        "timezone": "America/Chicago",
    })
    return data


def build_history_days(hourly_time):
    days = sorted({t[:10] for t in hourly_time})
    return days[-HISTORY_DAYS:]


def model_pollen_and_mold(name, days, temp_hist, humidity_hist, rain_hist, today_date):
    """
    Deterministic, documented ESTIMATE — not a measurement. No free public API
    provides county-level pollen counts, so this stands in for one until a
    licensed feed (e.g. a paid IQAir/Ambee/National Allergy Bureau product) is
    connected. The model:

      - Seasonal base for tree/grass/weed pollen from the calendar month
        (rough Midwest allergy-season curve: tree high in spring, grass in
        early summer, weed/ragweed in late summer-fall).
      - A small, deterministic per-city texture offset (seeded from the city
        name) so neighboring towns aren't perfectly identical.
      - Mold risk from real humidity plus a 3-day trailing rainfall sum
        (mold is understood to rise after wet, humid stretches).

    Swap this function out entirely once a real pollen data source is wired in
    — the rest of the pipeline (and the frontend) only cares about the 0-100
    index values this returns, not how they were produced.
    """
    def seed(s):
        h = 2166136261
        for ch in s:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        return h

    rng_state = seed(name)

    def rand():
        nonlocal rng_state
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        return (rng_state % 1000) / 1000.0

    month_curve = {
        # month: (tree_base, grass_base, weed_base)
        1: (5, 5, 5), 2: (10, 5, 5), 3: (55, 15, 5), 4: (80, 30, 8),
        5: (60, 55, 10), 6: (25, 65, 15), 7: (10, 45, 30), 8: (5, 25, 55),
        9: (5, 15, 65), 10: (8, 10, 40), 11: (5, 5, 15), 12: (5, 5, 5),
    }

    tree_hist, grass_hist, weed_hist, mold_hist = [], [], [], []
    for i, day in enumerate(days):
        month = int(day.split("-")[1])
        t_base, g_base, w_base = month_curve.get(month, (20, 20, 20))
        texture = (rand() - 0.5) * 18
        temp_bonus = max(0, (temp_hist[i] or 60) - 60) * 0.4 if temp_hist[i] is not None else 0

        tree_hist.append(round(max(1, min(100, t_base + texture + temp_bonus * 0.3))))
        grass_hist.append(round(max(1, min(100, g_base + texture + temp_bonus * 0.2))))
        weed_hist.append(round(max(1, min(100, w_base + texture + temp_bonus * 0.2))))

        rain_3day = sum(rain_hist[max(0, i - 2):i + 1])
        hum = humidity_hist[i] if humidity_hist[i] is not None else 55
        mold = hum * 0.55 + rain_3day * 35
        mold_hist.append(round(max(2, min(100, mold))))

    return tree_hist, grass_hist, weed_hist, mold_hist


def fetch_city(name, lat, lon):
    w = fetch_weather(lat, lon)
    a = fetch_aqi(lat, lon)

    days = build_history_days(w["hourly"]["time"])
    temp_hist = [pick_noon(w["hourly"], "temperature_2m", d) for d in days]
    humidity_hist = [pick_noon(w["hourly"], "relative_humidity_2m", d) for d in days]
    wind_hist = [pick_noon(w["hourly"], "wind_speed_10m", d) for d in days]

    rain_by_day = dict(zip(w["daily"]["time"], w["daily"]["precipitation_sum"]))
    rain_hist = [round(rain_by_day.get(d, 0) or 0, 2) for d in days]

    aqi_days = build_history_days(a["hourly"]["time"])
    aqi_hist = [pick_noon(a["hourly"], "us_aqi", d) for d in aqi_days]
    # align AQI history to the same day list as weather (should already match)
    if aqi_days != days:
        aqi_by_day = dict(zip(aqi_days, aqi_hist))
        aqi_hist = [aqi_by_day.get(d, aqi_hist[-1] if aqi_hist else 40) for d in days]

    tree_hist, grass_hist, weed_hist, mold_hist = model_pollen_and_mold(
        name, days, temp_hist, humidity_hist, rain_hist, days[-1]
    )

    def clean(v, fallback):
        return fallback if v is None else round(v)

    return {
        "lat": lat,
        "lon": lon,
        "days": days,
        "temp": [clean(v, 68) for v in temp_hist],
        "humidity": [clean(v, 55) for v in humidity_hist],
        "wind": [clean(v, 8) for v in wind_hist],
        "rainfall": rain_hist,
        "aqi": [clean(v, 40) for v in aqi_hist],
        "tree": tree_hist,
        "grass": grass_hist,
        "weed": weed_hist,
        "mold": mold_hist,
        "current_time": w.get("current", {}).get("time"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data.json")
    args = parser.parse_args()

    cities_out = {}
    errors = []
    for name, (lat, lon) in CITIES.items():
        try:
            cities_out[name] = fetch_city(name, lat, lon)
            print(f"  fetched {name}", file=sys.stderr)
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  FAILED {name}: {e}", file=sys.stderr)

    if not cities_out:
        print("No cities fetched successfully — aborting without writing data.json", file=sys.stderr)
        sys.exit(1)

    output = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "anchor_city": COUNTYWIDE_ANCHOR,
        "sources": {
            "weather": "Open-Meteo Forecast API (open-meteo.com) — blends NOAA/NWS and other national models",
            "aqi": "Open-Meteo Air Quality API (open-meteo.com) — US AQI, EPA formula",
            "pollen_mold": "Modeled — see scripts/fetch_data.py:model_pollen_and_mold(). No free public API available.",
        },
        "errors": errors,
        "cities": cities_out,
    }

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {args.out}: {len(cities_out)}/{len(CITIES)} cities, {len(errors)} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
