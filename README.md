# Lake County AirBio

An environmental and allergy-awareness site for Lake County, Illinois — daily pollen, mold,
air-quality, and weather conditions for 47 municipalities, a 7-day trend view, and a
weighted Allergy Risk score, built as a student project by Ambuja Singh.

## How the live data works

`index.html` doesn't call any API directly — browsers can't be trusted to keep API usage
polite or consistent, and this keeps the page itself simple and fast. Instead:

1. `scripts/fetch_data.py` fetches real temperature, humidity, wind, rainfall, and AQI for
   every city in its `CITIES` dict from [Open-Meteo](https://open-meteo.com/) (free, no API
   key required), and computes a modeled pollen/mold estimate from that real weather data.
2. It writes everything to `data.json` in the repo root.
3. `.github/workflows/update-data.yml` runs that script automatically **once a day** on
   GitHub's own servers, and commits the refreshed `data.json` back to the repo if anything
   changed.
4. `index.html` simply does `fetch('./data.json')` when a visitor loads the page, so everyone
   always sees whatever the last scheduled run produced — no server, database, or API key of
   your own required.

## Publishing it on GitHub Pages

1. Create a new GitHub repository and push everything in this folder to it (including the
   hidden `.github/` folder — make sure your git client isn't ignoring dotfiles).
2. In the repo, go to **Settings → Pages**, and under "Build and deployment" choose
   **Deploy from a branch**, branch `main`, folder `/ (root)`. Save.
3. Go to the **Actions** tab. GitHub Actions is enabled by default for public repos, but if
   you see a prompt to enable workflows, click it. You should see the
   "Update Lake County AirBio data" workflow listed.
4. Run it once by hand: open that workflow → **Run workflow** → **Run workflow**. This
   creates the first `data.json` (the page will show "Live data unavailable" until this has
   run at least once).
5. After that, it runs automatically every day at 11:00 UTC (6 AM Central during daylight
   time) — no further action needed. You can always trigger it manually the same way if you
   want to force a refresh.
6. Your site will be live at `https://<your-username>.github.io/<repo-name>/` a minute or two
   after step 2.

## Changing the schedule

Edit the `cron:` line in `.github/workflows/update-data.yml`. Cron times are in UTC. For
example, `"0 6,18 * * *"` would refresh twice a day, at 6 AM and 6 PM UTC.

## Adding or removing a city

Edit the `CITIES` dictionary at the top of `scripts/fetch_data.py` (name → latitude/longitude),
**and** the matching `cities` array near the top of the `<script>` block in `index.html`
(name → x/y position on the 640×760 map). The map position for a new city can be approximated
from its latitude/longitude relative to nearby cities already on the map, or recomputed with a
simple linear projection against the county's bounding box.

## Upgrading pollen/mold from modeled to a real feed

No free, keyless public API publishes county-level pollen counts today. If you later get
access to a licensed feed (for example, a paid Ambee or IQAir pollen API, or a regional
National Allergy Bureau station), replace the body of `model_pollen_and_mold()` in
`scripts/fetch_data.py` with real API calls — the rest of the pipeline and the front end
only care about the `tree` / `grass` / `weed` / `mold` arrays it returns (0–100 index values
per day), not how they're produced.

## Upgrading AQI to EPA AirNow

Open-Meteo's air-quality API is free and keyless, and is a reasonable default. To switch to
the EPA's own [AirNow](https://docs.airnowapi.org/) feed instead, get a free API key, add it
as a GitHub Actions secret (**Settings → Secrets and variables → Actions**), pass it into the
workflow as an environment variable, and swap `fetch_aqi()` in `fetch_data.py` to call
AirNow's endpoint instead — the output shape (`aqi`: a 7-value array) should stay the same.

## Local testing

```bash
python3 scripts/fetch_data.py --out data.json   # needs internet access to open-meteo.com
python3 -m http.server 8000                     # then open http://localhost:8000
```

## Disclaimer

This is a student-built awareness and pattern-analysis tool, not a medical device. See the
site's About page for the full disclaimer.
