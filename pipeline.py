#!/usr/bin/env python3
"""
Game Lead Finder Pipeline — CSV → HTML
Usage: python pipeline.py [--mode small|standard] input.csv
"""
import argparse, csv, io, json, re, sys
from datetime import date
from html import escape
from pathlib import Path

LEGACY_DATES_FILE  = "legacy_dates.json"
ANCHORS_FILE       = "anchors_2025.json"

def load_anchor_names() -> set[str]:
    """Load calibration anchor game names from anchors_2025.json."""
    p = Path(ANCHORS_FILE)
    if not p.exists():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return {a["name"] for a in data.get("anchors", [])}

def load_legacy_dates() -> dict[str, str]:
    """Load {norm_name: date_str} from legacy_dates.json if present."""
    p = Path(LEGACY_DATES_FILE)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

# ── Exclusion lists ──────────────────────────────────────────────────────────

EXCLUDED_PUBLISHERS = {
    "Scopely","Activision","Electronic Arts","EA","Jam City","Kabam","Zynga",
    "Take-Two","Take-Two Interactive","2K","Rockstar","Ubisoft","Square Enix",
    "Bandai Namco","Konami","Capcom","Sega","Nintendo","Sony","King","Supercell",
    "Niantic","Glu","DeNA","NEXON","NCSoft","Netease","NetEase","miHoYo",
    "HoYoverse","Tencent","Lilith","IGG","Garena","Riot Games","Blizzard",
    "Bethesda","Warner Bros","Warner Bros.","IronSource","ironSource","Playtika",
    "SciPlay","DoubleU","Product Madness","Big Fish","Huuuge","Murka","AppLovin",
    "Azur Interactive Games","Nordcurrent","Embracer Group","Onesoft",
    "Stillfront Group","Ten Square Games","Modern Times Group","Magic Seven",
    "KamaGames","Microsoft","Lihuhu","Warner Bros. Discovery","Oakever Games",
    "37 Interactive Entertainment","AppQuantum","MY.GAMES","Tilting Point",
    "Outfit7 (Jinke Culture)","Outfit7","Beach Bum","Lessmore",
    "Rovio Entertainment","Joymaster Studio","Big Fish Games","iKame","EYEWIND",
    "Moonee","Supercent","Gaijin Distribution","Grand Games","Moon Active",
    "Wemade","Mattel163","Wildlife Studios",
}

CALIBRATION_ANCHORS = {
    "AMAZE!","Lamar - Idle Vlogger","Phone Case DIY","Zombie Waves","Heroes vs Hordes","Royal Escape","My Cat",
    "Dazzly","Idle Guy","Venue - Relaxing Design Games","Venue","SuitU",
    "Tower Battle","Idle Weapon Shop","LUDUS","Royal Cooking","Business Empire",
    "Idle Nightclub Tycoon","Zombastic","Merge Fashion: Romance Story",
    "Merge Fashion","Zombie Apocalypse: Doomsday-Z","Raid Rush","Obsidian Knight",
    "Kitty Sort","Fruit Merge","QuizzLand","IQ & Brain Test: Triviascapes",
    "DIY Makeup","Sculpt People","Dessert DIY","Eye Color Mix",
    "Coffee Mania - Sorting Jam",
}

PROFIT_RANGES = {"small": (60_000, 150_000), "standard": (150_000, 2_000_000)}
OUTPUT_FILE = "output.html"

# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_num(v: str) -> float:
    if not v:
        return 0.0
    v = re.sub(r"[,$ %]", "", v.strip())
    try:
        return float(v)
    except ValueError:
        return 0.0

