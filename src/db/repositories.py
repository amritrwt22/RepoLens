# src/db/repositories.py : reads on the repositories table.
#
#   list_repositories   every indexed repository, newest first — the gallery
#   get_repository      one by owner/repo, in any state — the repo page
#
# Returns rows from this table only. A card also needs its language mix, which
# lives in files; joining the two is the handler's job, not this file's.
#
# Writes go through store.py. Reads are split per table, so anything asking a
# question of repositories lands here.

def list_repositories(conn):
    """Every repository that finished indexing, newest first.

    IN   conn   an open psycopg connection

    OUT  list of dicts — id, owner, repo, file_count, total_lines,
         indexed_at. Empty list when none are indexed.

    commit_sha NULL means the row exists but nothing was ever indexed into
    it, so there is nothing to answer from and no card to show.

    Sorted on indexed_at with id breaking ties: two repositories indexed in
    the same transaction share an indexed_at, and without the tiebreak their
    order flips between requests.

    An empty list is a real answer, not an error — the gallery exists and
    happens to hold nothing. The endpoint returns 200 with [], never 404.

    id is returned although the API never exposes it: the handler needs it to
    attach each repository's languages, which files.py keys on repository_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, owner, repo, file_count, total_lines, indexed_at
            FROM repositories
            WHERE commit_sha IS NOT NULL
            ORDER BY indexed_at DESC, id DESC
            """
        )
        # list of tuples, values in SELECT order: (2, 'amritrwt22', 'RepoLens', ...)
        rows = cur.fetchall()

        # tuples -> dicts, so callers use names not row[i]
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "owner": row[1],
                "repo": row[2],
                "file_count": row[3],
                "total_lines": row[4],
                "indexed_at": row[5],
            })

        return result


def get_repository(conn, owner, repo):
    """One repository by its GitHub name, whatever state it is in.

    IN   conn   an open psycopg connection
         owner  "amritrwt22"
         repo   "RepoLens"

    OUT  {"id":, "owner":, "repo":, "commit_sha":, "file_count":,
          "total_lines":, "indexed_at":}
         None when no such repository was ever submitted.

    None is what the handler turns into a 404. Unlike the gallery there is no
    commit_sha filter - this page answers for a repository in any state, and
    commit_sha being NULL is part of the answer, not a reason to hide it.

    Matched on the lowercased pair because GitHub treats repository names as
    case-insensitive, and the UNIQUE index is on owner_norm/repo_norm.
    /RepoLens and /repolens find the same row.

    id is returned although the API never exposes it: the handler needs it for
    the languages and the latest job.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, owner, repo, commit_sha, file_count, total_lines,
                   indexed_at
            FROM repositories
            WHERE owner_norm = lower(%s) AND repo_norm = lower(%s)
            """,
            (owner, repo),
        )
        # one tuple or None, values in SELECT order
        row = cur.fetchone()

    # fetchone gives None when nothing matched
    if row is None:
        return None

    return {
        "id": row[0],
        "owner": row[1],
        "repo": row[2],
        "commit_sha": row[3],
        "file_count": row[4],
        "total_lines": row[5],
        "indexed_at": row[6],
    }
