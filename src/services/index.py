# index.py - the orchestrator.
#
# walk -> chunk -> embed -> store, against one repository on disk.
# Writes one repositories row, one files row per file, and one code_chunks row
# per chunk with its 768-float embedding.
#
# Design notes at the bottom of this file.

import os                        # os.environ — the process's environment variables
import sys                       # sys.argv — the command line, as a list of strings
from pathlib import Path         # handles ~, trailing slashes and relative paths

from dotenv import load_dotenv   # reads .env into os.environ 
import psycopg                   # python to postgres driver

from src.db.store import prepare_connection, store_repository, store_file, store_chunks, finish_repository, fail_repository
from src.pipeline.walk import find_source_files
from src.pipeline.chunker import chunk_text
from src.pipeline.embedder import Embedder

# A batch ends when either cap is hit. BATCH_SIZE limits how many chunks go in
# one request; MAX_BATCH_CHARS limits the payload. The API's real limit is
# 30,000 tokens/min, and at ~2.8 chars/token 28,000 chars is ~10,000 tokens -
# a third of the budget. Ordinary code hits BATCH_SIZE first; dense long-line
# files hit the character cap and produce smaller batches on their own.
# avg token range: 2.7 - 4.3 chars/ token. (ex: ;=token with 1 char, a big function name = 30 chars/token)
# we took least chars/token, so in case in repo we have all tokens with very less chars, creating
# more tokens, then in worst case there can be 10k tokens only per 28k chars. (we are assuming that all tokens in repo has 2.7 chars, which is very less. meaning we are on safest zone, this limit can be exceed if we have avg char/token rate less than 2.7, but still there is 20k tokens headroom to handle it).
# even in worst case when 1 char = 1 token. we get 28k tokens from our 28k characters limit : completely safe
BATCH_SIZE = 20
MAX_BATCH_CHARS = 28_000

def index_repository(conn, root):
    """Index one repository that already exists as a folder on disk.

    conn    an open psycopg connection. Handed in, so this function owns the
            transaction boundaries but not the connection's lifetime.
    root    a Path to the folder. Not a URL, not a zip - whatever the source is
            later (a GitHub clone, an extracted upload), it becomes a folder
            first and this function does not change.

    Returns nothing. Writes rows, and leaves the repository row at 'ready' or
    'failed'.

    Steps:
        1  create the repository row, commit it alone
        2  for each file the walker yields:
               store the file row, keep its generated file_id
               chunk the file, stamp file_id onto each chunk
               append to the buffer; flush whenever it reaches BATCH_SIZE
        3  flush whatever is left in the buffer after the loop
        4  fill in the counts, mark 'ready', commit
        5  on any failure: roll back, mark 'failed' with the error, re-raise
    """
    name = root.name        # repo name

    # Transaction 1: committed on its own, before any content work starts.
    # If indexing fails later this row survives, so it can be marked 'failed'.
    repo_id = store_repository(conn, name)
    conn.commit()
    
    file_count = 0
    total_lines = 0
    chunk_count = 0
    buffer = []      # accumulates the chunks
    buffer_chars = 0 # running size of the buffer, in characters
    
    
    # One instance for the whole run: holds the API client and reuses the
    # HTTP connection across every embedding request.
    embedder = Embedder()
    
    
    # --------------------happy path : transaction 2--------------
    # either the whole repo is chunked and embedded or not at all. 
    # try path for indexing the complete repo successfully. 
    # trans open at first store_file (when first execute takes place)
    # ends at commit below after finish repository
    try:
        
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
                buffer_chars += len(chunk["content"])
                
                if len(buffer) >= BATCH_SIZE or buffer_chars >= MAX_BATCH_CHARS:
                    flush(conn, repo_id, buffer, embedder)
                    buffer = []
                    buffer_chars = 0
            
        # final flush when the no. of chunks left in buffer are < BATCH_SIZE
        if buffer:
            flush(conn, repo_id, buffer, embedder)
            
        # Transaction 2 ends here, after storing all the chunk with their embeddings in db
        # repo, files and chunks with embeddings are stored in db : all successfull
        # now update the status from 'indexing' to 'ready' and upadte null columns in repository table and commit
        finish_repository(conn, repo_id, file_count, chunk_count, total_lines)
        conn.commit()

        print(f"files: {file_count} lines: {total_lines} chunks: {chunk_count}")
        
    # ------------ failure path: transaction 3---------------------------
    # Anything raised above leaves transaction 2 ABORTED - postgres refuses
    # every further statement until it ends. So : ROLLBACK (all content in files and chunks tables deleted for this repository), 
    # then record the failure in the row created in transaction 1 in repository table's [error] column. And mark indexing status as 'failed'
    except Exception as e:
        conn.rollback()
        fail_repository(conn, repo_id, f"{type(e).__name__}: {e}")
        conn.commit()

        # Recording a failure is not handling it. Without this the process
        # exits 0 and a failed run looks like a successful one.
        raise
            
            
        
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

    Steps:
        1  pull the text out of each chunk
        2  embed all of them in ONE request
        3  attach each vector to its chunk, by position
        4  store the batch
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


