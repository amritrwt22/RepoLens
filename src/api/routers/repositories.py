# src/api/routers/repositories.py : the /v1/repositories endpoints.
#
#   GET /v1/repositories   the gallery - every indexed repository
#
# Handlers translate HTTP and nothing else: take the connection the dependency
# lends them, call db/, shape the result, hand it back. No SQL here, and no RAG -
# a gallery has nothing to orchestrate, so it never reaches services/.

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_connection
from src.db.repositories import list_repositories, get_repository
from src.db.files import languages_by_repository
from src.db.jobs import latest_job

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

    # 1. [{"id":, "owner":, "repo":, "file_count":, "total_lines":,
    #      "indexed_at":}, ...]   newest first
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
            "total_lines": r["total_lines"],
            "indexed_at":  r["indexed_at"],
            "languages":   langs,
        })

    # 5. the object, not a bare list - see the docstring
    return {"repositories": gallery}


# Two fields rather than one "status" word: one word cannot say "answerable"
# and "last run failed" at once, which is why the schema splits them too.
#
# job.error is deliberately withheld - it holds raw exception text, down to
# the provider's name and error codes.
#
# Three queries: the row, its languages, its latest job. The id ties them
# together and never reaches the response.
@router.get("/{owner}/{repo}", status_code=200)
def get_repo(owner: str, repo: str, conn = Depends(get_connection)):
    """One repository by name, in whatever state it is in.

    REQUEST
        GET /v1/repositories/{owner}/{repo}

        owner and repo are matched case-insensitively, so /RepoLens and
        /repolens are the same repository. No query string, no body.

    RESPONSE  200 application/json

        {
          "owner": "amritrwt22",
          "repo": "RepoLens",
          "commit_sha": "3599ffdf66656e26d1af70fe5829f453c45541cf",
          "file_count": 28,
          "total_lines": 4802,
          "indexed_at": "2026-10-23T06:54:28.050783+00:00",
          "languages": [
            { "language": "Python",   "line_count": 3299 },
            { "language": "Markdown", "line_count": 1271 },
            { "language": "SQL",      "line_count": 232  }
          ],
          "job": {
            "status": "completed",
            "conclusion": "success",
            "finished_at": "2026-10-23T06:54:28.067889+00:00"
          }
        }

        commit_sha is the gate: not null means the repository can be asked
        about, null means nothing is indexed yet. job is the last indexing
        run, whatever its outcome.

        The two are independent - a repository can hold a good commit_sha and
        a failed last run at once, staying answerable on the older commit:

          commit_sha   job                     means
          set          completed / success     ready
          set          in_progress             ready, re-indexing now
          set          completed / failure     ready, last update failed
          null         in_progress             first index running
          null         completed / failure     first index failed

    STATUS CODES
        200  the repository exists, in any state
        404  no repository by that owner and name
        503  PostgreSQL unreachable
        500  an unhandled exception
    """
    
    # 1. {"id":, "owner":, "repo":, "commit_sha":, "file_count":,
    #     "total_lines":, "indexed_at":}   or None if no such repository
    repository = get_repository(conn, owner, repo)
    
    # raise HTTPException sends a response: that status code, and
    # {"detail": "..."} as the body. FastAPI catches this one class itself -
    # any other exception is unhandled and becomes a raw 500.
    #
    # return at the bottom sends the body with the decorator's status_code.
    if repository is None:
        raise HTTPException(status_code=404, detail="no such repository")

    # 2. {2: [("Python", 3299), ("SQL", 232)]} when the repo has files, or {}
    #    when it has none - the dict is built from the rows, so no files means
    #    no rows means no key. Never {2: []}.
    #
    #    .get(id, []) flattens both cases into a list, possibly empty.
    #    languages[id] would raise KeyError on the second one
    languages = languages_by_repository(conn, [repository["id"]]).get(repository["id"], [])
    
    # 3. {"status":, "conclusion":, "error":, "finished_at":}  or None
    job = latest_job(conn, repository["id"])
    
    # 4. the response object. id is used above and dropped here, and each
    #    ("Python", 3299) becomes {"language":, "line_count":}
    langs = []
    for language, line_count in languages:
        langs.append({"language": language, "line_count": line_count})
        
    # 5. job.error is left out on purpose - it holds raw exception text
    return {
        "owner":       repository["owner"],
        "repo":        repository["repo"],
        "commit_sha":  repository["commit_sha"],
        "file_count":  repository["file_count"],
        "total_lines": repository["total_lines"],
        "indexed_at":  repository["indexed_at"],
        "languages":   langs,
        "job": {
            "status":      job["status"],
            "conclusion":  job["conclusion"],
            "finished_at": job["finished_at"],
        } 
    }






# ---------------------------------------------------------------------------
# SENDING A STATUS CODE - express vs fastapi
# ---------------------------------------------------------------------------
#
# EXPRESS - you hold `res`, so one mechanism sends every code
#
#     function getRepo(req, res) {
#       const repo = findRepo(owner, name)
#
#       if (!repo)
#         return res.status(404).json({ message: "no such repository" })
#
#       if (!repo.commit_sha)
#         return res.status(409).json({ message: "not indexed yet" })
#
#       return res.status(200).json(repo)
#     }
#
#   Every branch picks its own code. Nothing declared anywhere.
#
#
# FASTAPI - no `res`. The return value IS the body, so success and failure
# leave by different doors
#
#     @router.get("/{owner}/{repo}", status_code=200)
#     def get_repo(owner: str, repo: str, conn = Depends(get_connection)):
#
#         repository = get_repository(conn, owner, repo)
#
#         if repository is None:
#             raise HTTPException(status_code=404, detail="no such repository")
#
#         if repository["commit_sha"] is None:
#             raise HTTPException(status_code=409, detail="not indexed yet")
#
#         return repository
#
#   Same two ifs. The difference is only how each one answers:
#
#     return    -> the body, with the decorator's code (200 here)
#     raise     -> 404 {"detail": "no such repository"}
#                  A response, not a crash. Exits immediately, so nothing
#                  below needs an else
#
#
# CODES THIS HANDLER NEVER WRITES
#
#     422   a bad request body. FastAPI checks it against the type hints
#           before calling this function, and answers on its own
#
#     503   the database is unreachable. Every route fails the same way, so
#           it is caught once by a global handler on app, not four times here
#
#     500   anything unhandled. Same - one global handler, not four

