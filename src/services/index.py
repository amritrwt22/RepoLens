# index.py - the orchestrator.
#
# clone -> walk -> chunk -> embed -> store, against one GitHub repository.
# Writes one repositories row, one indexing_jobs row per run, one files row per
# file, and one code_chunks row per chunk with its 768-float embedding.
#
# Design notes at the bottom of this file.

import os                        # os.environ — the process's environment variables
import sys                       # sys.argv — the command line, as a list of strings
from pathlib import Path         # wraps the clone's path string as a path object

from dotenv import load_dotenv   # reads .env into os.environ 
import psycopg                   # python to postgres driver

from src.pipeline.clone import clone_repo
from src.pipeline.walk import find_source_files
from src.pipeline.chunker import chunk_text
from src.pipeline.embedder import Embedder
from src.db.store import prepare_connection, get_or_create_repository, start_job, delete_repository_content, store_file, store_chunks, mark_repository_indexed, mark_job_completed

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

def index_repository(conn, root, owner, repo, sha):
    """Index one repository that already exists as a folder on disk.

    conn    an open psycopg connection. Handed in, so this function owns the
            transaction boundaries but not the connection's lifetime.
    root    a Path to the folder, today a clone made by clone_repo. Not a URL,
            not a zip - whatever the source becomes later, it is a folder by
            the time it reaches here and this function does not change.
    owner   "amritrwt22" - from the URL, not the folder name. A cloned folder
            is called repolens_owner_repo_xxxx, which is not the repo name.
    repo    "RepoLens"
    sha     the commit the folder is sitting on. This run's to_sha, and what
            commit_sha becomes if it succeeds.

    Returns nothing. Writes rows, and leaves the job row at 'success' or
    'failure'.

    Steps:
        1  upsert the repository, open the job row, commit them alone
           - if the repo is already on this commit, close the job and stop
        2  for each file the walker yields:
               store the file row, keep its generated file_id
               chunk the file, stamp file_id onto each chunk
               append to the buffer; flush whenever it reaches BATCH_SIZE
        3  flush whatever is left in the buffer after the loop
        4  fill in the counts and commit_sha, close the job, commit
        5  on any failure: roll back, close the job as 'failure', re-raise
    """


    # Transaction 1: open the run. Committed on its own, before any content
    # work starts, so both rows survive whatever happens later — after a
    # failure the repository is still there and the job carries the reason.
    #
    # from_sha is the commit this repository was last indexed at, or None if it
    # never has been. That single value is what lets one code path serve both
    # cases: None falls through as a first index, an older sha as a re-index.
    repo_id, from_sha = get_or_create_repository(conn, owner, repo)
    job_id = start_job(conn, repo_id, from_sha, sha)

    # We are already indexed at the latest commit, so there is nothing to
    # update. The job is marked completed here, this transaction commits, and
    # the function returns — T2 and T3 never run.
    #
    # 'skipped' rather than 'success' so a run that did nothing can be told
    # apart from one that indexed the repository.
    if from_sha == sha:
        mark_job_completed(conn, job_id, "skipped")
        conn.commit()
        print(f"already indexed at {sha[:7]}, nothing to do")
        return

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
    # Either the whole repo is swapped or none of it is. The transaction opens
    # at the delete below and ends at the commit after the job is closed.
    try:
        # The delete is inside T2, so until the commit nobody sees it. A question
        # asked mid-run is answered from the old files against the old commit_sha.
        # On a first index this removes nothing.
        delete_repository_content(conn, repo_id)
        
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
            
        # Transaction 2 ends here. The new content, the new commit_sha and the
        # closed job all become visible in the same instant.
        mark_repository_indexed(conn, repo_id, sha, file_count, chunk_count, total_lines)
        mark_job_completed(conn, job_id, "success")
        conn.commit()

        print(f"files: {file_count} lines: {total_lines} chunks: {chunk_count}")
        
    # ------------ failure path: transaction 3---------------------------
    # Anything raised above leaves transaction 2 ABORTED - postgres refuses every
    # further statement until it ends. So ROLLBACK first: the half-written files
    # and chunks go, and only then can a fresh transaction record what happened.
    #
    # This touches the job row only. The repository keeps its old commit_sha, so
    # a repo that was answerable before a failed re-index is still answerable.
    except Exception as e:
        conn.rollback()
        mark_job_completed(conn, job_id, "failure", f"{type(e).__name__}: {e}")
        conn.commit()

        # Recording a failure is not handling it. Without this the process
        # exits 0 and a failed run looks like a successful one.
        raise

    # Ctrl-C needs its own block: KeyboardInterrupt inherits from BaseException,
    # not Exception, so the catch-all above never sees it. Without this the job
    # stays 'in_progress' forever.
    #
    # 'cancelled' rather than 'failure' - nothing broke, someone stopped it.
    except KeyboardInterrupt:
        conn.rollback()
        mark_job_completed(conn, job_id, "cancelled", "interrupted")
        conn.commit()
        raise
            
            
        
