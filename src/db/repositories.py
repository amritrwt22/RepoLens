# src/db/repositories.py : reads on the repositories table.
#
#   list_repositories   every indexed repository, newest first — the gallery
#
# Returns rows from this table only. A card also needs its language mix, which
# lives in files; joining the two is the handler's job, not this file's.
#
# Writes go through store.py. Reads are split per table, so anything asking a
# question of repositories lands here.

def list_repositories(conn):
    """Every repository that finished indexing, newest first.

    IN   conn   an open psycopg connection

    OUT  list of dicts — id, owner, repo, file_count, chunk_count,
         total_lines, indexed_at. Empty list when none are indexed.

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
            SELECT id, owner, repo, file_count, chunk_count, total_lines,
                   indexed_at
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
                "chunk_count": row[4],
                "total_lines": row[5],
                "indexed_at": row[6],
            })

        return result
