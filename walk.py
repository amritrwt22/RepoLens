import sys
from pathlib import Path

root = Path(sys.argv[1])

count=0
for path in root.rglob("*"):
    if path.is_file():
        count+=1
        
print(f"total files: {count}")


# counting all files 
# total files: 69052

import sys
from pathlib import Path

root = Path(sys.argv[1])

count=0
for path in root.rglob("*"):
    if path.is_file():
        count+=1
        
print(f"total files: {count}")


# ---------------- EXPLANATION ----------------
# sys:
#   Built-in Python module for interacting with the system/interpreter.
#   sys.argv contains command-line arguments.
#
# pathlib:
#   Python module for working with file and directory paths.
#   Path represents a filesystem path and provides methods like
#   is_file(), is_dir(), rglob(), etc.
#
# sys.argv[1]:
#   Gets the folder path provided when running the script.
#   Example:
#       python count.py /Users/amrit/project
#       sys.argv[1] -> "/Users/amrit/project"
#
# Path(sys.argv[1]):
#   Converts the string path into a Path object.
#
# root.rglob("*"):
#   Recursively finds everything (files + directories) inside root
#   and all its subdirectories.
#
# path.is_file():
#   Checks whether the current path is a file.
#
# count += 1:
#   Increases the file counter whenever a file is found.
#
# f"...{count}":
#   f-string; inserts the value of count into the output string.
#
#
# FLOW:
#
# User runs:
#       python count.py /some/folder
#                    ↓
#              sys.argv[1]
#                    ↓
#          Path("/some/folder")
#                    ↓
#             root.rglob("*")
#                    ↓
#       Find files + directories recursively
#                    ↓
#          ┌─────────┴─────────┐
#          ↓                   ↓
#        File               Directory
#          ↓                   ↓
#     count += 1             Ignore
#          ↓
#        Repeat
#          ↓
#     Print total files