def is_english(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", s))

# ── Model constants (calibrated against 30 anchor games, 2025 actuals) ──────
# IAA:      $0.10/dl × 50% margin  — median abs error ~74% (high variance, flag all IAA)
# Blend:    65% × Rev + 35% × IAA  — median abs error ~33%
# IAP High: 42% × Rev              — median abs error ~30% (updated from 38% via 2025 calibration)
IAA_RATE        = 0.10   # est. ad revenue per download
IAA_MARGIN      = 0.50   # publisher margin on ad revenue
BLEND_REV       = 0.65
BLEND_IAA       = 0.35
IAP_HIGH_MARGIN = 0.42   # was 0.38 pre-calibration
IAP_THRESHOLD   = 1_000_000

def compute_profit(dl_mo: float, rev_mo: float) -> tuple[float, bool]:
    rpd = rev_mo / dl_mo if dl_mo else 0.0
    if rpd < 0.10:
        return dl_mo * IAA_RATE * IAA_MARGIN, True
    if rev_mo <= IAP_THRESHOLD:
        return BLEND_REV * rev_mo + BLEND_IAA * (dl_mo * IAA_RATE * IAA_MARGIN), False
    return IAP_HIGH_MARGIN * rev_mo, False

def fmt_money(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def fmt_dl(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return f"{v:.0f}"

def trend_cat(pct: float) -> str:
    if pct > 10:   return "growing"
    if pct < -10:  return "declining"
    return "stable"

def trend_html(pct: float) -> str:
    emoji = "📈" if pct > 10 else ("📉" if pct < -10 else "➡️")
    warn  = " ⚠️" if pct > 50 else ""
    return f"{emoji} {pct:+.0f}%{warn}"

def normalize(name: str) -> str:
    # strip emoji / punctuation, strip subtitle after : - – —, first-15 lowercase
    name = re.sub(r"[^\w\s\-:–—]", "", name)
    name = re.split(r"[:\-–—]", name)[0].strip()
    return name[:15].lower()

# ── CSV loading ──────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-16") as f:
        text = f.read()
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))

# ── Existing HTML parsing ────────────────────────────────────────────────────

def load_existing(path: str) -> tuple[set[str], set[str], dict[str, str]]:
    """
    Returns (all_norm_names, returning_sources, added_dates).
    all_norm_names  — every game already in the HTML (any tab) → skip on re-run.
    returning_sources — games that were in growing or declining → Returning tab.
    added_dates     — {norm_name: original_added_date} to preserve first-seen dates.
    """
    p = Path(path)
    if not p.exists():
        return set(), set(), {}
    content = p.read_text(encoding="utf-8")

    all_names: set[str] = set()
    returning_src: set[str] = set()
    added_dates: dict[str, str] = {}

    # Every data row carries data-name, data-tab, data-added attributes on <tr>
    for m in re.finditer(
        r'<tr[^>]+data-name="([^"]+)"[^>]+data-tab="([^"]+)"[^>]+data-added="([^"]*)"',
        content
    ):
        raw_name, tab, added = m.group(1), m.group(2), m.group(3)
        norm = normalize(raw_name)
        all_names.add(norm)
        if added:
            added_dates[norm] = added
        if tab in ("growing", "declining"):
            returning_src.add(norm)

    return all_names, returning_src, added_dates

# ── Main pipeline ────────────────────────────────────────────────────────────

def parse_csv_to_records(csv_path: str) -> dict[str, dict]:
    """Load one CSV and return {norm_key: record} dict."""
    rows = load_csv(csv_path)
    seen: dict[str, dict] = {}
    for row in rows:
        name = row.get("Unified Name", "").strip()
        pub  = (row.get("Unified Publisher Name") or row.get("Publisher Name") or "").strip()
        if not name or not is_english(name):
            continue
        dl_mo   = parse_num(row.get("Downloads (Absolute)", "")) / 3
        rev_mo  = parse_num(row.get("Revenue (Absolute)", ""))   / 3
        rev_pop = parse_num(row.get("Revenue (PoP Growth %)", "")) * 100
        profit, is_iaa = compute_profit(dl_mo, rev_mo)
        key = name.lower()
        if key not in seen or rev_mo > seen[key]["rev_mo"]:
            seen[key] = dict(name=name, publisher=pub, dl_mo=dl_mo,
                             rev_mo=rev_mo, rev_pop=rev_pop,
                             profit=profit, is_iaa=is_iaa)
    return seen


def run(csv_paths: list[str], mode: str) -> None:
    profit_min, profit_max = PROFIT_RANGES[mode]
    run_date = date.today().strftime("%Y-%m-%d")

    existing_names, returning_src, added_dates = load_existing(OUTPUT_FILE)

    # Merge anchor names from JSON into the hardcoded set (single source of truth)
    live_anchors = CALIBRATION_ANCHORS | load_anchor_names()

    # Merge legacy dates: legacy file → existing HTML → today (legacy is oldest, lowest priority to override)
    legacy = load_legacy_dates()
    for norm, d in legacy.items():
        if norm not in added_dates:   # don't overwrite dates already in current HTML
            added_dates[norm] = d

    # ── Load all CSVs, track which game keys appear in multiple sources ──
    per_source: list[dict[str, dict]] = [parse_csv_to_records(p) for p in csv_paths]

    # Count how many sources each normalised key appears in
    source_count: dict[str, int] = {}
    for src in per_source:
        for key in src:
            source_count[key] = source_count.get(key, 0) + 1

    # Merge: keep highest-revenue record across sources
    merged: dict[str, dict] = {}
    for src in per_source:
        for key, rec in src.items():
            if key not in merged or rec["rev_mo"] > merged[key]["rev_mo"]:
                merged[key] = rec

    records = list(merged.values())

    # ── Publisher auto-exclude count (against merged pool) ──
    pub_count: dict[str, int] = {}
    for r in records:
        pk = r["publisher"].lower()
        pub_count[pk] = pub_count.get(pk, 0) + 1

    EXCL_LOWER = {e.lower() for e in EXCLUDED_PUBLISHERS}

    # ── Apply exclusions + profit filter ──
    filtered = []
    for r in records:
        if r["name"] in live_anchors:
            continue
        if r["publisher"].lower() in EXCL_LOWER:
            continue
        if pub_count.get(r["publisher"].lower(), 0) >= 8:
            continue
        if not (profit_min <= r["profit"] <= profit_max):
            continue
        filtered.append(r)

    # ── Categorize ──
    # Priority: existing HTML dedup > cross-source duplicate > previous run returning > trend
    tabs: dict[str, list] = {"growing": [], "stable": [], "declining": [], "returning": []}
    for r in filtered:
        norm = normalize(r["name"])
        key  = r["name"].lower()

        if norm in existing_names:
            continue  # already in the HTML — skip

        if source_count.get(key, 1) > 1:
            # Appeared in multiple CSV sources — cross-platform signal → Returning
            tabs["returning"].append(r)
        elif norm in returning_src:
            # Was in Growing/Declining on previous run → Returning
            tabs["returning"].append(r)
        else:
            tabs[trend_cat(r["rev_pop"])].append(r)

    for tab_list in tabs.values():
        tab_list.sort(key=lambda x: x["profit"], reverse=True)

    html = build_html(tabs, run_date, mode, added_dates)
    Path(OUTPUT_FILE).write_text(html, encoding="utf-8")

    total = sum(len(v) for v in tabs.values())
    cross = sum(1 for r in filtered if source_count.get(r["name"].lower(), 1) > 1
                and normalize(r["name"]) not in existing_names)
    print(f"OK  {OUTPUT_FILE}  --  {total} leads  "
          f"({len(tabs['growing'])} growing  |  {len(tabs['stable'])} stable  |  "
          f"{len(tabs['declining'])} declining  |  {len(tabs['returning'])} returning"
          f"  [{cross} cross-platform])")

# ── HTML builder ─────────────────────────────────────────────────────────────

def build_rows(records: list[dict], tab_name: str, run_date: str,
               added_dates: dict[str, str]) -> str:
    out = []
    for i, r in enumerate(records, 1):
        name_safe  = escape(r["name"])
        pub_safe   = escape(r["publisher"])
        iaa_suffix = ' 🎯 <span class="iaa-warn" title="IAA estimate — verify manually before presenting">⚠️</span>' if r["is_iaa"] else ""
        label      = name_safe + iaa_suffix
        row_cls    = "iaa-row" if r["is_iaa"] else ""
        p_cls      = " class='profit-red'" if tab_name == "declining" else ""
        added      = added_dates.get(normalize(r["name"]), run_date)

        out.append(
            f'<tr class="{row_cls}" data-name="{name_safe}" data-tab="{tab_name}"'
            f' data-added="{added}"'
            f' data-profit="{r["profit"]:.0f}" data-rev="{r["rev_mo"]:.0f}"'
            f' data-dl="{r["dl_mo"]:.0f}">'
            f'<td>{i}</td>'
            f'<td class="game-cell">{label}</td>'
            f'<td class="pub-cell">{pub_safe}</td>'
            f'<td>{added}</td>'
            f'<td{p_cls}>{fmt_money(r["profit"])}</td>'
            f'<td>{fmt_money(r["rev_mo"])}</td>'
            f'<td>{fmt_dl(r["dl_mo"])}</td>'
            f'<td>{trend_html(r["rev_pop"])}</td>'
            f'<td class="check-cell"><input type="checkbox" data-game="{name_safe}" onchange="saveCheck(this)"></td>'
            f'<td class="notes-cell"><input type="text" class="notes-input" data-game="{name_safe}" placeholder="…" oninput="saveNote(this)"></td>'
            f'</tr>'
        )
    return "\n".join(out)


def build_html(tabs: dict, run_date: str, mode: str, added_dates: dict[str, str] = {}) -> str:
    g   = len(tabs["growing"])
    st  = len(tabs["stable"])
    d   = len(tabs["declining"])
    ret = len(tabs["returning"])
    total = g + st + d + ret
    mode_label = "$60K–$150K" if mode == "small" else "$150K–$2M"

    rows_g   = build_rows(tabs["growing"],   "growing",   run_date, added_dates)
    rows_st  = build_rows(tabs["stable"],    "stable",    run_date, added_dates)
    rows_d   = build_rows(tabs["declining"], "declining", run_date, added_dates)
    rows_ret = build_rows(tabs["returning"], "returning", run_date, added_dates)

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Game Lead Finder — {mode_label} — {run_date}</title>
<style>
/* ── Reset / Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f7f8fa; --card: #fff; --border: #e2e6ea; --text: #1a1d23;
  --text2: #6c757d; --accent: #3b5bdb; --accent-h: #2f4ac0;
  --green: #2f9e44; --red: #e03131; --blue: #1971c2; --purple: #7048e8;
  --iaa: #fff9e6; --iaa-border: #ffe066;
  --th-bg: #f1f3f5; --hover: #f8f9fa;
  --shadow: 0 1px 4px rgba(0,0,0,.08);
}}
[data-theme="dark"] {{
  --bg: #0f1117; --card: #1a1d27; --border: #2d3142; --text: #e8eaf0;
  --text2: #9ba3b5; --accent: #748ffc; --accent-h: #5c7cfa;
  --green: #51cf66; --red: #ff6b6b; --blue: #74c0fc; --purple: #b197fc;
  --iaa: #2b2610; --iaa-border: #6b5a00;
  --th-bg: #222536; --hover: #1e2133;
  --shadow: 0 1px 4px rgba(0,0,0,.4);
}}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13px; background: var(--bg); color: var(--text);
  min-height: 100vh; padding: 20px 24px 40px;
}}

/* ── Top-right button cluster ── */
.top-right {{
  position: fixed; top: 16px; right: 20px;
  display: flex; align-items: center; gap: 8px; z-index: 999;
}}
#theme-btn {{
  width: 38px; height: 38px; border-radius: 50%;
  border: 1px solid var(--border); background: var(--card);
  cursor: pointer; font-size: 18px; display: flex; align-items: center;
  justify-content: center; box-shadow: var(--shadow); transition: background .2s;
}}
#theme-btn:hover {{ background: var(--hover); }}
.action-btn {{
  height: 36px; padding: 0 16px; border-radius: 8px; border: none;
  font-size: 12px; font-weight: 700; letter-spacing: .06em;
  cursor: pointer; display: flex; align-items: center; gap: 6px;
  box-shadow: var(--shadow); transition: filter .15s, transform .1s;
}}
.action-btn:hover  {{ filter: brightness(1.12); }}
.action-btn:active {{ transform: scale(.97); }}
#execute-btn {{ background: #2f9e44; color: #fff; }}
#upload-btn  {{ background: #1971c2; color: #fff; }}

