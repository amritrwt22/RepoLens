# src/api/routers/repositories.py : the /v1/repositories endpoints.
#
#   GET /v1/repositories   the gallery - every indexed repository
#
# Handlers translate HTTP and nothing else: take the connection the dependency
# lends them, call db/, shape the result, hand it back. No SQL here, and no RAG -
# a gallery has nothing to orchestrate, so it never reaches services/.

from fastapi import APIRouter, Depends

from src.api.dependencies import get_connection
from src.db.repositories import list_repositories
from src.db.files import languages_by_repository

# the box this file's routes go in. main.py mounts it at /v1/repositories, so
# the paths below are only what comes after that - "" is the gallery itself.
router = APIRouter()


# A JSON object, not a bare array - both are JSON, but an object is keyed by
# name like a dict, an array by position like a list:
#
#     array    [ {"owner": "amritrwt22", ...}, {"owner": "amritrwt22", ...} ]
#     object   { "repositories": [ ...the same two... ] }
#
# A list can only hold more of the same thing. Adding "total" or a cursor to
# the object is a new key nobody notices; adding it to the array means either
# a stray item clients render as a card, or changing the shape and breaking
# all of them.
#
# Two queries, not one per card: the repository rows from one, the language
# mix from another, matched on the repository id - used here, then dropped.
#
# These notes stay as # comments, not docstring: FastAPI publishes the
# docstring as this endpoint's description on /docs. Reasoning is ours.
@router.get("")
def list_repos(conn = Depends(get_connection)):
    """The gallery: every indexed repository, newest first.

    REQUEST
        GET /v1/repositories

        No path parameters, no query string, no body. Nothing a caller sends
        can be wrong, which is why there is no 400 and no 422 here.

    RESPONSE  200 application/json

        {
          "repositories": [
            {
              "owner": "amritrwt22",
              "repo": "RepoLens",
              "file_count": 28,
              "chunk_count": 104,
              "total_lines": 4802,
              "indexed_at": "2026-10-23T06:54:28.050783+00:00",
              "languages": [
                { "language": "Python",   "line_count": 3299 },
                { "language": "Markdown", "line_count": 1271 },
                { "language": "SQL",      "line_count": 232  }
              ]
            }
          ]
        }

        languages is largest-first, and a repository with no files has [].
        The caller turns the line counts into the percentages on the bar.

    STATUS CODES
        200  always, including an empty gallery: {"repositories": []}.
             The collection exists and happens to hold nothing, so 404 would
             be a lie - the URL names something real.
        503  PostgreSQL unreachable. Not caught here; psycopg raises and a
             global exception handler turns it into 503 for every endpoint.
        500  an unhandled exception. Nothing to write, by definition.

    """

    # 1. [{"id":, "owner":, "repo":, "file_count":, "chunk_count":,
    #      "total_lines":, "indexed_at":}, ...]   newest first
    repos = list_repositories(conn)

    # 2. the ids on their own, for the next query: [2, 1]
    ids = []
    for r in repos:
        ids.append(r["id"])

    # 3. the language mix, keyed by repo id, largest first
    #    {2: [("Python", 3299), ("SQL", 232)], 1: [("JavaScript", 125)]}
    languages = languages_by_repository(conn, ids)

    # 4. one response object per card. id is used above and dropped here,
    #    and each ("Python", 3299) becomes {"language":, "line_count":}
    gallery = []
    for r in repos:

        # a repo with no files is absent from the dict, so .get hands back
        # [] and this loop runs zero times - langs stays [], no language bar
        # on that card. languages[...] would raise KeyError and 500 them all
        langs = []
        for language, line_count in languages.get(r["id"], []):
            langs.append({"language": language, "line_count": line_count})

        gallery.append({
            "owner":       r["owner"],
            "repo":        r["repo"],
            "file_count":  r["file_count"],
            "chunk_count": r["chunk_count"],
            "total_lines": r["total_lines"],
            "indexed_at":  r["indexed_at"],
            "languages":   langs,
        })

    # 5. the object, not a bare list - see the docstring
    return {"repositories": gallery}
