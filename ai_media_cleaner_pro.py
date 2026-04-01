import streamlit as st
from pathlib import Path
from PIL import Image
import imagehash
from send2trash import send2trash
import os

st.set_page_config(layout="wide")

st.title("🔥 AI Media Cleaner")

# ---------- SESSION STATE ---------- #

if "duplicates" not in st.session_state:
    st.session_state.duplicates = []

if "selected_files" not in st.session_state:
    st.session_state.selected_files = set()

if "scan_done" not in st.session_state:
    st.session_state.scan_done = False


# ---------- FOLDER PICKER ---------- #
# ---------- NATIVE FOLDER PICKER ---------- #

import tkinter as tk
from tkinter import filedialog


def browse_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    folder_selected = filedialog.askdirectory()

    root.destroy()

    return folder_selected


st.subheader("Select Folder")

if "folder_path" not in st.session_state:
    st.session_state.folder_path = ""

col1, col2 = st.columns([3,1])

with col1:
    st.text_input(
        "Folder Path",
        value=st.session_state.folder_path,
        disabled=True,
        label_visibility="collapsed"
    )

with col2:
    if st.button("📂 Browse"):
        folder = browse_folder()
        if folder:
            st.session_state.folder_path = folder
            st.session_state.scan_done = False
            st.session_state.selected_files.clear()
            st.rerun()


folder = Path(st.session_state.folder_path) if st.session_state.folder_path else None


# ---------- DELETE PANEL (TOP) ---------- #

selected_count = len(st.session_state.selected_files)

if selected_count > 0:

    valid_files = [
        Path(f) for f in st.session_state.selected_files
        if Path(f).exists()
    ]

    total_size = sum(f.stat().st_size for f in valid_files)

    st.error(f"🚨 {selected_count} files selected for deletion")
    st.info(f"💾 Storage recovery: {round(total_size/1024/1024,2)} MB")

    if st.button("DELETE SELECTED FILES"):

        for file in valid_files:
            send2trash(str(file))

        st.session_state.selected_files.clear()

        # Clean duplicate groups
        cleaned = []
        for reason, group in st.session_state.duplicates:
            remaining = [f for f in group if f.exists()]
            if len(remaining) > 1:
                cleaned.append((reason, remaining))

        st.session_state.duplicates = cleaned

        st.success("Files moved to Recycle Bin!")
        st.rerun()


# ---------- SCAN BUTTON ---------- #

if st.button("SCAN FOR DUPLICATES"):

    if not folder:
        st.warning("Please select a folder first.")
        st.stop()

    image_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

    files = [
        f for f in folder.rglob("*")
        if f.suffix.lower() in image_extensions
    ]

    progress = st.progress(0)
    percent = st.empty()

    hashes = {}
    duplicates = []

    total = len(files)

    for i, file in enumerate(files):

        try:
            img = Image.open(file)
            h = imagehash.phash(img)

            if h in hashes:
                duplicates.append(("Visually Similar", [hashes[h], file]))
            else:
                hashes[h] = file

        except:
            continue

        progress.progress((i+1)/total)
        percent.write(f"Scanning: {int((i+1)/total*100)}%")

    st.session_state.duplicates = duplicates
    st.session_state.scan_done = True
    st.success(f"Found {len(duplicates)} duplicate groups!")
    st.rerun()


# ---------- DUPLICATE VIEW ---------- #

if st.session_state.scan_done:

    st.header("Visually Similar")

    for group_index, (reason, files) in enumerate(st.session_state.duplicates):

        st.divider()
        st.subheader(reason)

        cols = st.columns(5)  # ALWAYS 5 GRID

        for idx, file in enumerate(files):

            if not file.exists():
                continue

            col = cols[idx % 5]

            with col:

                try:
                    img = Image.open(file)
                    st.image(img, use_container_width=True)
                except:
                    st.write("Preview not supported")

                st.caption(file.name)
                st.caption(f"{round(file.stat().st_size/1024/1024,2)} MB")

                key = f"{group_index}_{idx}_{file}"

                previous_count = len(st.session_state.selected_files)

                selected = st.checkbox(
                    "Select",
                    key=key,
                    value=str(file) in st.session_state.selected_files
                )

                if selected:
                    st.session_state.selected_files.add(str(file))
                else:
                    st.session_state.selected_files.discard(str(file))

                # 🔥 THIS FIXES DELETE BUTTON DELAY
                if len(st.session_state.selected_files) != previous_count:
                    st.rerun()
