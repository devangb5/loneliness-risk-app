import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
import branca.colormap as cm
from streamlit_folium import st_folium
import tempfile
import os
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
        if sheet == "DemographicFactorData":
            df = pd.read_excel(EXCEL_FILE, sheet_name=sheet, skiprows=1, nrows=215)
        else:
            df = pd.read_excel(EXCEL_FILE, sheet_name=sheet)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "")
        if "tractid" in df.columns:
            df["tractid"] = df["tractid"].astype(str).str.strip().str.replace("1400000US", "", regex=False)
        else:
            st.warning(f"Sheet {sheet} is missing 'tractid' column after cleaning.")
        sheet_dfs[sheet] = df
    return sheet_dfs

@st.cache_data
def load_tracts():
    url = "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_21_tract.zip"

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tracts.zip")

        # Download ZIP
        with open(zip_path, "wb") as f:
            f.write(requests.get(url).content)

        # Unzip
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        # Find the .shp file
        shp_file = [f for f in os.listdir(tmpdir) if f.endswith(".shp")][0]
        shp_path = os.path.join(tmpdir, shp_file)

        # Read into GeoDataFrame
        gdf_tracts = gpd.read_file(shp_path)
        gdf_tracts = gdf_tracts[gdf_tracts['COUNTYFP'] == '111']
        gdf_tracts["tractid_short"] = gdf_tracts["GEOID"]
        return gdf_tracts.to_crs(epsg=4326)

def calculate_weighted_risk_index(df, weights):
    df_clean = df.copy()
    valid_cols = [col for col in weights if col in df_clean.columns and weights[col] > 0]
    if not valid_cols or sum(weights[col] for col in valid_cols) == 0:
        st.warning("No valid columns selected or all weights are zero.")
        df_clean["risk_index"] = None
        return df_clean

    weighted_sum = sum(df_clean[col] * weights[col] for col in valid_cols)
    total_weight = sum(weights[col] for col in valid_cols)
    df_clean["risk_index"] = weighted_sum / total_weight
    return df_clean

def main():
    st.set_page_config(layout="wide")
    st.title("📍 Interactive Loneliness Risk Index – Jefferson County, KY")

    sheet_dfs = load_excel_sheets()
    gdf_tracts = load_tracts()

    st.sidebar.header("1️⃣ Select Sheets and Columns")

    selected_sheets = st.sidebar.multiselect(
        "Sheets to Include in Risk Index", SHEETS_TO_USE, default=SHEETS_TO_USE
    )

    st.sidebar.markdown("2️⃣ Assign Weights (Default is 1.0)")
    selected_cols = []
    weights = {}

    for sheet in selected_sheets:
        df = sheet_dfs[sheet]
        st.sidebar.markdown(f"**{sheet}**")
        for col in df.columns:
            if col in ["tractid", "tractid_short"]:
                continue
            col_id = f"{sheet}::{col}"
            include = st.sidebar.checkbox(f"➤ {col}", value=False, key=f"check_{col_id}")
            if include:
                selected_cols.append((sheet, col))
                weights[col] = st.sidebar.slider(f"Weight for {col}", 0.0, 10.0, 1.0, 0.5, key=f"weight_{col_id}")

    base_df = gdf_tracts[["tractid_short", "geometry"]].copy()
    merged_df = base_df.copy()

    for sheet in selected_sheets:
        df = sheet_dfs[sheet]
        if "tractid" not in df.columns:
            st.warning(f"Sheet {sheet} skipped – no 'tractid' column found.")
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
                    'fillColor': colormap(feature['properties']['risk_index']) if feature['properties']['risk_index'] is not None else 'gray',
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
        else:
            st.warning("Risk index could not be calculated.")

        st.subheader("🗺️ Map of Loneliness Risk Index")
        st_folium(m, width=1400, height=850)

        st.subheader("📊 Risk Index Table")
        show_cols = ["tractid_short"] + [col for _, col in selected_cols] + ["risk_index"]
        st.dataframe(merged_df[[col for col in show_cols if col in merged_df.columns]])
    else:
        st.info("Please select at least one column and assign a weight.")

if __name__ == "__main__":
    main()
