from datetime import datetime, timezone
from typing import List
import numpy as np
import pandas as pd
import pydeck as pdk
from pydeck.data_utils import compute_view
import altair as alt
import streamlit as st

st.set_page_config(page_title="RemedyAtlas", page_icon="🌍", layout="wide")

st.title("🌍 RemedyAtlas — Folk Remedies Around the World")
st.caption(
    "Educational showcase of traditional practices. **Not medical advice.** "
    "Practices may lack clinical evidence or be unsafe for some people. "
    "Always consult a qualified healthcare professional."
)

# ---------- About / Intro ----------
with st.container():
    st.subheader("What is this?")
    st.markdown(
        """
**RemedyAtlas** collects and visualizes **folk and traditional home remedies** from around the world —
filterable by **symptom/ailment**, **region**, **evidence level**, and **country**. Explore entries on a
world map and browse them as cards or a table. Sources include public agencies (e.g., WHO/EMA/NCCIH)
and reputable reviews. This is **purely informational** and **not medical advice**.
        """
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            """
**How to use**
- Use the sidebar to pick **Symptom/Ailment**
- Optional filters: **Region**, **Evidence**, **Country contains**
- Click pins on the map for details
- Switch between **Card view / Table view** below
            """
        )
    with c2:
        st.markdown(
            """
**Evidence legend**
- 🟢 **some/clinical** – some clinical evidence
- 🟡 **mixed** – mixed/uncertain evidence
- 🟠 **limited/low** – limited data only
- ⚪ **folk/tradition** – traditional use
- ⚫ **n/a** – not applicable
            """
        )
    with c3:
        st.markdown(
            """
**Safety**
- Herbs can have **interactions** & **contraindications**
- Extra caution for **pregnancy**, **children**, **heart/liver**, **anticoagulants**
- For serious concerns, **seek medical care**
            """
        )
    st.divider()

# ---------------- Constants ----------------
REQUIRED = [
    "ailment","plant_common","plant_scientific","preparation",
    "region","country","latitude","longitude",
    "tradition_notes","cautions","evidence_level","source_url"
]

EVIDENCE_EMOJI = {
    "some/clinical": "🟢 some/clinical",
    "mixed": "🟡 mixed",
    "limited/low": "🟠 limited/low",
    "folk-tradition": "⚪ folk/tradition",
    "not-applicable": "⚫ n/a",
}

CAUTION_KEYWORDS: List[str] = [
    "pregnan", "anticoagul", "bleeding", "aspirin", "blood pressure",
    "liver", "renal", "children", "pediatric", "toxic", "avoid"
]

ALL_SYMPTOMS = "All symptoms"
ALL_REGIONS = "All regions"
ALL_EVIDENCE = "All evidence levels"

# ---------------- Helpers ----------------
def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # map common accidental variants
    aliases = {"a_ilment": "ailment", "plant_name": "plant_common"}
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    return df

@st.cache_data
def load_csv(path: str) -> pd.DataFrame:
    for enc in ("utf-8", "utf-8-sig"):
        try:
            df = pd.read_csv(path, sep=None, engine="python", encoding=enc)
            return _normalize_headers(df)
        except FileNotFoundError:
            return pd.DataFrame(columns=REQUIRED)
        except Exception:
            continue
    return pd.DataFrame(columns=REQUIRED)

def coerce_and_validate(df: pd.DataFrame) -> pd.DataFrame:
    df = _normalize_headers(df).copy()

    # Coerce numeric
    df["latitude"]  = pd.to_numeric(df.get("latitude"),  errors="coerce")
    df["longitude"] = pd.to_numeric(df.get("longitude"), errors="coerce")

    # Detect & fix swapped lat/lon
    looks_swapped = (df["latitude"].abs() > 90) & (df["longitude"].abs() <= 90)
    n_swapped = int(looks_swapped.sum())
    if n_swapped:
        lat_old = df.loc[looks_swapped, "latitude"].copy()
        df.loc[looks_swapped, "latitude"]  = df.loc[looks_swapped, "longitude"]
        df.loc[looks_swapped, "longitude"] = lat_old
        st.warning(f"Auto-fixed {n_swapped} row(s) with swapped latitude/longitude.")

    # Drop invalids
    valid_mask = (df["latitude"].between(-90, 90)) & (df["longitude"].between(-180, 180))
    dropped = int((~valid_mask).sum())
    if dropped:
        st.warning(f"Dropped {dropped} row(s) with invalid coordinates after validation.")
    df = df.loc[valid_mask].copy()

    # Evidence badge
    def badge(ev: str) -> str:
        ev = (ev or "").strip().lower()
        return EVIDENCE_EMOJI.get(ev, "⚪ folk/tradition")
    df["evidence_badge"] = df.get("evidence_level", "").apply(badge)

    # Caution flag
    def has_caution(text: str) -> str:
        t = (str(text) or "").lower()
        return "⚠️" if any(k in t for k in CAUTION_KEYWORDS) else "—"
    df["caution_flag"] = df.get("cautions", "").apply(has_caution)

    # Tooltip
    df["_tooltip"] = (
        df.get("country","") + "<br/>" +
        df.get("plant_common","") + " <i>(" + df.get("plant_scientific","") + ")</i><br/>" +
        df.get("preparation","")
    )
    return df

