import sys
from pathlib import Path
from collections import Counter

root = Path(sys.argv[1])

count = 0
in_node_modules = 0
extensions = Counter()

for path in root.rglob("*"):
    if path.is_file():
        count += 1
        if "node_modules" in path.parts:
            in_node_modules += 1
        extensions[path.suffix] += 1

print(f"total files:      {count}")
print(f"in node_modules:  {in_node_modules}")
print()

for ext, n in extensions.most_common(10):
    print(f"{ext or '(none)':10} {n}")
    
    
    
# ---------------- WHAT THIS SCRIPT GIVES ----------------
# Takes a folder path from the command line and recursively analyzes it.
#
# Output:
#   1. Total number of files
#   2. Number of files inside node_modules
#   3. Top 10 most common file extensions


# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python walk.py ~/Desktop/projects/WorkWave-main                    
# total files:      69052
# in node_modules:  68121

# .js        36840
# .ts        7613
# .json      7573
# .map       4725
# .md        2797
# (none)     2693
# .svg       2180
# .mjs       1898
# .mts       1113
# .yml       260
# (venv) (base) amrit@Amrittts-Macbook-Air repolens % 




# User runs:
# python count.py /some/folder
#             ↓
#       sys.argv[1]
#             ↓
#      Path("/some/folder")
#             ↓
#       root.rglob("*")
#             ↓
#    Find everything recursively
#             ↓
#        Is it a file?
#         ↙         ↘
#       NO           YES
#       ↓             ↓
#     Ignore       count += 1
#                     ↓
#           Is node_modules?
#              ↙          ↘
#            YES          NO
#             ↓            ↓
#    in_node_modules += 1
#                     ↓
#            Get path.suffix
#                     ↓
#        extensions[suffix] += 1
#                     ↓
#                  Repeat
#                     ↓
#           Print statistics
#                     ↓
#     ┌──────────────────────────┐
#     │ Total files              │
#     │ Files in node_modules    │
#     │ Top 10 file extensions   │
#     └──────────────────────────┘