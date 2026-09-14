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

from db.store import prepare_connection, store_repository, store_file
from pipeline.walk import find_source_files



def index_repository(conn, root):
    """Index one repository that already exists as a folder on disk.

    Takes a path - not a URL, not a zip. Whatever the source is later (a GitHub
    clone, an extracted upload), it becomes a folder on disk first, and this
    function doesn't change.

    'conn' is handed in, so the caller owns the transaction boundaries.
    """
    name = root.name        # repo name

    # Transaction 1: committed on its own, before any content work starts.
    # If indexing fails later this row survives, so it can be marked 'failed'.
    repo_id = store_repository(conn, name)
    conn.commit()
    
    # Transaction 2 opens at the first store_file below and stays open until
    # every file and chunk is in. It is not commited in this part
    
    file_count = 0
    total_lines = 0
    
    for f in find_source_files(root):
        # f = {"path":, "language":, "line_count":, "content":}
        file_id = store_file(conn, repo_id, f)
        file_count += 1
        total_lines += f["line_count"]
        
    print(f"files: {file_count} lines: {total_lines}")

    













    
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


    # A transaction opens at the first execute and ends at conn.commit(), or
    # when the `with psycopg.connect(...)` block exits. commit() does NOT close
    # the connection - one connection carries all three transactions below.