def jitter_overlaps(df: pd.DataFrame, deg_radius: float = 0.25) -> pd.DataFrame:
    """Spread points sharing (country, ailment) so markers don’t sit exactly on top of each other."""
    if df.empty:
        return df
    out = []
    for (_, _g) in df.groupby(["country","ailment"], dropna=False):
        g = _g.copy()
        if len(g) == 1:
            g["lat_j"] = g["latitude"]
            g["lon_j"] = g["longitude"]
            out.append(g); continue
        lat0 = float(g["latitude"].iloc[0])
        lon0 = float(g["longitude"].iloc[0])
        angles = np.linspace(0, 2*np.pi, len(g), endpoint=False)
        lon_scale = max(np.cos(np.deg2rad(lat0)), 1e-6)
        g["lat_j"] = lat0 + deg_radius * np.sin(angles)
        g["lon_j"] = lon0 + (deg_radius * np.cos(angles)) / lon_scale
        out.append(g)
    return pd.concat(out, ignore_index=True)

# ---------------- Load data ----------------
df_raw = load_csv("data/remedies.csv")
df = coerce_and_validate(df_raw)

# NEW: ensure exact-match filters won’t fail due to stray spaces/zero-width chars
for col in ["ailment", "region", "country"]:
    df[col] = (
        df[col]
        .astype(str)
        .str.replace("\u00a0", " ", regex=False)  # NBSP
        .str.replace("\u200b", "", regex=False)   # zero-width space
        .str.strip()
    )

if df.empty:
    st.info("Your dataset is empty. Add rows to **data/remedies.csv** and refresh.")
    st.stop()

# ---------------- Sidebar (clean UX) ----------------
with st.sidebar:
    st.header("Filters")

    ailments = sorted(df["ailment"].dropna().unique().tolist())
    ailment = st.selectbox("Symptom / ailment", [ALL_SYMPTOMS] + ailments, index=0)

    regions = sorted(df["region"].dropna().unique().tolist())
    region = st.selectbox("Region", [ALL_REGIONS] + regions, index=0)

    ev = st.selectbox("Evidence level", [ALL_EVIDENCE] + list(EVIDENCE_EMOJI.keys()), index=0)

    country_search = st.text_input("Country contains (optional)", "")
    st.markdown(
        "**Safety note**: Traditional practices can be unsafe for certain people "
        "(pregnancy, meds, conditions). This app is informational only."
    )

# ---------------- Apply filters ----------------
mask = pd.Series(True, index=df.index)

if ailment != ALL_SYMPTOMS:
    # EXACT match: dropdown and filter use identical strings
    mask &= df["ailment"].eq(ailment)

if region != ALL_REGIONS:
    mask &= df["region"].eq(region)

if ev != ALL_EVIDENCE:
    mask &= df["evidence_level"].str.lower().eq(ev.lower())

if country_search.strip():
    mask &= df["country"].str.contains(country_search.strip(), case=False, na=False)

fdf = df.loc[mask].copy()
fdf = jitter_overlaps(fdf)

# ---------------- KPIs ----------------
k1, k2, k3 = st.columns(3)
k1.metric("Matches", len(fdf))
k2.metric("Distinct countries", fdf["country"].nunique() if len(fdf) else 0)
k3.metric("Distinct plants", fdf["plant_scientific"].nunique() if len(fdf) else 0)

# ---------------- Map ----------------
if len(fdf):
    try:
        view = compute_view(fdf[["longitude", "latitude"]])
        view.pitch = 0
        view.zoom = max(1.5, view.zoom)
    except Exception:
        view = pdk.ViewState(
            latitude=float(fdf["latitude"].mean()),
            longitude=float(fdf["longitude"].mean()),
            zoom=1.7
        )
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=fdf,
        get_position=["lon_j", "lat_j"],   # jittered coords
        get_radius=200000,
        get_fill_color=[34, 197, 94, 160],
        pickable=True,
    )
    tooltip = {"html": "{_tooltip}", "style": {"backgroundColor": "#0b0f12", "color": "white"}}
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip))
else:
    st.info("No entries match your filters.")