/* ── Upload panel ── */
#upload-panel {{
  position: fixed; top: 62px; right: 20px; z-index: 998;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px 18px; width: 300px;
  box-shadow: 0 4px 20px rgba(0,0,0,.15);
  display: none; flex-direction: column; gap: 10px;
}}
#upload-panel.open {{ display: flex; }}
#upload-drop {{
  border: 2px dashed var(--border); border-radius: 8px;
  padding: 20px 12px; text-align: center; cursor: pointer;
  transition: border-color .2s, background .2s;
  font-size: 13px; color: var(--text2);
}}
#upload-drop:hover, #upload-drop.drag-over {{
  border-color: #1971c2; background: rgba(25,113,194,.05);
}}
#upload-drop .drop-icon {{ font-size: 24px; margin-bottom: 6px; }}
#upload-hint {{
  font-size: 11px; color: var(--text2); text-align: center;
  background: var(--th-bg); border-radius: 6px; padding: 6px 10px;
}}
#upload-status {{
  font-size: 12px; color: var(--text2); min-height: 16px; text-align: center;
}}

/* ── Toast ── */
#toast {{
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(60px);
  background: #333; color: #fff; padding: 10px 20px; border-radius: 8px;
  font-size: 13px; opacity: 0; transition: opacity .3s, transform .3s;
  pointer-events: none; z-index: 9999; white-space: nowrap;
}}
#toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}

