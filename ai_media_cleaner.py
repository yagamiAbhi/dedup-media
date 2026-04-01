import streamlit as st
from pathlib import Path
from PIL import Image
import imagehash
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from send2trash import send2trash

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except:
    pass


st.set_page_config(layout="wide")

SIMILARITY_THRESHOLD = 8
MAX_THREADS = os.cpu_count()
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}


# ---------- SESSION ---------- #

if "duplicates" not in st.session_state:
    st.session_state.duplicates = None

if "selected_files" not in st.session_state:
    st.session_state.selected_files = set()


# ---------- HASH ---------- #

def file_hash(path):
    hasher = hashlib.blake2b(digest_size=16)

    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)

    return hasher.hexdigest()


def perceptual_hash(path):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except:
        return None


# ---------- SCAN WITH PROGRESS ---------- #

def scan_folder(folder):

    files = [f for f in Path(folder).rglob("*") if f.suffix.lower() in IMAGE_EXT]

    progress = st.progress(0)
    status = st.empty()

    duplicates = []

    total_steps = len(files) * 2
    step = 0

    # ---------- EXACT ---------- #

    size_map = {}

    for f in files:
        size_map.setdefault(f.stat().st_size, []).append(f)

    suspicious = [g for g in size_map.values() if len(g) > 1]

    hash_map = {}

    status.text("Checking exact duplicates...")

    for group in suspicious:
        for f in group:

            h = file_hash(f)
            hash_map.setdefault(h, []).append(f)

            step += 1
            progress.progress(step / total_steps)

    for group in hash_map.values():
        if len(group) > 1:
            duplicates.append(("Exact Duplicate", group))

    # ---------- SIMILAR ---------- #

    status.text("Checking visually similar images...")

    phashes = {}

    for f in files:

        ph = perceptual_hash(f)
        if ph:
            phashes[f] = ph

        step += 1
        progress.progress(step / total_steps)

    visited = set()
    file_list = list(phashes.keys())

    for i in range(len(file_list)):

        if file_list[i] in visited:
            continue

        group = [file_list[i]]

        for j in range(i + 1, len(file_list)):

            if file_list[j] in visited:
                continue

            diff = phashes[file_list[i]] - phashes[file_list[j]]

            if diff <= SIMILARITY_THRESHOLD:
                group.append(file_list[j])
                visited.add(file_list[j])

        if len(group) > 1:
            duplicates.append(("Visually Similar", group))

    progress.empty()
    status.empty()

    return duplicates


# ---------- UI ---------- #

st.title("🔥 AI Media Cleaner")

folder = st.text_input("Enter media folder path")

if st.button("SCAN FOR DUPLICATES") and folder:

    with st.spinner("Scanning media..."):

        st.session_state.duplicates = scan_folder(folder)
        st.session_state.selected_files.clear()

    st.success(f"Found {len(st.session_state.duplicates)} duplicate groups!")


# ---------- BULK DELETE ---------- #

if st.session_state.selected_files:

    existing_files = [f for f in st.session_state.selected_files if Path(f).exists()]

    total_size = sum(Path(f).stat().st_size for f in existing_files)

    st.warning(f"{len(existing_files)} files selected")
    st.info(f"💾 Storage to recover: {round(total_size/1024/1024,2)} MB")

    if st.button("🚨 DELETE SELECTED FILES"):

        for file in existing_files:
            send2trash(file)

        st.session_state.selected_files.clear()

        # CLEAN DUPLICATE LIST
        cleaned_duplicates = []

        for reason, group in st.session_state.duplicates:

            filtered = [f for f in group if f.exists()]

            if len(filtered) > 1:
                cleaned_duplicates.append((reason, filtered))

        st.session_state.duplicates = cleaned_duplicates

        st.success("Files moved to Recycle Bin!")
        st.rerun()


# ---------- DISPLAY ---------- #

if st.session_state.duplicates:

    for group_index, (reason, group) in enumerate(st.session_state.duplicates):

        st.divider()
        st.subheader(reason)

        cols = st.columns(len(group))

        for file_index, (col, file) in enumerate(zip(cols, group)):

            if not file.exists():
                continue

            unique_key = f"{group_index}_{file_index}"

            with col:

                try:
                    img = Image.open(file)
                    st.image(img, use_container_width=True)
                except:
                    st.write("Preview not supported")

                st.write(f"📁 {file.name}")
                st.write(f"💾 {round(file.stat().st_size/1024/1024,2)} MB")

                selected = st.checkbox(
                    "Select",
                    key=unique_key,
                    value=str(file) in st.session_state.selected_files
                )

                if selected:
                    st.session_state.selected_files.add(str(file))
                else:
                    st.session_state.selected_files.discard(str(file))