# ---------------- Pretty Practices section ----------------
st.subheader("Practices")

# --- tiny CSS for badges/cards ---
st.markdown(
    """
    <style>
      .ra-card{border-radius:14px;padding:14px 16px;margin:10px 0;background:#12171b;border:1px solid #1e2936;}
      .ra-top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
      .ra-country{font-weight:600}
      .ra-plant{font-weight:600}
      .ra-chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#1f2a36;color:#b7c5d3;border:1px solid #263445}
      .ra-chip.green{background:#12361f;color:#d7f9df;border-color:#1e5d33}
      .ra-chip.yellow{background:#3a3719;color:#fff3b0;border-color:#5e560f}
      .ra-chip.orange{background:#3c271b;color:#ffd8c2;border-color:#6a3b1d}
      .ra-chip.gray{background:#2a2a2a;color:#d0d0d0;border-color:#3a3a3a}
      .ra-chip.dark{background:#1f1f1f;color:#bdbdbd;border-color:#2a2a2a}
      .ra-note{margin-top:6px;color:#cbd5df}
      .ra-caution{margin-top:6px;color:#ffd7d7}
      .ra-actions{margin-top:8px}
      .ra-actions a{font-size:12px;color:#9ecbff;text-decoration:none}
    </style>
    """,
    unsafe_allow_html=True,
)

# choose view
view = st.radio("View", ["Card view", "Table view"], horizontal=True)

def _evidence_chip(ev: str) -> str:
    ev = (ev or "").lower()
    if "some/clinical" in ev:  return "<span class='ra-chip green'>🟢 some/clinical</span>"
    if "mixed" in ev:          return "<span class='ra-chip yellow'>🟡 mixed</span>"
    if "limited" in ev:        return "<span class='ra-chip orange'>🟠 limited/low</span>"
    if "folk" in ev:           return "<span class='ra-chip gray'>⚪ folk/tradition</span>"
    return "<span class='ra-chip dark'>⚫ n/a</span>"

if len(fdf) == 0:
    st.info("No entries match your filters.")
else:
    if view == "Table view":
        # ---- Clean, human labels for the table
        df_disp = fdf[[
            "country","region","ailment","plant_common","plant_scientific","preparation",
            "evidence_badge","caution_flag","tradition_notes","cautions","source_url"
        ]].rename(columns={
            "country": "Country",
            "region": "Region",
            "ailment": "Symptom",
            "plant_common": "Plant",
            "plant_scientific": "Scientific name",
            "preparation": "Preparation",
            "evidence_badge": "Evidence",
            "caution_flag": "⚠︎",
            "tradition_notes": "Notes",
            "cautions": "Cautions",
            "source_url": "Source"
        })
        st.dataframe(
            df_disp.reset_index(drop=True),
            width="stretch",
            hide_index=True,
            column_config={
                "Source": st.column_config.LinkColumn("Source", display_text="Open"),
                "Evidence": st.column_config.TextColumn("Evidence", help="Evidence snapshot (not medical advice)"),
                "⚠︎": st.column_config.TextColumn("⚠︎", help="Important caution flags"),
                "Scientific name": st.column_config.TextColumn("Scientific name"),
            }
        )
    else:
        # ---- Card view
        for _, r in fdf.sort_values(["country","plant_scientific"]).iterrows():
            st.markdown(
                f"""
                <div class="ra-card">
                  <div class="ra-top">
                    <span class="ra-country">{r['country']}</span>
                    <span class="ra-chip">{r['region']}</span>
                    <span class="ra-chip">🩺 {r['ailment']}</span>
                    {_evidence_chip(r.get('evidence_level',''))}
                    {("<span class='ra-chip'>⚠︎ caution</span>" if r.get('caution_flag','—')=='⚠️' else "")}
                  </div>
                  <div><span class="ra-plant">{r['plant_common']}</span> <i>({r['plant_scientific']})</i> — {r['preparation']}</div>
                  {f"<div class='ra-note'>{r['tradition_notes']}</div>" if r.get('tradition_notes') else ""}
                  {f"<div class='ra-caution'>⚠︎ {r['cautions']}</div>" if r.get('cautions') else ""}
                  <div class="ra-actions">
                    <a href="{r['source_url']}" target="_blank" rel="noopener">Source ↗</a>
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

st.markdown(
    """
    ---
    <div style='text-align: center; color: #a0a0a0; font-size: 0.9em; margin-top: 2em;'>
        © 2025 <b>RemedyAtlas</b> — Educational showcase of traditional remedies.<br>
        <i>Developed by <b>Rouba Kiprianos</b></i><br>
        <span style='font-size:0.8em;'>Not intended as medical advice.</span>
    </div>
    """,
    unsafe_allow_html=True,
)
