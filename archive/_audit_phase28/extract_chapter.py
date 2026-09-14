"""Chapter text extractor for Phase 28 audit.

Usage:
    python _audit_phase28/extract_chapter.py 13           # extract chapter 013
    python _audit_phase28/extract_chapter.py 13 14 15     # extract multiple
    python _audit_phase28/extract_chapter.py --grep "26 week" 13 14 15
"""
import sys
import os
import glob
import re
import docx

CORPUS_DIR = r"D:\Trading\Output\Trading Doc"

def find_chapter(num):
    pattern = os.path.join(CORPUS_DIR, f"Chapter {num:03d} - *.docx")
    matches = glob.glob(pattern)
    return matches[0] if matches else None

def extract(path):
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())

def main():
    args = sys.argv[1:]
    grep_pat = None
    if "--grep" in args:
        i = args.index("--grep")
        grep_pat = args[i + 1]
        args = args[:i] + args[i + 2:]
    chapters = []
    for a in args:
        try:
            chapters.append(int(a))
        except ValueError:
            pass
    if not chapters:
        print("usage: extract_chapter.py [--grep PAT] CHAPTER_NUM [CHAPTER_NUM ...]")
        sys.exit(1)
    for c in chapters:
        path = find_chapter(c)
        if not path:
            print(f"### Chapter {c:03d}: NOT FOUND")
            continue
        title = os.path.basename(path).replace(".docx", "")
        print(f"\n{'='*80}\n### {title}\n{'='*80}\n")
        text = extract(path)
        if grep_pat:
            for line in text.split("\n"):
                if re.search(grep_pat, line, re.IGNORECASE):
                    print(line)
        else:
            print(text)

if __name__ == "__main__":
    main()
