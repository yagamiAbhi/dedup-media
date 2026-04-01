import os
from pathlib import Path
from pillow_heif import register_heif_opener
register_heif_opener()
from PIL import Image
import imagehash
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import shutil
import hashlib
import csv
import logging
import re
import sys

MAX_THREADS = os.cpu_count()
SIMILARITY_THRESHOLD = 8
VARIANT_SIZE_DIFF = 0.30

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
RAW_EXT = {".dng", ".cr2", ".nef", ".arw", ".rw2"}


# ---------- LOGGING ---------- #

def setup_logging(output_dir):
    log_file = output_dir / "dedup_log.txt"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


# ---------- COPY NAME DETECTOR ---------- #

def is_copy_name(file):
    name = file.stem.lower()

    patterns = [
        r'copy',
        r'\(\d+\)',
        r'-\d+$',
        r'_\d+$'
    ]

    return any(re.search(p, name) for p in patterns)


# ---------- SMART PICK ---------- #

def pick_best(files):

    originals = [f for f in files if not is_copy_name(f)]
    if originals:
        files = originals

    largest = max(f.stat().st_size for f in files)
    largest_files = [f for f in files if f.stat().st_size == largest]

    if len(largest_files) == 1:
        winner = largest_files[0]
        logging.info(f"Winner selected: {winner.name}")
        return winner

    winner = min(largest_files, key=lambda f: f.stat().st_ctime)
    logging.info(f"Winner selected (oldest): {winner.name}")
    return winner


# ---------- HASH ---------- #

def file_hash(path):
    hasher = hashlib.blake2b(digest_size=16)

    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                hasher.update(chunk)

        return hasher.hexdigest()

    except Exception as e:
        logging.error(f"Hash failed for {path}: {e}")
        return None


# ---------- PERCEPTUAL HASH ---------- #

def perceptual_hash(path):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)

    except Exception:
        logging.warning(f"Skipping AI compare (unsupported image): {path}")
        return None


# ---------- MAIN ENGINE ---------- #

def ai_media_dedup(input_dir):

    input_path = Path(input_dir)
    output_dir = input_path.parent / f"{input_path.name}_AI_unique"
    output_dir.mkdir(exist_ok=True)

    setup_logging(output_dir)

    logging.info("Starting AI Media Deduplication")

    files = [f for f in input_path.rglob("*") if f.is_file()]
    logging.info(f"Total files found: {len(files)}")

    kept = []
    removed = []
    report_rows = []

    # ---------- RAW AUTO KEEP ---------- #

    raw_files = [f for f in files if f.suffix.lower() in RAW_EXT]

    for f in raw_files:
        kept.append(f)
        logging.info(f"RAW auto-kept: {f.name}")

    # remove RAW from pipeline
    files = [f for f in files if f.suffix.lower() not in RAW_EXT]

    # ---------- SIZE GROUP ---------- #

    size_groups = {}

    for f in files:
        size_groups.setdefault(f.stat().st_size, []).append(f)

    suspicious = [g for g in size_groups.values() if len(g) > 1]

    logging.info("Checking exact duplicates...")

    hash_groups = {}

    with ThreadPoolExecutor(MAX_THREADS) as executor:
        futures = {executor.submit(file_hash, f): f
                   for group in suspicious
                   for f in group}

        for future in tqdm(futures):
            f = futures[future]
            h = future.result()

            if h:
                hash_groups.setdefault(h, []).append(f)

    remaining_for_ai = []

    # ---------- EXACT ---------- #

    for group in hash_groups.values():

        if len(group) == 1:
            remaining_for_ai.append(group[0])
            continue

        winner = pick_best(group)
        kept.append(winner)

        for f in group:
            if f != winner:
                removed.append(f)

                report_rows.append([
                    winner.name,
                    winner.stat().st_size,
                    f.name,
                    f.stat().st_size,
                    "Exact Duplicate"
                ])

    # add true uniques
    for group in size_groups.values():
        if len(group) == 1:
            remaining_for_ai.append(group[0])

    # ---------- AI SIMILAR ---------- #

    logging.info("Detecting visually similar images...")

    image_files = [f for f in remaining_for_ai if f.suffix.lower() in IMAGE_EXT]
    non_images = [f for f in remaining_for_ai if f.suffix.lower() not in IMAGE_EXT]

    kept.extend(non_images)

    phashes = {}

    with ThreadPoolExecutor(MAX_THREADS) as executor:
        futures = {executor.submit(perceptual_hash, f): f for f in image_files}

        for future in tqdm(futures):
            f = futures[future]
            ph = future.result()

            if ph:
                phashes[f] = ph
            else:
                kept.append(f)

    visited = set()
    files_list = list(phashes.keys())

    for i in range(len(files_list)):

        if files_list[i] in visited:
            continue

        similar_group = [files_list[i]]

        for j in range(i+1, len(files_list)):

            if files_list[j] in visited:
                continue

            diff = phashes[files_list[i]] - phashes[files_list[j]]

            if diff <= SIMILARITY_THRESHOLD:
                similar_group.append(files_list[j])
                visited.add(files_list[j])

        winner = pick_best(similar_group)
        kept.append(winner)

        for f in similar_group:
            if f == winner:
                continue

            winner_size = winner.stat().st_size
            file_size = f.stat().st_size

            size_diff = abs(winner_size - file_size) / max(winner_size, file_size)

            if size_diff > VARIANT_SIZE_DIFF:

                kept.append(f)

                report_rows.append([
                    winner.name,
                    winner_size,
                    f.name,
                    file_size,
                    "VARIANT — Manual Review"
                ])

            else:

                removed.append(f)

                report_rows.append([
                    winner.name,
                    winner_size,
                    f.name,
                    file_size,
                    "Visually Similar Duplicate"
                ])

    # ---------- COPY ---------- #

    logging.info("Copying unique files...")

    for f in tqdm(kept):

        dest = output_dir / f.name
        counter = 1

        while dest.exists():
            dest = output_dir / f"{f.stem}_{counter}{f.suffix}"
            counter += 1

        shutil.copy2(f, dest)

    # ---------- REPORT ---------- #

    report_path = output_dir / "dedup_report.csv"

    total_saved = sum(row[3] for row in report_rows if "Duplicate" in row[4])
    saved_gb = total_saved / (1024 ** 3)

    with open(report_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            "Kept File",
            "Kept Size(bytes)",
            "Removed File",
            "Removed Size(bytes)",
            "Reason"
        ])

        if report_rows:
            writer.writerows(report_rows)
        else:
            writer.writerow(["NO DUPLICATES FOUND", "", "", "", ""])

    logging.info("Deduplication completed!")
    logging.info(f"Unique files kept: {len(kept)}")
    logging.info(f"Duplicates removed: {len(removed)}")
    logging.info(f"Space saved: {saved_gb:.2f} GB")
    logging.info(f"Report generated: {report_path}")


if __name__ == "__main__":
    try:
        path = input("Enter media folder path: ").strip()
        ai_media_dedup(path)

    except Exception:
        logging.exception("Fatal error occurred")
        sys.exit(1)