/* ── Header ── */
h1 {{ font-size: 20px; font-weight: 700; color: var(--text); margin-bottom: 4px; }}
.subtitle {{ color: var(--text2); font-size: 12px; margin-bottom: 18px; }}

/* ── Summary card ── */
.summary-card {{
  display: flex; flex-wrap: wrap; gap: 12px;
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px; margin-bottom: 22px; box-shadow: var(--shadow);
}}
.summary-item {{ display: flex; flex-direction: column; align-items: center;
  min-width: 70px; }}
.s-num {{ font-size: 22px; font-weight: 700; line-height: 1.1; }}
.s-label {{ font-size: 11px; color: var(--text2); margin-top: 2px; }}
.s-total  {{ color: var(--text); }}
.s-green  {{ color: var(--green); }}
.s-blue   {{ color: var(--blue); }}
.s-red    {{ color: var(--red); }}
.s-purple {{ color: var(--purple); }}
.s-accent {{ color: var(--accent); }}
.summary-divider {{ width: 1px; background: var(--border); align-self: stretch; margin: 0 4px; }}

/* ── Tabs ── */
.tabs {{ display: flex; gap: 4px; margin-bottom: 0; border-bottom: 2px solid var(--border); }}
.tab-btn {{
  padding: 8px 16px; border: none; background: none; cursor: pointer;
  color: var(--text2); font-size: 13px; font-weight: 500; border-radius: 6px 6px 0 0;
  border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color .15s;
}}
.tab-btn:hover {{ color: var(--text); background: var(--hover); }}
.tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); background: var(--card); }}

