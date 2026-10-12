# db/store.py : the only module that writes to Postgres.
#
# Takes what the pipeline produced in memory and puts it in the six tables.
# It never walks, chunks or embeds, and it never creates a connection — it is handed one.
# That way the same code works from a script today and from a pooled web request later.
#
#
# WHICH FUNCTION BELONGS TO WHICH TRANSACTION
#
# Indexing a repository — the flow lives in services/index.py, the transaction
# boundaries are documented there. Dry runs: docs/18-repolens_design/schema-design.md
#
#   T1  open the run
#         get_or_create_repository   find or create the repo, read its current commit
#         start_job                  record that a run has started
#
#   T2  swap the content
#         delete_repository_content  drop the old files; chunks cascade with them
#         store_file                 one row per file
#         store_chunks               one batch of chunks with their embeddings
#         mark_repository_indexed    record the commit and the counts
#         mark_job_completed         close the run as a success
#
#   T3  record the failure
#         mark_job_completed         close the run as a failure, with the reason
#
# Not part of any transaction:
#         prepare_connection         call once after connecting, before storing vectors

from pgvector.psycopg import register_vector # teaches psycopg the vector type

def prepare_connection(conn):
    """Make one connection ready for storing vectors. Call once after connecting.

      Every type in Postgres has a numeric id, assigned when the extension is installed
      in database. So the vector might be type 16485 on my db and something else on other.
      So to identify the data type, our program needs to know the id of the datatype.

      register_vector asks the db server for the vector type's id on THIS connection
      and teaches psycopg to convert a python list to and from it. It applies to one
      connection, not to program - a new connection needs it again.

    """
    register_vector(conn)


def get_or_create_repository(conn, owner, repo):
    """Find or create the row for one repository.

    IN   conn, owner ("amritrwt22"), repo ("RepoLens")
    OUT  (repo_id, from_sha)
             repo_id   int
             from_sha  str, or None if this repo has never been indexed

    Inserts the row, then reads it back. ON CONFLICT DO NOTHING makes the
    insert skip quietly when the repo is already there.

    This is what handles two users indexing the same repo at the same moment.
    The check and the insert are one statement, so one of them creates the row and the other quietly gets nothing. As separate steps — read, then write —
    both see it missing, both insert, and one dies on UNIQUE (owner, repo).

    The SELECT returns the row whether it was just created or already existed.
    DO NOTHING returns no row on a conflict, so RETURNING cannot do this job.

    Both statements run in one transaction, so nothing can change the row
    between them.

    Only owner and repo are written. commit_sha, the counts and indexed_at are
    filled by mark_repository_indexed when indexing succeeds.
    """
    with conn.cursor() as cur:
        # Creates the row the first time we see this repo; does nothing if it
        # is already there.
        cur.execute(
            """
            INSERT INTO repositories (owner, repo)
            VALUES (%s, %s)
            ON CONFLICT (owner, repo) DO NOTHING
            """,
            (owner, repo),
        )

        # The row exists by now either way.
        cur.execute(
            """
            SELECT id, commit_sha
            FROM repositories
            WHERE owner = %s AND repo = %s
            """,
            (owner, repo),
        )
        return cur.fetchone()


def start_job(conn, repo_id, from_sha, to_sha):
    """Record that an indexing run has started, and return the job's id.

    IN   conn      an open psycopg connection
         repo_id   int, from get_or_create_repository
         from_sha  str or None — the commit the repo serves right now.
                   None means it has never been indexed.
         to_sha    str — the commit this run targets, from git rev-parse HEAD

    OUT  job_id    int

    Writes the five columns known now. conclusion, finished_at and error are
    written by mark_job_completed when the run ends.

    from_sha is written every time. None is a real value for it: it is how a
    first index is told apart from a re-index.

    status is 'in_progress' because the caller starts walking immediately.
    'queued' is for when a worker picks jobs off a queue.

    The returned id is how the caller finds this row again to close it.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexing_jobs
                (repository_id, from_sha, to_sha, status, started_at)
                VALUES (%s, %s, %s, 'in_progress', now())
                RETURNING id
            """,
            (repo_id, from_sha, to_sha),
        )
        return cur.fetchone()[0]


def delete_repository_content(conn, repo_id):
    """Delete every file of one repository. Its chunks go with them.

    IN   conn      an open psycopg connection
         repo_id   int

    Returns nothing.

    code_chunks.file_id is ON DELETE CASCADE, so removing a file removes its
    chunks. There is no second DELETE.

    Deletes nothing on a first index, which needs no special case.

    Runs as the first statement of the transaction that writes the new content
    and moves commit_sha, so readers never see the repository without files.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM files
            WHERE repository_id = %s
            """,
            (repo_id,),
        )


