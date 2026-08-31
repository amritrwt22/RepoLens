#!/usr/bin/env python3
# dump.py — inspect what the walker produces, one file at a time.
#
# Consumes the find_source_files() generator and prints each yielded dict
# as it arrives. Nothing is held in memory except the file currently
# being printed — see docs/generators-and-yield.md.
# Run from the repo root:  python -m scripts.dump <path-to-repo>

import sys
from pathlib import Path

from walk import find_source_files

root = Path(sys.argv[1])

# Calling the generator function does NOT run it. It hands back a
# generator object, paused before its first line.
files = find_source_files(root)

count = 0

# Each pass resumes the walker, which runs until its next yield, hands
# over one dict, and freezes again. The `for` calls next() for us.
for f in files:
    count += 1

    print(f"--- file {count} ---")
    print(f"path:       {f['path']}")
    print(f"language:   {f['language']}")
    print(f"line_count: {f['line_count']}")

    # `content` is the whole file. Print only the opening so the
    # terminal stays readable.
    preview = f["content"][:200].replace("\n", "\\n")
    print(f"content:    {preview} ...")
    print()

print(f"total: {count} files")


# (venv) (base) amrit@Amrittts-Macbook-Air repolens % ./dump.py ~/Desktop/projects/WorkWave-main 2>/dev/null | head -40

# --- file 1 ---
# path:       Server/index.js
# language:   JavaScript
# line_count: 125
# content:    const express = require("express"); // import express from the express library to create a new app\nconst http = require("http"); // import http module for creating HTTP server for Socket.IO\nconst { Se ...

# --- file 2 ---
# path:       Server/middlewares/AuthMiddleware.js
# language:   JavaScript
# line_count: 26
# content:    const jwt = require("jsonwebtoken");\n// this file perform authentication and authorization\n// authentication process - verify the token\n// authorization process - check the role of user\nconst authMidd ...

# --- file 3 ---
# path:       Server/middlewares/userLogin.js
# language:   JavaScript
# line_count: 58
# content:    // jsonwebtoken is module of node.js to work with json web tokens.\n// jwt = require("jsonwebtoken") is used to import the jsonwebtoken library, which is used for creating and verifying JSON Web Tokens ...