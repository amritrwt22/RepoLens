# walk.py — find the source files in a repository that are worth indexing.
#
# find_source_files(root) is a generator: it yields one dict per file,
# pausing in between, so only one file's text is in memory at a time.
#
# Each yielded dict maps directly onto the `files` table columns (see
# docs/schema-design.md), so M4 can insert it without renaming anything.

import sys
import os
from pathlib import Path
from collections import Counter

# Directories that never contain source worth indexing.
# Dependencies, build output, caches, version control.
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "dist", "build",
    "__pycache__", "target", "vendor", ".next", ".cache", "coverage",
}

# Doubles as the allow-list (only these extensions are kept) and the
# extension -> language mapping the Overview screen needs.
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".cpp": "C++",
    ".h": "C", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".sql": "SQL",
}

# Anything bigger is a minified bundle, generated code, or a lockfile.
MAX_FILE_BYTES = 200 * 1024


def find_source_files(root):
    """Yield one dict per indexable source file, one at a time.

    root: Path to the repository root.

    Yields:
        {"path": str, "language": str, "line_count": int, "content": str}
        where `path` is RELATIVE to root.
    """
    root = Path(root)

    # os.walk hands us (current dir, its subdirs, its files) at each level.
    for dirpath, dirnames, filenames in os.walk(root):

        # Editing dirnames IN PLACE (note the [:]) tells os.walk not to
        # descend into those directories at all. Assigning a new list
        # instead of slicing would not work - os.walk reads this exact list.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for name in filenames:
            path = Path(dirpath) / name

            # .get() returns None for unknown extensions instead of raising.
            language = LANGUAGES.get(path.suffix)
            if language is None:
                continue

            if path.stat().st_size > MAX_FILE_BYTES:
                print(f"skip (too big):  {path}", file=sys.stderr)
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # The only reliable binary check: try decoding, see if it blows up.
                print(f"skip (not text): {path}", file=sys.stderr)
                continue

            yield {
                # relative_to() strips the root, so we store
                # "Client/src/App.js", not "/Users/amrit/Desktop/...".
                "path": str(path.relative_to(root)),
                "language": language,
                "line_count": len(content.splitlines()),
                "content": content,
            }


# Runs only when you execute this file directly, not when another
# module imports find_source_files from it.
if __name__ == "__main__":
    root = Path(sys.argv[1])

    files = 0
    total_lines = 0
    languages = Counter()

    # The generator is consumed here, one file at a time.
    for f in find_source_files(root):
        files += 1
        total_lines += f["line_count"]
        languages[f["language"]] += 1

    print(f"files:       {files}")
    print(f"total lines: {total_lines}")
    print()
    for language, n in languages.most_common():
        print(f"{language:12} {n}")
        
# This section is only for testing the walker when we run walk.py directly.
# find_source_files() is a generator, so it yields one valid source file at a time.
# The for loop automatically asks the generator for the next file, processes it,
# then asks for the next one until all files have been yielded.
#
# We don't need the actual file contents here. We only use each yielded file's
# metadata to count the total files, total lines, and files per language.
#
# When walk.py is imported by another module (e.g. chunk.py), this section does
# not run. The other module can directly use find_source_files().
        
# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python walk.py ~/Desktop/projects/WorkWave-main                 
# files:       153
# total lines: 14808
# JavaScript   153
        
        
        
        
    

# ─────────────────────────────────────────────────────────────────────────
#  HOW THIS FILE WORKS
# ─────────────────────────────────────────────────────────────────────────
#
#   find_source_files(root)
#          │
#          ▼
#   ┌─────────────────────────────────────────────────────────┐
#   │  os.walk(root)  —  visit one directory at a time        │
#   └─────────────────────────────────────────────────────────┘
#          │
#          ▼
#   ┌─────────────────────────────────────────────────────────┐
#   │  dirnames[:] = [d for d in dirnames if d not in         │
#   │                 SKIP_DIRS]                              │
#   │                                                         │
#   │  Prunes BEFORE descending. node_modules is never even   │
#   │  opened — this is why 69,052 files became 931 quickly.  │
#   └─────────────────────────────────────────────────────────┘
#          │
#          ▼
#      for each file in this directory
#          │
#          ▼
#   ┌───────────────────────┐
#   │ known extension?      │──── no ───▶ skip (silent)
#   │ LANGUAGES.get(suffix) │             .svg .png .md .json
#   └───────────────────────┘
#          │ yes
#          ▼
#   ┌───────────────────────┐
#   │ size <= 200 KB?       │──── no ───▶ skip + warn on stderr
#   └───────────────────────┘             minified bundles
#          │ yes
#          ▼
#   ┌───────────────────────┐
#   │ decodes as UTF-8?     │──── no ───▶ skip + warn on stderr
#   │ (try/except)          │             binaries
#   └───────────────────────┘
#          │ yes
#          ▼
#   ┌─────────────────────────────────────────────────────────┐
#   │  yield {                                                │
#   │      "path":       relative to root, not absolute       │
#   │      "language":   from LANGUAGES                       │
#   │      "line_count": len(content.splitlines())            │
#   │      "content":    the full file text                   │
#   │  }                                                      │
#   │                                                         │
#   │  ...then PAUSE here until the caller asks for the next. │
#   └─────────────────────────────────────────────────────────┘
#          │
#          └────────▶ back to "for each file" when resumed
#
#
#  WHY yield AND NOT return
#
#     return a list          yield (generator)
#     ─────────────          ─────────────────
#     read all 153 files     read 1 file
#     hold all in memory     hand it over, pause
#     then start chunking    chunker processes it
#                            resume, read next file
#
#     153 files ≈ 500 KB, so it makes no difference here.
#     A 2,000-file repo would hold ~100 MB at once with a list.
#     The generator holds one file, whatever the repo size.
#
#
#  WHO CALLS IT
#
#     walker  ──yields──▶  one file dict
#                              │
#                              ▼
#                          chunker  ──▶  chunks of 60 lines
#                              │
#                              ▼
#                          embedder ──▶  vectors
#                              │
#                              ▼
#                          Postgres
#
#     Right now nothing calls it except the __main__ block below,
#     which just counts what comes out. The chunker is next (M2).