/* ── Tab panels ── */
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}

/* ── Search ── */
.search-bar {{
  width: 260px; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--card); color: var(--text);
  font-size: 12px; margin: 12px 0 8px; outline: none;
}}
.search-bar:focus {{ border-color: var(--accent); }}

/* ── Table wrapper ── */
.tbl-wrap {{ overflow-x: auto; border-radius: 8px; border: 1px solid var(--border);
  box-shadow: var(--shadow); background: var(--card); }}

table {{ width: 100%; border-collapse: collapse; table-layout: auto; font-size: 14.3px; }}

/* ── Resize handle on th ── */
th {{
  position: relative; background: var(--th-bg); color: var(--text2);
  font-weight: 600; font-size: 11px; text-transform: uppercase;
  letter-spacing: .04em; padding: 9px 12px; white-space: nowrap;
  user-select: none; cursor: pointer;
}}
th:hover {{ background: var(--hover); color: var(--text); }}
th .sort-icon {{ margin-left: 4px; opacity: .5; font-style: normal; }}
th.sorted-asc .sort-icon::after  {{ content: " ▲"; }}
th.sorted-desc .sort-icon::after {{ content: " ▼"; }}
th:not(.sorted-asc):not(.sorted-desc) .sort-icon::after {{ content: " ⇅"; }}

.resize-handle {{
  position: absolute; right: 0; top: 0; bottom: 0; width: 5px;
  cursor: col-resize; z-index: 1;
}}
.resize-handle:hover, .resize-handle.active {{ background: var(--accent); opacity: .5; }}

td {{ padding: 8px 12px; border-top: 1px solid var(--border); vertical-align: middle; }}
tr:hover td {{ background: var(--hover); }}

.iaa-row td {{ background: var(--iaa); }}
.iaa-row:hover td {{ filter: brightness(.97); }}
[data-theme="dark"] .iaa-row td {{ background: var(--iaa); }}

.profit-red {{ color: var(--red) !important; font-weight: 600; }}
.game-cell {{ font-weight: 500; max-width: 200px; }}
.pub-cell  {{ color: var(--text2); font-size: 12px; max-width: 160px; }}

/* ── Checkbox & notes ── */
.check-cell input[type=checkbox] {{ width: 15px; height: 15px; cursor: pointer; accent-color: var(--accent); }}
.notes-input {{
  width: 100%; min-width: 120px; padding: 3px 6px; border: 1px solid var(--border);
  border-radius: 4px; background: transparent; color: var(--text); font-size: 12px;
  outline: none;
}}
.notes-input:focus {{ border-color: var(--accent); background: var(--card); }}

/* ── Empty state ── */
.empty {{ padding: 40px; text-align: center; color: var(--text2); font-size: 13px; }}

/* ── IAA warning tooltip ── */
.iaa-warn {{ cursor: help; font-style: normal; }}

/* ── Tab banners ── */
.tab-banner {{
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; border-radius: 6px; margin-bottom: 8px;
  font-size: 12px; line-height: 1.4;
}}
.tab-banner.clean {{
  background: #ebfbee; border: 1px solid #8ce99a; color: #2f9e44;
}}
.tab-banner.warn {{
  background: #fff9db; border: 1px solid #ffe066; color: #835900;
}}
[data-theme="dark"] .tab-banner.clean {{
  background: #0d2e14; border-color: #2f9e44; color: #69db7c;
}}
[data-theme="dark"] .tab-banner.warn {{
  background: #2b2300; border-color: #e67700; color: #ffd43b;
}}
.tab-banner .banner-icon {{ font-size: 14px; flex-shrink: 0; }}
</style>
</head>
<body>

