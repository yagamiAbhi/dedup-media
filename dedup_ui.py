import streamlit as st
import pandas as pd
from PIL import Image
from pathlib import Path

st.set_page_config(layout="wide")

st.title("📸 AI Media Dedup – Review Console")

csv_path = st.text_input(
    "Enter path to dedup_report.csv",
)

if csv_path:

    df = pd.read_csv(csv_path)

    if "NO DUPLICATES FOUND" in df.iloc[0].to_string():
        st.success("No duplicates detected 🎉")
        st.stop()

    folder = Path(csv_path).parent.parent  # original folder

    st.sidebar.header("Filters")

    reason_filter = st.sidebar.multiselect(
        "Filter by Reason",
        options=df["Reason"].unique(),
        default=df["Reason"].unique()
    )

    df = df[df["Reason"].isin(reason_filter)]

    st.write(f"### Showing {len(df)} comparisons")

    for _, row in df.iterrows():

        kept_path = folder / row["Kept File"]
        removed_path = folder / row["Removed File"]

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### ✅ Kept")

            if kept_path.exists():
                try:
                    img = Image.open(kept_path)
                    st.image(img, use_container_width=True)
                except:
                    st.warning("Preview not supported")

            st.write(f"**Name:** {row['Kept File']}")
            st.write(f"**Size:** {round(row['Kept Size(bytes)']/1024/1024,2)} MB")

        with col2:
            st.markdown("### ❌ Removed / Variant")

            if removed_path.exists():
                try:
                    img = Image.open(removed_path)
                    st.image(img, use_container_width=True)
                except:
                    st.warning("Preview not supported")

            st.write(f"**Name:** {row['Removed File']}")
            st.write(f"**Size:** {round(row['Removed Size(bytes)']/1024/1024,2)} MB")

        st.info(f"Reason: {row['Reason']}")

        st.divider()