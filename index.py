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

from db.store import prepare_connection, store_repository, store_file, store_chunks, finish_repository, fail_repository
from pipeline.walk import find_source_files
from pipeline.chunker import chunk_text
from pipeline.embedder import Embedder

BATCH_SIZE = 20

def index_repository(conn, root):
    """Index one repository that already exists as a folder on disk."""
    name = root.name        # repo name

    # Transaction 1: committed on its own, before any content work starts.
    # If indexing fails later this row survives, so it can be marked 'failed'.
    repo_id = store_repository(conn, name)
    conn.commit()
    
    # Transaction 2 opens at the first store_file below and stays open until
    # every file and chunk is in. It is not committed in this part.
    
    file_count = 0
    total_lines = 0
    chunk_count = 0
    buffer = []      # accumulates the chunks
    embedder = Embedder() # one instance for whole indexing of a repo:
    # it holds API client and reuses HTTP connection across all embedding req. 
    
    # find_source_files is a GENERATOR - one file at a time, never all in repo.
    for file in find_source_files(root):
        # file = {"path":, "language":, "line_count":, "content":}
        file_id = store_file(conn, repo_id, file)
        file_count += 1
        total_lines += file["line_count"]
        
        # chunk_text returns a LIST - all chunks of this one file
        for chunk in chunk_text(file["content"]):
            # chunk = {"start_line":, "end_line":, "content":}
            # ** unpacks chunk's keys into a new dict, then file_id is added:
            # {"start_line":, "end_line":, "content":, "file_id":}
            # file_id travels per chunk because one buffer spans several files.
            buffer.append({**chunk, "file_id": file_id})
            chunk_count += 1
            
            if len(buffer) >= BATCH_SIZE:
                flush(conn, repo_id, buffer, embedder)
                buffer = []
        
    # final flush when the no. of chunks left in buffer are < BATCH_SIZE
    if buffer:
        flush(conn, repo_id, buffer, embedder)
        
    # Transaction 2 ends here, after storing all the chunk with their embeddings in db
    # repo, files and chunks with embeddings are stored in db : all successfull
    # now update the status from 'indexing' to 'ready' and upadte null columns in repository table and commit
    finish_repository(conn, repo_id, file_count, chunk_count, total_lines)
    conn.commit()

    print(f"files: {file_count} lines: {total_lines} chunks: {chunk_count}")
            
            
            
        
def flush(conn, repo_id, buffer, embedder):
    """Embed one buffer of chunks and store them.

    conn      an open psycopg connection
    repo_id   int, from store_repository
    buffer    list of dicts, each:
                  {"start_line": 1, "end_line": 60,
                   "content": "<60 lines>", "file_id": 7}
    embedder  an Embedder instance - holds the API client, created once per run

    Returns nothing. Mutates buffer: each dict gains an "embedding" key, a list
    of 768 floats.

    chunks and vectors line up by POSITION - vectors[i] is the embedding of
    buffer[i]. Nothing in the data links them, so they are paired here, the
    moment the embedder returns, while that guarantee still holds.
    """
    
    texts = []
    for chunk in buffer:
        texts.append(chunk["content"])
        
    # one HTTP request for the whole buffer
    vectors = embedder.embed_documents(texts)
    
    # attach each vector to its chunk - after this there is one structure,
    # not two lists that could drift apart
    for i in range(len(buffer)):
        buffer[i]["embedding"] = vectors[i]
        
    store_chunks(conn, repo_id, buffer)
        
        
    
    
    















    
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


# WHY THIS STAYS FLAT IN MEMORY
#
# find_source_files yields one file at a time, so the repository is never held
# as a whole. At any moment memory holds:
#
#   - one file's content
#   - that file's chunks, from chunk_text (~1.2x the file, chunks overlap)
#   - at most BATCH_SIZE chunks in the buffer
#
# The buffer is the only thing that accumulates, and it is emptied every time
# it fills. So the ceiling is set by the largest single file plus BATCH_SIZE -
# not by how big the repository is. A repo 100x larger costs the same.