<div class="top-right">
  <button id="execute-btn" class="action-btn" onclick="onExecute()">⚡ EXECUTE</button>
  <button id="upload-btn"  class="action-btn" onclick="toggleUpload()">⬆ UPLOAD</button>
  <button id="theme-btn" onclick="toggleTheme()" title="Toggle dark/light">🌙</button>
</div>

<!-- Upload panel -->
<div id="upload-panel">
  <div id="upload-drop" onclick="document.getElementById('csv-input').click()"
       ondragover="onDragOver(event)" ondragleave="onDragLeave(event)" ondrop="onDrop(event)">
    <div class="drop-icon">📂</div>
    <div>Click or drag &amp; drop CSV files here</div>
    <input id="csv-input" type="file" accept=".csv,.tsv,.txt" multiple
           style="display:none" onchange="onFilePick(this.files)">
  </div>
  <div id="upload-hint">Last 90 days &nbsp;·&nbsp; Games &nbsp;·&nbsp; WW &nbsp;·&nbsp; Both stores</div>
  <div id="upload-status"></div>
</div>

<!-- Toast -->
<div id="toast"></div>

<h1>Game Lead Finder &nbsp;<span style="font-weight:400;font-size:14px;color:var(--text2)">{mode_label}</span></h1>
<div class="subtitle">Run date: {run_date} &nbsp;·&nbsp; Platform: Google Play (Unified) &nbsp;·&nbsp; Window: 90-day CSV</div>

<div class="summary-card">
  <div class="summary-item"><span class="s-num s-total">{total}</span><span class="s-label">Total</span></div>
  <div class="summary-divider"></div>
  <div class="summary-item"><span class="s-num s-green">{g}</span><span class="s-label">Growing</span></div>
  <div class="summary-item"><span class="s-num s-blue">{st}</span><span class="s-label">Stable</span></div>
  <div class="summary-item"><span class="s-num s-red">{d}</span><span class="s-label">Declining</span></div>
  <div class="summary-item"><span class="s-num s-purple">{ret}</span><span class="s-label">Returning</span></div>
  <div class="summary-divider"></div>
  <div class="summary-item"><span class="s-num s-accent" id="reviewed-count">0</span><span class="s-label">Reviewed</span></div>
  <div class="summary-item"><span class="s-num" id="reviewed-pct">0%</span><span class="s-label">% Done</span></div>
  <div class="summary-item"><span class="s-num" id="notes-count">0</span><span class="s-label">With Notes</span></div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('growing',this)">📈 Growing ({g})</button>
  <button class="tab-btn" onclick="switchTab('stable',this)">➡️ Stable ({st})</button>
  <button class="tab-btn" onclick="switchTab('declining',this)">📉 Declining ({d})</button>
  <button class="tab-btn" onclick="switchTab('returning',this)">🔄 Returning ({ret})</button>
</div>

<!-- ── Growing ── -->
<div class="tab-panel active" id="tab-growing">
  <input class="search-bar" placeholder="Search games…" oninput="filterTab('growing',this.value)">
  <div class="tab-banner warn"><span class="banner-icon">⚠️</span><span>These games may already exist in Salesforce. Cross-check before outreach. <em>Salesforce dedup coming soon.</em></span></div>
  <div class="tbl-wrap">
    <table id="tbl-growing">
      <thead><tr>
        <th style="width:42px">#<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Game<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Publisher<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Added<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="profit">Est. Profit/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="rev">Revenue/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="dl">Downloads/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Rev Trend (90d)<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th style="width:64px">Checked?</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>{rows_g if rows_g else '<tr><td colspan="10" class="empty">No games in this range.</td></tr>'}</tbody>
    </table>
  </div>
</div>

<!-- ── Stable ── -->
<div class="tab-panel" id="tab-stable">
  <input class="search-bar" placeholder="Search games…" oninput="filterTab('stable',this.value)">
  <div class="tab-banner clean"><span class="banner-icon">✅</span><span>These games are <strong>not in Salesforce</strong> — verified clean leads ready for review.</span></div>
  <div class="tbl-wrap">
    <table id="tbl-stable">
      <thead><tr>
        <th style="width:42px">#<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Game<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Publisher<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Added<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="profit">Est. Profit/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="rev">Revenue/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="dl">Downloads/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Rev Trend (90d)<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th style="width:64px">Checked?</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>{rows_st if rows_st else '<tr><td colspan="10" class="empty">No games in this range.</td></tr>'}</tbody>
    </table>
  </div>
</div>

