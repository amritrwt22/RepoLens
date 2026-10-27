# src/db/files.py : reads on the files table.
#
#   languages_by_repository   lines per language, for a set of repositories
#
# Returns rows from this table only. The gallery card also needs the owner,
# the repo name and the counts, which live in repositories; joining the two is
# the handler's job, not this file's.
#
# Writes go through store.py. Reads are split per table, so anything asking a
# question of files lands here.


def languages_by_repository(conn, repo_ids):
    """Lines per language, for a set of repositories.

    IN   conn      an open psycopg connection
         repo_ids  list of ints, from list_repositories

    OUT  dict of repo_id -> [(language, line_count)], largest first:

           {2: [("Python", 3299), ("Markdown", 1271), ("SQL", 232)],
            1: [("JavaScript", 125)]}

         {} when repo_ids is empty.

    A list of ids, not one, so the whole gallery costs one query.

    GROUP BY repository_id, language - one row per repo-language pair. Group
    on language alone and every repository's Python merges into one number.

    ORDER BY line_count DESC - largest language first, so the card's bar
    renders in order and the frontend never sorts.

    Lines rather than file counts, because the card sizes its bar on lines.
    Raw counts, not percentages - the caller can work out 69% from 3299, but
    not 3299 from 69%.

    A repo with no files is absent from the dict, not an empty entry -
    GROUP BY makes no row from no rows. Use .get(repo_id, []) or one such
    repo raises KeyError and takes the whole gallery down.
    """
    # ANY(ARRAY[]) would return nothing anyway - this saves the round trip
    if not repo_ids:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT repository_id, language, sum(line_count) AS line_count
            FROM files
            WHERE repository_id = ANY(%s)
            GROUP BY repository_id, language
            ORDER BY repository_id, line_count DESC
            """,
            (repo_ids,),
        )
        # list of tuples, values in SELECT order: (2, 'Python', 3299)
        rows = cur.fetchall()

    # the 4 flat rows above become 2 keys, each holding a LIST of tuples -
    # a repo has several languages:  {2: [('Python', 3299), ('SQL', 232)]}
    #
    # no sorted() needed - the ORDER BY already did it, and append keeps
    # the order rows arrive in
    result = {}
    for repo_id, language, line_count in rows:
        if repo_id not in result:
            result[repo_id] = []
        result[repo_id].append((language, line_count))

    return result
