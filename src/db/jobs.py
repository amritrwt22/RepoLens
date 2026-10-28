# src/db/jobs.py : reads on the indexing_jobs table.
#
#   latest_job   the most recent run for one repository
#
# One row per indexing attempt. Three columns describe it, and they fill in
# that order:
#
#   status      where the run is
#                 queued        row written, nothing started yet
#                 in_progress   running
#                 completed     over, whatever the outcome
#
#   conclusion  how it ended. NULL until status is 'completed'
#                 success     the repository was indexed
#                 skipped     already on that commit, nothing to do
#                 failure     something broke
#                 cancelled   stopped by Ctrl-C, or swept up after a kill
#
#   error       why a run did not succeed. Set on failure and on cancelled,
#               NULL otherwise. Raw exception text - useful here, not fit to
#               return over HTTP
#
# So a running job is {in_progress, NULL, NULL} and a good one ends as
# {completed, success, NULL}.
#
# Whether a repo can be ASKED about is a different fact, on
# repositories.commit_sha. A repo can be answerable and have a failed last
# run at once, so the handler keeps the two separate.
#
# Writes go through store.py.

def latest_job(conn, repo_id):
    """The most recent indexing run for one repository.

    IN   conn     an open psycopg connection
         repo_id  int, from get_repository

    OUT  {"status":, "conclusion":, "error":, "finished_at":}
         None only if repo_id does not exist.

    conclusion is NULL until status reaches 'completed', so a running job is
    {"status": "in_progress", "conclusion": None}.

    Ordered by id, not time: started_at is NULL while queued and finished_at
    is NULL while running - exactly the rows worth finding.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, conclusion, error, finished_at
            FROM indexing_jobs
            WHERE repository_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (repo_id,),
        )
        # one tuple or None, values in SELECT order
        row = cur.fetchone()

    # should never fire: index.py inserts the repository and its first job in
    # one transaction, so a repo that exists always has at least one job
    if row is None:
        return None

    return {
        "status": row[0],
        "conclusion": row[1],
        "error": row[2],
        "finished_at": row[3],
    }