<!-- ── Declining ── -->
<div class="tab-panel" id="tab-declining">
  <input class="search-bar" placeholder="Search games…" oninput="filterTab('declining',this.value)">
  <div class="tab-banner warn"><span class="banner-icon">⚠️</span><span>These games may already exist in Salesforce. Cross-check before outreach. <em>Salesforce dedup coming soon.</em></span></div>
  <div class="tbl-wrap">
    <table id="tbl-declining">
      <thead><tr>
        <th style="width:42px">#<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Game<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Publisher<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Added<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="profit">Est. Profit/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="rev">Revenue/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="dl">Downloads/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Rev Trend (90d)<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th style="width:64px">Checked?</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>{rows_d if rows_d else '<tr><td colspan="10" class="empty">No games in this range.</td></tr>'}</tbody>
    </table>
  </div>
</div>

<!-- ── Returning ── -->
<div class="tab-panel" id="tab-returning">
  <input class="search-bar" placeholder="Search games…" oninput="filterTab('returning',this.value)">
  <div class="tab-banner warn"><span class="banner-icon">⚠️</span><span>These games may already exist in Salesforce. Cross-check before outreach. <em>Salesforce dedup coming soon.</em></span></div>
  <div class="tbl-wrap">
    <table id="tbl-returning">
      <thead><tr>
        <th style="width:42px">#<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Game<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Publisher<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Added<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="profit">Est. Profit/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="rev">Revenue/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th data-col="dl">Downloads/mo<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th>Rev Trend (90d)<i class="sort-icon"></i><div class="resize-handle"></div></th>
        <th style="width:64px">Checked?</th>
        <th>Notes</th>
      </tr></thead>
      <tbody>{rows_ret if rows_ret else '<tr><td colspan="10" class="empty">No returning games yet.</td></tr>'}</tbody>
    </table>
  </div>
</div>

<script>
// ── Theme ──
function toggleTheme() {{
  const html = document.documentElement;
  const dark = html.dataset.theme === 'dark';
  html.dataset.theme = dark ? 'light' : 'dark';
  document.getElementById('theme-btn').textContent = dark ? '🌙' : '☀️';
  localStorage.setItem('glf_theme', html.dataset.theme);
}}
(function() {{
  const t = localStorage.getItem('glf_theme');
  if (t) {{
    document.documentElement.dataset.theme = t;
    document.getElementById('theme-btn').textContent = t === 'dark' ? '☀️' : '🌙';
  }}
}})();

// ── Tabs ──
function switchTab(name, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}

// ── Search / filter ──
function filterTab(tabName, query) {{
  const q = query.toLowerCase();
  document.querySelectorAll('#tbl-' + tabName + ' tbody tr').forEach(row => {{
    const name = (row.dataset.name || '').toLowerCase();
    const pub  = (row.querySelector('.game-cell')?.title || '').toLowerCase();
    row.style.display = (!q || name.includes(q) || pub.includes(q)) ? '' : 'none';
  }});
}}

// ── localStorage — checks ──
function saveCheck(cb) {{
  localStorage.setItem('glf_check_' + cb.dataset.game, cb.checked ? '1' : '');
  updateReviewedCount();
}}
function saveNote(inp) {{
  localStorage.setItem('glf_note_' + inp.dataset.game, inp.value);
  updateReviewedCount();
}}
function restoreState() {{
  document.querySelectorAll('input[type=checkbox][data-game]').forEach(cb => {{
    const v = localStorage.getItem('glf_check_' + cb.dataset.game);
    if (v === '1') cb.checked = true;
  }});
  document.querySelectorAll('.notes-input[data-game]').forEach(inp => {{
    const v = localStorage.getItem('glf_note_' + inp.dataset.game);
    if (v) inp.value = v;
  }});
  updateReviewedCount();
}}
function updateReviewedCount() {{
  const checked   = document.querySelectorAll('input[type=checkbox][data-game]:checked').length;
  const total     = document.querySelectorAll('input[type=checkbox][data-game]').length;
  const withNotes = Array.from(document.querySelectorAll('.notes-input[data-game]'))
                         .filter(el => el.value.trim() !== '').length;
  document.getElementById('reviewed-count').textContent = checked;
  document.getElementById('reviewed-pct').textContent =
    total ? Math.round(checked / total * 100) + '%' : '0%';
  document.getElementById('notes-count').textContent = withNotes;
}}