# =============================================================================
# DESIGN NOTES
# =============================================================================
#
# This is the only file that knows the order of things, and the only one that
# decides what succeeds or fails together. The pipeline modules know nothing
# about the database; db/store.py knows nothing about the pipeline.
#
#
# THE THREE TRANSACTIONS
#
#   1  store_repository -> COMMIT
#        The repository row is saved before any of the long work begins. If
#        indexing dies five minutes later, a rollback discards the files and
#        chunks - but this row is already committed, so it survives and can be
#        marked 'failed'. Inside transaction 2 it would be discarded too, and
#        there would be no trace the attempt ever happened.
#
#   2  every file + every chunk + finish_repository -> COMMIT
#        All the content, or none of it. A half-indexed repository is worse
#        than no repository: it reports itself present and answers questions
#        from a third of the code.
#
#   3  on failure: ROLLBACK -> fail_repository -> COMMIT -> raise
#        Transaction 2 is aborted and refuses every statement, so the rollback
#        has to come first. Only then can a fresh transaction record the error.
#
#
#        happy path                         failure path
#        ----------                         ------------
#        store_repository                   store_repository
#        COMMIT              (1)            COMMIT              (1)
#        files + chunks                     files + chunks ... boom
#        finish_repository                  ROLLBACK        (2 discarded)
#        COMMIT              (2)            fail_repository
#        status = 'ready'                   COMMIT              (3)
#                                           status = 'failed', error set
#                                           raise
#
#
# WHY MEMORY STAYS FLAT
#
#   find_source_files is a generator, so the repository is never held whole.
#   At any moment memory holds:
#
#       - one file's content
#       - that file's chunks from chunk_text (~1.2x the file; they overlap)
#       - at most one batch of chunks in the buffer
#
#   The buffer is the only thing that accumulates, and it is emptied whenever
#   it fills. The ceiling is the largest single file plus one batch - not the
#   size of the repository. A repo 100x larger costs the same.
#
#
# WHY A BATCH IS CAPPED TWO WAYS
#
#   BATCH_SIZE caps the number of chunks. MAX_BATCH_CHARS caps the payload,
#   and it is the one that matters: the API's binding limit is 30,000 TOKENS
#   per minute, not requests.
#
#   Tokens cannot be counted locally, so they are estimated from characters.
#   Measured on real chunks with the API's count_tokens: 2.8 - 4.3 chars per
#   token. The ratio varies because a long identifier is one token of ~25
#   characters, while `{a: 1}` is six tokens of one character each.
#
#   The cap uses the LOWEST ratio on purpose:
#
#       28,000 chars / 2.8  = 10,000 tokens     <- what we assume
#       28,000 chars / 4.3  =  6,500 tokens     <- what it usually is
#
#   Assuming the worst ratio over-estimates the tokens, so batches flush early
#   rather than late. Using 4.3 would allow 43,000 chars, which on
#   punctuation-heavy code is 15,000 real tokens - half the minute's budget in
#   a single request.
#
#   Counting chunks alone was the original design and is not enough: 20 chunks
#   of dense, long-line source could exceed the whole per-minute budget in one
#   call. Ordinary code still hits BATCH_SIZE first, so nothing changes for a
#   normal repository - the character cap only bites where it needs to.