def store_file(conn, repo_id, file):
    """Insert one file row and return its generated id.

    Every column is filled — nothing is deferred, unlike repositories.

    `file` is one dict from pipeline.walk.find_source_files:
        {"path": "Server/index.js", "language": "JavaScript",
         "line_count": 125, "content": "<full text>"}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (repository_id, path, language, line_count, content)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (repo_id, file["path"], file["language"], file["line_count"], file["content"]),
        )
        # Same as above: (file_id,) out of the result, [0] to unwrap it.
        # Every chunk of this file needs this id.
        return cur.fetchone()[0]


def store_chunks(conn, repo_id, chunks):
    """Insert one batch of chunks, embedding included.

    Each chunk is a dict carrying a complete row.
    {"file_id": 7, "start_line": 1, "end_line": 60,
    "content": "---", "embedding": [0.021, -0.554, ...]}

    file_id lives inside each chunk because one batch of chunks may span
    several files; repo_id is an argument because it is the same for the whole run.

    index.py attaches embeddings to chunks immediately after embedder
    returns them, while positional correspondence still holds. Pair them
    ASAP as soon as embedder produce them (the API guarantees results come back in input order).
    From here on the pairing cannot get wrong, because nothing is left to pair.

    Returns nothing - no row references a chunk, so its id is never needed.
    Raises on a duplicate (file_id, start_line) or a missing key: both mean an upstream bug,
    and the whole repository rolls back.
    """

    # One tuple per row, values in the same order as the INSERT's column list.
    rows = []
    for c in chunks:
        rows.append((repo_id, c["file_id"], c["content"], c["start_line"], c["end_line"], c["embedding"]))

    with conn.cursor() as cur:
        # executemany: ONE SQL string, many parameter sets. psycopg pipelines
        # the whole batch instead of waiting for a reply per row, so the cost
        # is ~one round trip for the batch whatever its size — not one per row.
        cur.executemany(
            """
            INSERT INTO code_chunks
                (repository_id, file_id, content, start_line, end_line, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
            rows,
        )


def mark_job_completed(conn, job_id, conclusion, error=None):
    """Record that one indexing run has ended, and how it ended.

    IN   conn        an open psycopg connection
         job_id      int, from start_job
         conclusion  'success'   the run indexed the repository
                     'skipped'   already on that commit, nothing to do
                     'failure'   something broke; error holds the reason
                     'cancelled' stopped, or swept up after a hard kill
         error       str, only on a failure. Trimmed to 2000 characters.

    Returns nothing.

    Called on every path out of a run. status is always 'completed' because the
    run ended whichever way it went; conclusion is what differs. A failed run
    gets this call and nothing else — the repository is left on its previous
    commit, still answering questions.

    On the failure path this MUST run in a fresh transaction. The one that
    failed is aborted and refuses every statement, including this one, until it
    is rolled back.

    'error' is a short human-readable line, not a traceback: it is shown to
    whoever asked for the index. The traceback belongs in the logs.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE indexing_jobs
               SET status      = 'completed',
                   conclusion  = %s,
                   error       = %s,
                   -- clock_timestamp, not now(): now() is the transaction's start time
                   finished_at = clock_timestamp()
             WHERE id = %s
            """,
            (conclusion, error[:2000] if error else None, job_id),
        )


def mark_repository_indexed(conn, repo_id, commit_sha, file_count, chunk_count, total_lines):
    """Record that one repository is now indexed at the given commit.

    IN   conn         an open psycopg connection
         repo_id      int
         commit_sha   str — the commit whose files and chunks were just written
         file_count   int
         chunk_count  int
         total_lines  int

    Returns nothing.

    Used by both a first index and a re-index. Neither cares what was there
    before: the row is overwritten with the commit just indexed and its stats.

    commit_sha going from NULL to a value is what makes a repository
    answerable. It is set here, with the counts, in the transaction that wrote
    the content, so the commit and the content can never disagree.

    The counts come from index.py, which knows them from walking. Counting them
    here would be three extra queries for numbers already in hand.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE repositories
               SET commit_sha  = %s,
                   file_count  = %s,
                   chunk_count = %s,
                   total_lines = %s,
                   -- clock_timestamp, not now(): now() is the transaction's start time
                   indexed_at  = clock_timestamp()
             WHERE id = %s
            """,
            (commit_sha, file_count, chunk_count, total_lines, repo_id),
        )


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    import psycopg

    load_dotenv()

    # Hand-written, in the walker's shape. Testing store.py alone — if the
    # walker were involved, a failure here could be either module's fault.
    fake_file = {
        "path": "Server/index.js",
        "language": "JavaScript",
        "line_count": 125,
        "content": "const express = require('express');\n",
    }


    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)

        repo_id, from_sha = get_or_create_repository(conn, "amritrwt22", "WorkWave-main")
        print("repository id:", repo_id, " currently serving:", from_sha)

        job_id = start_job(conn, repo_id, from_sha, "c3184a5")
        print("job id:", job_id)

        delete_repository_content(conn, repo_id)

        file_id = store_file(conn, repo_id, fake_file)
        print("file id:", file_id)

        fake_chunks = [
            {"file_id": file_id, "start_line": 1, "end_line": 60,
             "content": "chunk_one", "embedding": [0.1] * 768},
            {"file_id": file_id, "start_line": 51, "end_line": 110,
             "content": "chunk two", "embedding": [0.2] * 768},
        ]

        store_chunks(conn, repo_id, fake_chunks)
        print("stored", len(fake_chunks), "chunks")

        mark_repository_indexed(conn, repo_id, "c3184a5",
                                file_count=1, chunk_count=2, total_lines=125)
        mark_job_completed(conn, job_id, "success")
        print("indexed at c3184a5, job closed")

