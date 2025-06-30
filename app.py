import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
import branca.colormap as cm
from streamlit_folium import st_folium
import tempfile
import os
import zipfile
import requests

EXCEL_FILE = "factors.xlsx"
SHEETS_TO_USE = [
    "DemographicFactorData",
    "ClinicalFactorData",
    "PlaceFactorData",
    "BehavorialFactorData",
    "NeighborhoodChange",
    "SafetyConcerns",
    "CommunityEngagement",
    "ExposureToNature"
]

@st.cache_data
def load_excel_sheets():
    sheet_dfs = {}
    for sheet in SHEETS_TO_USE:
        try:
            if sheet == "DemographicFactorData":
                df = pd.read_excel(EXCEL_FILE, sheet_name=sheet, skiprows=1, nrows=215)
            else:
                df = pd.read_excel(EXCEL_FILE, sheet_name=sheet)

            df.columns = df.columns.str.strip().str.lower().str.replace(" ", "")
            if "tractid" in df.columns:
                df["tractid"] = df["tractid"].astype(str).str.replace("1400000US", "", regex=False).str.strip()
                sheet_dfs[sheet] = df
            else:
                st.warning(f"Sheet **{sheet}** is missing a 'tractid' column. Skipped.")
        except Exception as e:
            st.warning(f"Could not load sheet '{sheet}': {e}")
    return sheet_dfs

@st.cache_data
def load_tracts():
    url = "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_21_tract.zip"
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tracts.zip")
        shp_path = None

        try:
            response = requests.get(url, verify=False, timeout=30)
            with open(zip_path, "wb") as f:
                f.write(response.content)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(tmpdir)
                for f in zip_ref.namelist():
                    if f.endswith(".shp"):
                        shp_path = os.path.join(tmpdir, f)

            gdf = gpd.read_file(shp_path)
            gdf = gdf[gdf["COUNTYFP"] == "111"]  # Jefferson County
            gdf["tractid_short"] = gdf["GEOID"]
            return gdf.to_crs(epsg=4326)
        except Exception as e:
            st.error(f"Failed to load tract shapefile: {e}")
            return gpd.GeoDataFrame()

def calculate_weighted_risk_index(df, weights):
    df_clean = df.copy()
    valid_cols = [col for col in weights if col in df_clean.columns and weights[col] > 0]
    if not valid_cols:
        st.warning("No valid columns selected or all weights are zero.")
        df_clean["risk_index"] = None
        return df_clean

    weighted_sum = sum(df_clean[col] * weights[col] for col in valid_cols)
    total_weight = sum(weights[col] for col in valid_cols)
    df_clean["risk_index"] = weighted_sum / total_weight
    return df_clean

def main():
    st.set_page_config(layout="wide")
    st.title("📍 Loneliness Risk Index Explorer – Jefferson County, KY")

    sheet_dfs = load_excel_sheets()
    gdf_tracts = load_tracts()
    if gdf_tracts.empty:
        return

    st.sidebar.header("Step 1: Choose Data")
    selected_sheets = st.sidebar.multiselect("Sheets to Include", list(sheet_dfs.keys()), default=list(sheet_dfs.keys()))

    st.sidebar.header("Step 2: Select Columns & Assign Weights")
    selected_cols = []
    weights = {}

    for sheet in selected_sheets:
        df = sheet_dfs[sheet]
        st.sidebar.markdown(f"**{sheet}**")
        for col in df.columns:
            if col in ["tractid", "tractid_short"]:
                continue
            col_id = f"{sheet}::{col}"
            if st.sidebar.checkbox(f"➤ {col}", key=f"check_{col_id}"):
                selected_cols.append((sheet, col))
                weights[col] = st.sidebar.slider(f"Weight for {col}", 0.0, 10.0, 1.0, 0.5, key=f"weight_{col_id}")

    base_df = gdf_tracts[["tractid_short", "geometry"]].copy()
    merged_df = base_df.copy()

    for sheet in selected_sheets:
        df = sheet_dfs[sheet]
        if "tractid" not in df.columns:
            continue
        merged_df = merged_df.merge(df, left_on="tractid_short", right_on="tractid", how="left", suffixes=("", f"_{sheet.lower()}"))

    if weights:
        merged_df = calculate_weighted_risk_index(merged_df, weights)

        m = folium.Map(location=[38.25, -85.75], zoom_start=11, width="100%", height="100%")

        if merged_df["risk_index"].notnull().any():
            vmin = merged_df["risk_index"].min()
            vmax = merged_df["risk_index"].max()
            colormap = cm.LinearColormap(['green', 'yellow', 'red'], vmin=vmin, vmax=vmax, caption='Loneliness Risk Index')
            colormap.add_to(m)

            folium.GeoJson(
                merged_df,
                style_function=lambda feature: {
                    'fillColor': colormap(feature['properties'].get("risk_index", 0)) if feature['properties'].get("risk_index") is not None else 'gray',
                    'color': 'black',
                    'weight': 0.5,
                    'fillOpacity': 0.7,
                },
                tooltip=GeoJsonTooltip(
                    fields=["tractid_short", "risk_index"],
                    aliases=["Tract ID", "Loneliness Risk Index"],
                    localize=True
                )
            ).add_to(m)

            st.subheader("🗺️ Loneliness Risk Index Map")
            st_folium(m, width=1400, height=850)

            st.subheader("📊 Data Table")
            display_cols = ["tractid_short"] + [col for _, col in selected_cols] + ["risk_index"]
            st.dataframe(merged_df[[col for col in display_cols if col in merged_df.columns]])
        else:
            st.warning("Risk index could not be calculated from selected columns.")
    else:
        st.info("Please select at least one column and assign a weight.")

if __name__ == "__main__":
    main()
