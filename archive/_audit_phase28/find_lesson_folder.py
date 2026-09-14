"""Map a chapter number to its source lesson folder containing transcript.json + frames.

Chapter docx filenames in `D:\\Trading\\Output\\Trading Doc` follow:
    Chapter NNN - <Section> - <Lesson>.docx

We need to find the matching folder under D:\\Trading\\Output\\{course_root}\\... that
contains transcript.json + frame_NNNNNN.jpg files.

Usage:
    python find_lesson_folder.py 15
    python find_lesson_folder.py 17 19 25 35 74 75 122
"""
import sys
import os
import glob
import re

TRADING_DOC = r"D:\Trading\Output\Trading Doc"
SEARCH_ROOTS = [
    r"D:\Trading\Output\Bernd Skorupinski  Hybrid AI Trading\Bernd Skorupinski - Hybrid AI Trading System - Course",
    r"D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course",
    r"D:\Trading\Output\Funded Traders\Funded Trader Signals",
    r"D:\Trading\Output\Funded Traders\Funded Trader Weekly Outlook",
    r"D:\Trading\Output\Funded Traders\Practical Application",
]

def get_chapter_title(num):
    pat = os.path.join(TRADING_DOC, f"Chapter {num:03d} - *.docx")
    matches = glob.glob(pat)
    if not matches:
        return None
    name = os.path.basename(matches[0])
    return name.replace(".docx", "")

def normalize(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def find_folder(num):
    title = get_chapter_title(num)
    if not title:
        return None, None
    parts = [p.strip() for p in title.split(" - ")[1:]]
    lesson_token = normalize(parts[-1]) if parts else ""
    section_token = normalize(parts[0]) if len(parts) >= 1 else ""
    best = None
    best_score = -1
    for root in SEARCH_ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            if "transcript.json" not in files:
                continue
            n_frames = sum(1 for f in files if f.startswith("frame_"))
            if n_frames == 0:
                continue
            folder_path = dirpath
            folder_norm = normalize(folder_path)
            score = 0
            if lesson_token and lesson_token in folder_norm:
                score += 10
            if section_token and section_token in folder_norm:
                score += 3
            for p in parts:
                pn = normalize(p)
                if len(pn) >= 4 and pn in folder_norm:
                    score += 1
            if score > best_score:
                best_score = score
                best = (folder_path, n_frames)
    return title, best

def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    if not nums:
        print("usage: find_lesson_folder.py N [N ...]")
        sys.exit(1)
    for n in nums:
        title, result = find_folder(n)
        if result is None:
            print(f"Ch {n:03d}: NOT FOUND ({title})")
        else:
            folder, n_frames = result
            print(f"Ch {n:03d}: {title}")
            print(f"   -> {folder}")
            print(f"   -> frames: {n_frames}")
        print()

if __name__ == "__main__":
    main()
