import streamlit as st
import rasterio
import numpy as np
import geopandas as gpd
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import tempfile
import os

from matplotlib.colors import LightSource
from matplotlib.ticker import FuncFormatter, MaxNLocator
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import LineString, MultiLineString
from pyproj import Transformer, CRS
from io import BytesIO

# =========================================
# PAGE CONFIG
# =========================================

st.set_page_config(
    page_title="GeoProfiler",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# TITLE
# ========================================

col1, col2 = st.columns([12, 1])

with col1:
    st.title("🌍 GeoProfiler")

with col2:
    with st.popover("ℹ"):
        st.markdown("""
        ### GeoProfiler Documentation

GeoProfiler is an open-source web application for extracting and visualizing topographic profiles from Digital Elevation Models (DEMs).
                    
The application supports both line and swath profile generation and provides profile exports in PNG, PDF, and CSV formats for further analysis and reporting.
                    
It integrates DEM visualization, hillshade rendering, profile extraction, and data export within a single workflow.
                    
GeoProfiler was developed to streamline the extraction and visualization of topographic profiles, reducing repetitive manual processing when working 
with multiple profile lines and large terrain datasets.

#### Features
* DEM visualization with hillshade
* Line profile generation
* Swath profile generation
* Automatic vector reprojection
* PNG, PDF and CSV exports
                
#### DEM Requirements

* DEMs must use a **projected coordinate reference system (CRS)** (e.g., UTM or other projected CRS with metric units).
* Geographic coordinate systems such as WGS84 (latitude/longitude) are not recommended because profile distances and 
swath widths require linear units for accurate terrain analysis.
* Elevation values are recommended to be in **meters**.
* GeoProfiler assumes the uploaded raster represents elevation data.
* Hydrologically corrected or filled DEMs are recommended for river and drainage profile analysis.
                    
#### Supported Vector Data

GeoProfiler accepts linear features representing the profile path.

Supported geometry types:

* LineString
* MultiLineString

Supported formats:

* GeoJSON (.geojson)
* Shapefile (.shp, .shx, .dbf, .prj)

Note: All Shapefile components must be uploaded together. The .prj file is required for CRS detection and automatic reprojection.

Example Profile Features:

* River and stream centerlines
* Topographic cross-sections 
* Geological fault profiles
* Escarpment and ridge profiles

#### Coordinate Reference Systems (CRS)

* If the vector dataset and DEM use different coordinate reference systems, GeoProfiler automatically reprojects the vector data to match the DEM CRS.
* DEM reprojection is not performed automatically.
* For best results, ensure that the DEM is already provided in an appropriate projected CRS.

#### Profile Types

**Line Profile**

* Extracts elevation values directly along a user-defined profile line.
* Suitable for river longitudinal profiles, terrain cross-sections, and fault profiling.

**Swath Profile**

* Extracts minimum, mean, and maximum elevation statistics within a user-defined corridor around the profile line.
* Useful for valley analysis, terrain characterization, and geomorphological investigations.

#### Outputs

Generated profiles can be exported as:

* PNG — high-quality image output
* PDF — publication-ready vector graphics
* CSV — profile data for further analysis in GIS, Excel, MATLAB, Python, or other software

#### Applications

* River longitudinal profiling
* Terrain and geomorphological analysis
* Fault and escarpment investigations
* Watershed and drainage studies
* Infrastructure and route planning
                    
        """)

# =========================================
# SIDEBAR
# =========================================

st.sidebar.header("GeoProfiler Controls")

# DEM Upload
dem_file = st.sidebar.file_uploader(
    "Upload DEM Raster (Projected CRS, e.g., UTM)",
    type=["tif", "tiff"]
)

if dem_file is not None:

    if "last_dem" not in st.session_state:
        st.session_state["last_dem"] = dem_file.name

    if st.session_state["last_dem"] != dem_file.name:

        st.session_state["run_profile"] = False
        st.session_state["last_dem"] = dem_file.name

# SHAPEFILE UPLOAD
shape_files = st.sidebar.file_uploader(
    "Upload Shapefile Components",
    type=["shp", "shx", "dbf", "prj", "geojson", "json"],
    accept_multiple_files=True
)

selected_shp = None

if shape_files:

    geojson_files = [
        f.name
        for f in shape_files
        if f.name.endswith((".geojson", ".json"))
    ]

    shp_files = [
        f.name
        for f in shape_files
        if f.name.endswith(".shp")
    ]

    if len(shp_files) == 0 and len(geojson_files) == 0:
        st.sidebar.warning(
            "Please upload a valid .shp or .geojson file."
        )

        st.stop()
    
    elif len(geojson_files) > 0:
        
        selected_shp = st.sidebar.selectbox(
            "Select GeoJSON for profiling",
            geojson_files
        )

    else:

        selected_shp = st.sidebar.selectbox(
            "Select shapefile for profiling",
            shp_files
        )


        # RESET PROFILE WHEN SHAPEFILE CHANGES
        if "last_shp" not in st.session_state:
            st.session_state["last_shp"] = selected_shp

        if st.session_state["last_shp"] != selected_shp:

            st.session_state["run_profile"] = False
            st.session_state["last_shp"] = selected_shp


        if selected_shp.endswith(".shp"):
            
            base_name = selected_shp.replace(".shp", "")

            required_files = [
                f"{base_name}.shp",
                f"{base_name}.shx",
                f"{base_name}.dbf",
                f"{base_name}.prj"
            ]

            uploaded_names = [f.name for f in shape_files]

            missing = [
                f for f in required_files
                if f not in uploaded_names
            ]

            if missing:
                
                st.error(
                    f"Missing shapefile components: {', '.join(missing)}"
                )

                st.info(
                    "Please upload .shp, .shx, .dbf and .prj files."
                )

                st.stop()

# Profile Type
profile_type = st.sidebar.selectbox(
    "Profile Type",
    ["line", "swath"]
)

# Swath Width
swath_width = st.sidebar.number_input(
    "Swath Width (meters)",
    min_value=10,
    max_value=10000,
    value=600,
    step=100
)

swath_width = st.sidebar.slider(
    "Adjust Swath Width",
    10,
    10000,
    int(swath_width)
)

# Smoothing
smooth_sigma = st.sidebar.number_input(
    "Profile Smoothing",
    min_value=1,
    max_value=50,
    value=5,
    step=1
)

smooth_sigma = st.sidebar.slider(
    "Adjust Smoothing",
    1,
    50,
    int(smooth_sigma)
)

current_settings = (
    profile_type,
    swath_width,
    smooth_sigma
)

if "previous_settings" not in st.session_state:
    st.session_state["previous_settings"] = current_settings

if current_settings != st.session_state["previous_settings"]:
    st.session_state["run_profile"] = False
    st.session_state["previous_settings"] = current_settings

# =========================================
# VECTOR / PUBLICATION SETTINGS
# =========================================
matplotlib.rcParams['pdf.fonttype'] = 42

# =========================================
# MAIN
# =========================================

# =========================================
# CACHE HILLSHADE
# =========================================

@st.cache_data
def generate_hillshade(display_dem, dx, dy):

    ls = LightSource(
        azdeg=315,
        altdeg=45
    )

    hillshade = ls.hillshade(
        display_dem,
        vert_exag=1,
        dx=dx,
        dy=dy
    )

    return hillshade

if dem_file:

    # =====================================
    # READ DEM
    # =====================================

    src = rasterio.open(dem_file)

    if CRS(src.crs).is_geographic:
        st.error(
            "Please upload a DEM in a projected CRS (e.g., UTM)."
        )
        st.stop()

    dem = src.read(1)

    nodata = src.nodata

    if nodata is not None:
        dem = np.where(dem == nodata, np.nan, dem)

    # =====================================
    # DISPLAY DEM DOWNSAMPLING
    # =====================================

    display_step = 4

    display_dem = dem[::display_step, ::display_step]

    # =====================================
    # HILLSHADE
    # =====================================

    hillshade = generate_hillshade(
        display_dem,
        src.res[0] * display_step,
        src.res[1] * display_step
    )

    # =====================================
    # SHAPEFILE HANDLING
    # =====================================

    shp_path = None
    gdf = None

    if shape_files:

        temp_dir = tempfile.mkdtemp()

        for uploaded_file in shape_files:

            temp_file_path = os.path.join(
                temp_dir,
                uploaded_file.name
            )

            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
       
        shp_path = os.path.join(
            temp_dir,
            selected_shp
        )

        if shp_path is not None:

            gdf = gpd.read_file(shp_path)

            # Check empty shapefile
            if gdf.empty:
                st.error("Invalid or empty shapefile.")
                st.stop()

            if gdf.crs is None:
                st.error(
                    "Shapefile has no Coordinate Reference System (CRS). Please define projection before upload."
                )
                
                st.stop()

            if gdf.crs != src.crs:
                gdf = gdf.to_crs(src.crs)

    # =====================================
    # EXTENT
    # =====================================

    extent = [
        src.bounds.left,
        src.bounds.right,
        src.bounds.bottom,
        src.bounds.top
    ]

    # =====================================
    # COORDINATE FORMATTER
    # =====================================

    transformer = Transformer.from_crs(
        src.crs,
        "EPSG:4326",
        always_xy=True
    )

    def format_lon(x, pos):

        lon, lat = transformer.transform(
            x,
            extent[2]
        )

        deg = int(lon)
        minutes = int(abs(lon - deg) * 60)

        return f"{deg}°{minutes:02d}'E"

    def format_lat(y, pos):

        lon, lat = transformer.transform(
            extent[0],
            y
        )

        deg = int(lat)
        minutes = int(abs(lat - deg) * 60)

        return f"{deg}°{minutes:02d}'N"

    # =====================================
    # DEM DISPLAY
    # =====================================

    st.subheader("DEM + Hillshade")

    fig, ax = plt.subplots(
        figsize=(5.8, 3.0),
        dpi=160
    )

    # Hillshade
    ax.imshow(
        hillshade,
        cmap="gray",
        extent=extent,
        alpha=0.7
    )

    # DEM
    img = ax.imshow(
        display_dem,
        cmap="terrain",
        extent=extent,
        alpha=0.8
    )

    # PROFILE LINES
    if gdf is not None:

        gdf.plot(
            ax=ax,
            color="whitesmoke",
            linewidth=0.5,
            alpha=0.9
        )

    # =====================================
    # ARCMap-style coordinates
    # =====================================

    # Longitude ticks
    ax.xaxis.set_major_locator(MaxNLocator(4))

    # Latitude ticks (ONLY 3)
    ax.yaxis.set_major_locator(MaxNLocator(3))

    # Formatters
    ax.xaxis.set_major_formatter(
        FuncFormatter(format_lon)
    )

    ax.yaxis.set_major_formatter(
        FuncFormatter(format_lat)
    )

    # Rotate latitude labels vertically
    for label in ax.get_yticklabels():
        
        label.set_rotation(90)
        label.set_verticalalignment("center")
        label.set_horizontalalignment("center")

    # AXIS STYLING
    ax.tick_params(
        axis='x',
        labelsize=4
    )

    ax.tick_params(
        axis='y',
        labelsize=4,
        pad=3
    )

    # Remove axis labels
    ax.set_xlabel("")
    ax.set_ylabel("")
    
    # FIGURE LAYOUT
    fig.subplots_adjust(
        left=0.08,
        right=0.8,
        top=0.8,
        bottom=0.12
    )

    cbar = fig.colorbar(
        img,
        ax=ax,
        fraction=0.15,   # thinner bar
        pad=0.02,        # closer to DEM
        shrink=1.0       # shorter height
    )

    # Smaller label
    cbar.set_label(
        "Elevation (m)",
        fontsize=6,
        labelpad=2
    )

    # Smaller tick values
    cbar.ax.tick_params(
        labelsize=4,
        width=0.6,
        length=3
    )

    # Thin border
    cbar.outline.set_linewidth(0.8)

    # Display DEM
    st.pyplot(fig)
    plt.close(fig)

    # =====================================
    # STATS
    # =====================================

    st.subheader("Elevation Statistics")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Minimum",
        f"{np.nanmin(dem):.1f} m"
    )

    col2.metric(
        "Maximum",
        f"{np.nanmax(dem):.1f} m"
    )

    col3.metric(
        "Mean",
        f"{np.nanmean(dem):.1f} m"
    )

    # =====================================
    # PROFILE GENERATION
    # =====================================

    if gdf is not None:

        generate = st.button("Generate Profile")

        if generate:
            st.session_state["run_profile"] = True

        if st.session_state.get("run_profile", False):

            dx = src.res[0]
            
            # VALIDATE LINE GEOMETRY
            valid_geometries = [
                "LineString",
                "MultiLineString"
            ]

            if not all(
                geom.geom_type in valid_geometries
                for geom in gdf.geometry
            ):
                st.error(
                    "Please upload line-based shapefiles (LineString or MultiLineString)."
                )
                st.stop()

            for idx, geom in enumerate(gdf.geometry):

                st.caption(f"Processing profile {idx+1}")

                # =================================
                # HANDLE GEOMETRY
                # =================================

                if isinstance(geom, MultiLineString):

                    line = max(
                        geom.geoms,
                        key=lambda g: g.length
                    )

                elif isinstance(geom, LineString):

                    line = geom

                else:
                    continue

                # =================================
                # SAMPLE CENTERLINE
                # =================================

                distances = np.arange(
                    0,
                    line.length,
                    dx
                )

                points = [
                    line.interpolate(d)
                    for d in distances
                ]
      
                # Skip very short profiles
                if len(points) < 2:
                    
                    st.warning(
                        f"Skipping very short profile {idx+1}"
                    )
                    
                    continue

                xy = [
                    (p.x, p.y)
                    for p in points
                ]

                # =================================
                # LINE PROFILE
                # =================================

                if profile_type == "line":

                    rows, cols = rasterio.transform.rowcol(
                        src.transform,
                         [p[0] for p in xy],
                         [p[1] for p in xy]
                    )

                    rows = np.array(rows)
                    cols = np.array(cols)

                    valid = (
                         (rows >= 0) &
                         (rows < dem.shape[0]) &
                         (cols >= 0) &
                         (cols < dem.shape[1])
                    )

                    elev = np.full(len(rows), np.nan)

                    elev[valid] = dem[
                        rows[valid],
                        cols[valid]
                    ].astype(float)

                    if nodata is not None:
                        elev[elev == nodata] = np.nan

                    nans = np.isnan(elev)

                    # Prevent crash if all values are NaN
                    if np.all(nans):
                        continue

                    if np.any(nans):

                        elev[nans] = np.interp(
                            np.flatnonzero(nans),
                            np.flatnonzero(~nans),
                            elev[~nans]
                        )
                    # Remove unrealistic negative elevations
                    elev[elev < -500] = np.nan

                    if np.all(np.isnan(elev)):
                       continue

                    elev = gaussian_filter1d(
                        elev,
                        sigma=smooth_sigma
                    )

                    distance_km = distances / 1000

                    fig2, ax2 = plt.subplots(
                        figsize=(8, 3)
                    )

                    ax2.plot(
                        distance_km,
                        elev,
                        color="black",
                        linewidth=1.5,
                    )

                    ax2.set_title(
                        f"Topographic Line Profile – Line {idx+1}",
                        fontsize=15
                    )

                    ax2.set_xlabel("Distance (km)")
                    ax2.set_ylabel("Elevation (m)")

                    ax2.grid(False)

                    plt.tight_layout()

                    plot_col, export_col = st.columns([9, 1])

                    with plot_col:
                        
                        st.pyplot(fig2)

                    # =================================
                    # EXPORTS
                    # =================================
                    
                    png = BytesIO()
                    pdf = BytesIO()
                    csv_buffer = BytesIO()

                    fig2.savefig(
                        png,
                        format="png",
                        dpi=300,
                        bbox_inches="tight"
                    )

                    # ==========================
                    # CSV EXPORT
                    # ==========================

                    profile_df = pd.DataFrame({
                        "Distance_km": distance_km,
                        "Elevation_m": elev
                    })

                    csv_buffer.write(
                        profile_df.to_csv(index=False).encode()
                    )

                    fig2.savefig(
                        pdf,
                        format="pdf",
                        bbox_inches="tight",
                        transparent=True
                    )

                    with export_col:
                        
                        st.caption("Download")

                        st.download_button(
                            "⬇ PNG",
                             png.getvalue(),
                             file_name=f"profile_line_{idx+1}.png",
                             use_container_width=True,
                             on_click="ignore"
                        )

                        st.download_button(
                            "⬇ CSV",
                            csv_buffer.getvalue(),
                            file_name=f"profile_line_{idx+1}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            on_click="ignore"
                        )

                        st.download_button(
                            "⬇ PDF",
                            pdf.getvalue(),
                            file_name=f"profile_line_{idx+1}.pdf",
                            use_container_width=True,
                            on_click="ignore"
                        )

                    plt.close(fig2)

                # =================================
                # SWATH PROFILE
                # =================================

                elif profile_type == "swath":

                    offsets = np.arange(
                        -swath_width/2,
                        swath_width/2 + dx,
                        dx
                    )

                    all_profiles = []

                    for off in offsets:

                        swath_xy = []

                        for i, p in enumerate(points):

                            if i == 0:

                                p1 = points[i]
                                p2 = points[i+1]

                            elif i == len(points)-1:

                                p1 = points[i-1]
                                p2 = points[i]

                            else:

                                p1 = points[i-1]
                                p2 = points[i+1]

                            tx = p2.x - p1.x
                            ty = p2.y - p1.y

                            norm = np.sqrt(tx**2 + ty**2)

                            if norm == 0:

                                swath_xy.append(
                                    (p.x, p.y)
                                )

                                continue

                            tx /= norm
                            ty /= norm

                            nx = -ty
                            ny = tx

                            x_off = p.x + off * nx
                            y_off = p.y + off * ny

                            swath_xy.append(
                                (x_off, y_off)
                            )

                        x_coords = [p[0] for p in swath_xy]
                        y_coords = [p[1] for p in swath_xy]

                        rows, cols = rasterio.transform.rowcol(
                            src.transform,
                             x_coords,
                             y_coords
                        )

                        rows = np.array(rows)
                        cols = np.array(cols)

                        valid = (
                            (rows >= 0) &
                            (rows < dem.shape[0]) &
                            (cols >= 0) &
                            (cols < dem.shape[1])
                        )

                        elev = np.full(len(rows), np.nan)

                        elev[valid] = dem[
                            rows[valid],
                            cols[valid]
                        ].astype(float)

                        if nodata is not None:
                            elev[elev == nodata] = np.nan

                        nans = np.isnan(elev)

                        # Prevent crash if all values are NaN
                        if np.all(nans):
                            continue

                        if np.any(nans):

                            elev[nans] = np.interp(
                                np.flatnonzero(nans),
                                np.flatnonzero(~nans),
                                elev[~nans]
                            )
                        # Remove unrealistic negative elevations
                        elev[elev < -500] = np.nan
                        
                        if np.all(np.isnan(elev)):
                            
                           continue

                        all_profiles.append(elev)
     
                    if len(all_profiles) == 0:
                        
                        st.warning(
                            
                            f"No valid swath data for profile {idx+1}"
                        )

                        continue

                    all_profiles = np.array(all_profiles)

                    swath_min = np.nanmin(
                        all_profiles,
                        axis=0
                    )

                    swath_mean = np.nanmean(
                        all_profiles,
                        axis=0
                    )

                    swath_max = np.nanmax(
                        all_profiles,
                        axis=0
                    )

                    swath_min = gaussian_filter1d(
                        swath_min,
                        sigma=smooth_sigma
                    )

                    swath_mean = gaussian_filter1d(
                        swath_mean,
                        sigma=smooth_sigma
                    )

                    swath_max = gaussian_filter1d(
                        swath_max,
                        sigma=smooth_sigma
                    )

                    distance_km = distances / 1000

                    fig2, ax2 = plt.subplots(
                        figsize=(8, 3)
                    )

                    ax2.fill_between(
                        distance_km,
                        swath_min,
                        swath_max,
                        color="lightgray",
                        alpha=0.8,
                        label="Min-Max"
                    )

                    ax2.plot(
                        distance_km,
                        swath_mean,
                        color="black",
                        linewidth=1.5,
                        label="Mean"
                    )

                    ax2.legend()

                    ax2.set_title(
                        f"Topographic Swath Profile – Line {idx+1}",
                        fontsize=15
                    )

                    ax2.set_xlabel("Distance (km)")
                    ax2.set_ylabel("Elevation (m)")

                    ax2.grid(False)

                    plt.tight_layout()

                    plot_col, export_col = st.columns([9, 1])
                    
                    with plot_col:
                        
                        st.pyplot(fig2)

                    # =================================
                    # EXPORTS
                    # =================================

                    png = BytesIO()
                    pdf = BytesIO()
                    csv_buffer = BytesIO()

                    fig2.savefig(
                        png,
                        format="png",
                        dpi=300,
                        bbox_inches="tight",
                        transparent=True
                    )

                    swath_df = pd.DataFrame({
                        "Distance_km": distance_km,
                        "Min_Elevation_m": swath_min,
                        "Mean_Elevation_m": swath_mean,
                        "Max_Elevation_m": swath_max
                    })

                    csv_buffer.write(
                        swath_df.to_csv(index=False).encode()
                    )

                    fig2.savefig(
                        pdf,
                        format="pdf",
                        bbox_inches="tight",
                        transparent=True
                    )
                
                    with export_col:
                        st.caption("Download")

                        st.download_button(
                            "⬇ PNG",
                            png.getvalue(),
                            file_name=f"profile_swath_{idx+1}.png",
                            use_container_width=True,
                            on_click="ignore"
                        )

                        st.download_button(
                            "⬇ CSV",
                            csv_buffer.getvalue(),
                            file_name=f"profile_swath_{idx+1}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            on_click="ignore"
                        )

                        st.download_button(
                            "⬇ PDF",
                            pdf.getvalue(),
                            file_name=f"profile_swath_{idx+1}.pdf",
                            use_container_width=True,
                            on_click="ignore"
                        )

                    plt.close(fig2)

    src.close()

else:

    st.info("Upload a DEM raster to begin.")

st.markdown("---")

with st.expander("About GeoProfiler"):
    
    st.markdown("""
    **GeoProfiler** is an open-source web application for extracting and visualizing topographic profiles from Digital Elevation Models (DEMs).

The application supports both line and swath profile generation and provides profile exports in PNG, PDF, and CSV formats for further analysis and reporting.            

Developed by **[Chandni Verma](https://www.linkedin.com/in/chandni-verma-geo/)**
                
🔗 **Source Code:** [GeoProfiler-WebApp Repository](https://github.com/chandnivermageo/GeoProfiler-WebApp)
""")