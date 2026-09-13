# index.py - M4: the orchestrator. 
#
# Runs the whole pipeline against one repository and writes result to postgres:
# walk -> chunk -> embed -> store. One repositories row, one file row per file,
# one code_chunks row per chunk with its embedding.
# 
# The only file that knows the order of things, and the only one that 
# decides what succeeds or fails together.

import os                        # os.environ — the process's environment variables
import sys                       # sys.argv — the command line, as a list of strings
from pathlib import Path         # handles ~, trailing slashes and relative paths

from dotenv import load_dotenv   # reads .env into os.environ 
import psycopg                   # python to postgres driver

from db.store import prepare_connection

def index_repository(conn, root):
    """index one repository that already exists as a folder on disk.
    
    Takes a path - not a URL, not a zip. Whatever the source is later (a Github clone,
    an extracted upload), it becomes a folder first on disk, and this function 
    doesnt change.
    
    'conn' is handed in, so the caller owns the transaction boundaries.
    """
    name = root.name        # repo name
    
    print("path:", root)
    print("name:", name)
    
if __name__ == "__main__":
    # argv[0] is the script itself, so a real argument means len >= 2.
    if len(sys.argv) < 2:
        print("usage: python -m index <path-to-repo>")
        sys.exit(1)

    # expanduser: ~ -> /Users/amrit    resolve: absolute, and ".." removed
    root = Path(sys.argv[1]).expanduser().resolve()

    if not root.is_dir():
        print(f"not a directory: {root}")
        sys.exit(1)

    load_dotenv()                                    # .env -> os.environ

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)                     # teach it the vector type
        index_repository(conn, root)