// ── Column sort ──
(function() {{
  const sortState = {{}};
  document.querySelectorAll('th[data-col]').forEach(th => {{
    th.addEventListener('click', function(e) {{
      if (e.target.classList.contains('resize-handle')) return;
      const col  = th.dataset.col;
      const tbl  = th.closest('table');
      const tbody = tbl.querySelector('tbody');
      const key  = tbl.id + '_' + col;
      const asc  = sortState[key] !== true;
      sortState[key] = asc;

      // Update sort icons
      tbl.querySelectorAll('th').forEach(t => {{
        t.classList.remove('sorted-asc','sorted-desc');
      }});
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');

      const rows = Array.from(tbody.querySelectorAll('tr[data-name]'));
      rows.sort((a, b) => {{
        const av = parseFloat(a.dataset[col] || 0);
        const bv = parseFloat(b.dataset[col] || 0);
        return asc ? av - bv : bv - av;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});

  // Also sort by game name (text) for non-numeric th
  document.querySelectorAll('th:not([data-col])').forEach(th => {{
    if (th.querySelector('.resize-handle') === null) return;
    th.addEventListener('click', function(e) {{
      if (e.target.classList.contains('resize-handle')) return;
      const tbl   = th.closest('table');
      const tbody = tbl.querySelector('tbody');
      const idx   = Array.from(th.parentNode.children).indexOf(th);
      const key   = tbl.id + '_col' + idx;
      const asc   = sortState[key] !== true;
      sortState[key] = asc;
      tbl.querySelectorAll('th').forEach(t => t.classList.remove('sorted-asc','sorted-desc'));
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
      const rows = Array.from(tbody.querySelectorAll('tr[data-name]'));
      rows.sort((a, b) => {{
        const av = a.cells[idx]?.textContent.trim() || '';
        const bv = b.cells[idx]?.textContent.trim() || '';
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}})();

// ── Column resize ──
(function() {{
  document.querySelectorAll('.resize-handle').forEach(handle => {{
    let startX, startW, th;
    handle.addEventListener('mousedown', e => {{
      e.preventDefault();
      th = handle.parentElement;
      startX = e.pageX;
      startW = th.offsetWidth;
      handle.classList.add('active');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }});
    function onMove(e) {{
      th.style.width = Math.max(60, startW + (e.pageX - startX)) + 'px';
    }}
    function onUp() {{
      handle.classList.remove('active');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }}
  }});
}})();

// ── Toast ──
function showToast(msg, duration=3000) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}}

// ── EXECUTE ──
function onExecute() {{
  showToast('⚡ Sensor Tower API not connected yet — coming soon', 3500);
}}

// ── UPLOAD panel ──
function toggleUpload() {{
  const panel = document.getElementById('upload-panel');
  panel.classList.toggle('open');
}}
// Close panel if clicking outside
document.addEventListener('click', e => {{
  const panel = document.getElementById('upload-panel');
  const btn   = document.getElementById('upload-btn');
  if (panel.classList.contains('open') && !panel.contains(e.target) && e.target !== btn) {{
    panel.classList.remove('open');
  }}
}});

// ── Drag & drop ──
function onDragOver(e) {{
  e.preventDefault();
  document.getElementById('upload-drop').classList.add('drag-over');
}}
function onDragLeave(e) {{
  document.getElementById('upload-drop').classList.remove('drag-over');
}}
function onDrop(e) {{
  e.preventDefault();
  document.getElementById('upload-drop').classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
}}
function onFilePick(files) {{
  uploadFiles(files);
}}

// ── Upload & refresh ──
async function uploadFiles(files) {{
  if (!files || files.length === 0) return;
  const status = document.getElementById('upload-status');
  status.textContent = 'Uploading...';

  const form = new FormData();
  for (const f of files) form.append('csvfiles', f, f.name);

  try {{
    const resp = await fetch('/upload', {{ method: 'POST', body: form }});
    const data = await resp.json();
    if (data.ok) {{
      status.textContent = data.summary;
      showToast('Done! Reloading...', 2000);
      setTimeout(() => location.reload(), 1800);
    }} else {{
      status.textContent = 'Error: ' + data.error;
      showToast('Upload failed — see panel', 4000);
    }}
  }} catch(err) {{
    status.textContent = 'Could not reach local server. Is server.py running?';
    showToast('Server not running — run: py server.py', 5000);
  }}
}}

// ── Init ──
restoreState();
</script>
</body>
</html>"""

# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Game Lead Finder Pipeline")
    parser.add_argument("csv", nargs="+", help="One or more Sensor Tower CSV exports (UTF-16, tab-separated)")
    parser.add_argument("--mode", choices=["small", "standard"], default="small",
                        help="small=$60K-$150K  standard=$150K-$2M  (default: small)")
    args = parser.parse_args()

    for p in args.csv:
        if not Path(p).exists():
            sys.exit(f"Error: file not found -- {p}")

    run(args.csv, args.mode)

if __name__ == "__main__":
    main()
