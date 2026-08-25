# walk.py — M1: find the source files worth indexing.
#
# Takes a repo path, prunes junk directories, keeps known code
# extensions, skips oversized and binary files, prints stats.
#
# Results on the test repo (~/Desktop/projects/WorkWave-main):
#
#   Before filtering:  69,052 files
#     68,121 of those (98.6%) were inside node_modules
#
#   After filtering:      153 files, 14,808 lines
#     skipped >200KB:       0
#     skipped binary:       0
#
#   WorkWave's real source is JavaScript only:
#     142  .js
#      11  .jsx     (JSX is JavaScript, so both map to "JavaScript")
#     = 153 kept
#
#   Everything else in the repo is assets and config, correctly ignored:
#     106 .svg, 78 .png, 26 .jpg, 17 .md, 10 .json, 5 .html, 3 .css
#
#   Also ignored: 2 .env files — API keys must never reach the index.

import sys
import os
from pathlib import Path
from collections import Counter

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "dist", "build",
    "__pycache__", "target", "vendor", ".next", ".cache", "coverage",
}

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".cpp": "C++",
    ".h": "C", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".sql": "SQL",
}

MAX_FILE_BYTES = 200 * 1024

root = Path(sys.argv[1])

kept = 0
total_lines = 0
languages = Counter()
extensions = Counter()
skipped_too_big = 0
skipped_binary = 0

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

    for name in filenames:
        path = Path(dirpath) / name

        language = LANGUAGES.get(path.suffix)
        if language is None:
            continue

        if path.stat().st_size > MAX_FILE_BYTES:
            skipped_too_big += 1
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped_binary += 1
            continue

        kept += 1
        total_lines += len(text.splitlines())
        languages[language] += 1
        extensions[path.suffix] += 1

print(f"files kept:       {kept}")
print(f"total lines:      {total_lines}")
print(f"skipped (>200KB): {skipped_too_big}")
print(f"skipped (binary): {skipped_binary}")
print()

for language, n in languages.most_common():
    print(f"{language:12} {n}")

print()

for ext, n in extensions.most_common():
    print(f"{ext:12} {n}")




#               Project folder
#                     ↓
#                os.walk()
#                     ↓
#         ┌───────────┴───────────┐
#         ↓                       ↓
#    Check directories        Get files
#         ↓                       ↓
#   Remove SKIP_DIRS        Check extension
#                                 ↓
#                      ┌──────────┴──────────┐
#                      ↓                     ↓
#                Known language         Unknown
#                      ↓                     ↓
#                 Check size             Ignore
#                      ↓
#               > 200 KB?
#                ↙       ↘
#              YES        NO
#               ↓          ↓
#            Skip       Read UTF-8
#                          ↓
#                    ┌─────┴─────┐
#                    ↓           ↓
#                 Success      Error
#                    ↓           ↓
#              Count lines    Binary/skip
#                    ↓
#             Count language
#                    ↓
#               Print stats

# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python walk.py ~/Desktop/projects/WorkWave-main
# files kept:       153
# total lines:      14808
# skipped (>200KB): 0
# skipped (binary): 0

# JavaScript   153

# .js          142
# .jsx         11