def flush(conn, repo_id, buffer, embedder):
    """Embed one buffer of chunks and store them.

    conn      an open psycopg connection
    repo_id   int, from get_or_create_repository
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
    # sys.argv is the command line as a list. argv[0] is always the script
    # itself, argv[1] the first real argument - so one element means none given.
    if len(sys.argv) < 2:
        print("usage: python -m src.services.index <github-url>")
        sys.exit(1)

    url = sys.argv[1]

    load_dotenv()                                    # .env -> os.environ

    # The clone lives for the whole run and is deleted when this block ends,
    # whether indexing succeeded or raised.
    with clone_repo(url) as (path, owner, repo, sha):
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            prepare_connection(conn)                 # teach it the vector type
            index_repository(conn, Path(path), owner, repo, sha)


# =============================================================================
# DESIGN NOTES
# =============================================================================
#
# This is the only file that knows the order of things, and the only one that
# decides what succeeds or fails together. The pipeline modules know nothing
# about the database; db/store.py knows nothing about the pipeline.
#
#
# WHERE THE FOLDER COMES FROM
#
#   __main__ wraps all three transactions in clone_repo, so the clone exists
#   for the whole run and is deleted on the way out - after a success, after a
#   failure, and after the skip below. index_repository never sees a URL and
#   never deletes anything; it is handed a folder that already exists.
#
#
# THE THREE TRANSACTIONS
#
#   Row-by-row dry runs, including both failure paths:
#   docs/18-repolens_design/schema-design.md -> "First index — flow",
#   "Re-index — flow", "The contrast".
#
#   One code path runs both a first index and a re-index. They differ only in
#   what T1 finds: no commit_sha on the repository means first index, an
#   existing one means re-index and becomes the job's from_sha.
#
#
#   T1  upsert the repository, open the job row -> COMMIT
#
#       These two rows are committed before the long work starts, so they
#       survive whatever happens next. After a failure the repository row is
#       still there and the job row carries the reason.
#
#       If the repository is already on this commit, the job is closed here as
#       a success and the run ends - there is nothing to re-index.
#
#
#   T2  delete the old content, write the new content, move commit_sha,
#       close the job as success -> COMMIT
#
#       All of it or none of it. A half-indexed repository is worse than no
#       repository: it reports itself present and answers questions from a
#       third of the code.
#
#       The delete is inside this transaction. Until the commit nobody can see
#       it, so a question asked mid-run is answered from the old files against
#       the old commit_sha. The new files and the new commit_sha appear in the
#       same instant.
#
#
#   T3  on failure: ROLLBACK, close the job as failure -> COMMIT, raise
#
#       The rollback comes first: T2 is aborted and refuses every statement
#       until it is rolled back. Only then can a fresh transaction record it.
#
#       This touches the job row only. The repository keeps its commit_sha, so
#       a repo that was answerable before a failed re-index is still answerable
#       after it.
#
#
#        first index                  re-index                     failure
#        -----------                  --------                     -------
#        upsert repo (new row)        upsert repo (found)          upsert repo
#        from_sha = NULL              from_sha = old sha           open job
#        open job                     open job                     COMMIT      (1)
#        COMMIT          (1)          COMMIT          (1)          delete old
#        delete old (0 rows)          delete old content           files + chunks ... boom
#        files + chunks               files + chunks               ROLLBACK    (2 gone)
#        commit_sha = to_sha          commit_sha = to_sha          job failed, error set
#        job success                  job success                  COMMIT      (3)
#        COMMIT          (2)          COMMIT          (2)          raise
#        now servable                 now on the new commit_sha    still on the old commit_sha
#
#
#   NOT HANDLED: a hard kill (kill -9, SIGTERM, OOM) runs no python at all, so
#   it skips T3 and leaves the job at 'in_progress' forever. It also skips
#   clone_repo's cleanup, leaving the folder on disk.
#
#   Both need the same sweep, at deploy: jobs whose started_at is old get the
#   'cancelled' conclusion, and repolens_* folders older than a few hours get
#   deleted.
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
