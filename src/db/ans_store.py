# src/db/ans_store.py : the ask path's database layer.
#
# One file because asking a question is one sequence, not three concerns:
#
#   R1  get_repository_by_name   which repo, and can it be asked about
#   R2  get_cached_answer        have we answered this exact question before
#   T1  store_answer             the one write - the question and its chunks
#
# R1 and R2 are plain SELECTs - nothing to roll back. Only T1 needs a
# transaction, because it is two INSERTs that have to land together.
#
# NOTE: store.py calls itself the only module that writes to Postgres. That was
# true until this file; T1 is the other writer.

from psycopg.types.json import Json   # wraps a Python list for a jsonb column


def get_repository_by_name(conn, owner, repo):
    """Find one repository by its GitHub name, and whether it can be asked about.

    IN   conn   an open psycopg connection
         owner  "amritrwt22"
         repo   "RepoLens"

    OUT  {"id": int, "commit_sha": str or None}
         None if no such repository has ever been submitted.

    The ask path starts from a URL - /amritrwt22/RepoLens - not from an id, so
    this is the one lookup that goes by name.

    Matched on the lowercased pair, because GitHub treats repository names as
    case-insensitive and the UNIQUE index is on owner_norm/repo_norm. /RepoLens
    and /repolens find the same row.

    commit_sha answers "can this be asked about" by itself:

        None     no finished index, so there are no chunks to search
        a sha    answerable - and the cache key for every question asked
                 against this version of the code

    This function never looks at indexing_jobs. If commit_sha is set the repo
    is answerable, whatever a re-index is doing behind it.

    Raises nothing. "No such repository" is one of three normal answers, not an
    error - the caller decides whether that means a 404 or a message.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, commit_sha
            FROM repositories
            WHERE owner_norm = lower(%s) AND repo_norm = lower(%s)
            """,
            (owner, repo),
        )
        row = cur.fetchone()

    # fetchone returns None when nothing matched. That is a repository nobody has
    # ever submitted - different from one submitted but not indexed, which
    # returns a row with commit_sha None.
    if row is None:
        return None

    return {"id": row[0], "commit_sha": row[1]}


def normalise_question(question):
    """Reduce a question to the form the cache is keyed on.

    IN   question  str, exactly as typed
    OUT  str       the cache key form

        "   How DOES AUTH works ?? ?? ??"  ->  "how does auth works"

    Four rules: trim the ends, collapse inner runs of whitespace to one space,
    lowercase, drop trailing punctuation. So the same question typed with or
    without a question mark is one cache row rather than two Gemini calls.

    Deliberately conservative. Stripping all punctuation would also merge
    "what does != do" with "what does == do" - a wrong answer served with valid
    citations. A cache miss costs money; a wrong hit costs correctness.

    Used by both the cache lookup and the insert. If the two normalised
    differently the cache would never hit, and nothing would say so.
    """
    # split() breaks on any run of whitespace and drops the empties; join puts
    # the words back with one space each. Ends trimmed, inner runs collapsed.
    #     "   How  DOES AUTH works ?? ?? ??"  ->  "How DOES AUTH works ?? ?? ??"
    collapsed = " ".join(question.split())

    # lower() so "How" and "how" are one row. rstrip then deletes from the right
    # until it hits a character not in the set - the space is in the set so the
    # whole run clears, not just the last ??.
    #     "How DOES AUTH works ?? ?? ??"  ->  "how does auth works"
    return collapsed.lower().rstrip("?!. ")


def get_cached_answer(conn, repo_id, commit_sha, question, model, prompt_version):
    """Look for an answer already stored for this exact question.

    IN   conn            an open psycopg connection
         repo_id         int, from get_repository_by_name
         commit_sha      the commit the repo is indexed at, from the same place
         question        str, exactly as typed - normalised in here
         model           which chat model would answer it
         prompt_version  which prompt wording would answer it

    OUT  {"text": str, "sources": list}   a hit
         None                             a miss

    A hit means STOP: no embedding, no vector search, no Gemini call.

    The five columns are the whole unique key on questions. Same repo, same
    commit, same question, same model, same prompt - the answer cannot differ,
    so there is no reason to pay for it twice.

    commit_sha being in the key is what invalidates the cache for free: after a
    re-index every row for the old commit stops matching. No TTL, no eviction.

    Refusals are cached like any other answer. The same question against the
    same code will refuse again, so storing it saves a pointless call.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT answer, sources
            FROM questions
            WHERE repository_id = %s
              AND commit_sha = %s
              AND question_norm = %s
              AND model = %s
              AND prompt_version = %s
            """,
            # Normalised HERE, not by the caller. The insert calls the same
            # function, so the two cannot drift apart - and a drift would be
            # silent, just a cache that never hits.
            (repo_id, commit_sha,normalise_question(question), model, prompt_version),
        )
        row = cur.fetchone()

    # No row means nobody has asked this before - not an error.
    if row is None:
        return None

    # sources is jsonb; psycopg turns that into a Python list on the way out, so
    # no json.loads. Same shape answer() returns on a miss, so a cache hit is
    # indistinguishable to the caller.
    return {"text": row[0], "sources": row[1]}

def github_url(owner, repo, commit_sha, path, start_line, end_line):
    """Build a permanent GitHub link to one chunk's lines.

    IN   owner       "amritrwt22"
         repo        "RepoLens"
         commit_sha  the full 40-character sha the repo was indexed at
         path        "src/pipeline/retry.py", relative to the repo root
         start_line  1
         end_line    60

    OUT  str

        https://github.com/amritrwt22/RepoLens/blob/df48637.../src/pipeline/retry.py#L1-L60

    The full sha rather than a branch name is what makes it permanent. /blob/main
    points at whatever that file is today, so a citation would quietly start
    pointing at the wrong lines the moment someone edits it. The sha freezes it.

    Stored in questions.sources rather than rebuilt on every read, because that
    column is returned whole on every cache hit. retrieved_chunks deliberately
    does NOT store it - that table is read by analytics queries, so it keeps the
    raw path and lines and derives the URL only if something asks.
    """
    return (f"https://github.com/{owner}/{repo}/blob/{commit_sha}"
            f"/{path}#L{start_line}-L{end_line}")

def store_question(conn, repo_id, commit_sha, question, question_embedding,
                   answer_text, sources, model, prompt_version):
    """Store one answered question. Returns its id, or None on a conflict.

    IN   conn                an open psycopg connection
         repo_id             int, from get_repository_by_name
         commit_sha          the commit this was answered against
         question            str, as typed - normalised in here
         question_embedding  list of 768 floats, or None
         answer_text         what the model wrote, with [1] [2] still in it
         sources             list of dicts, from build_sources - goes to jsonb
         model               e.g. "gemini-3.5-flash-lite"
         prompt_version      the hash of the prompt files

    OUT  int   the new id - this request wrote the row
         None  somebody else wrote it first already, so we dont write again

    Does not commit. answer.py owns the transaction boundary, the same way
    index.py owns them for store.py.

    TWO PEOPLE, SAME QUESTION, SAME MOMENT
    Both miss the cache, so both run the whole pipeline - embed, search, Gemini,
    the lot - and both arrive here. The quota is spent twice; nothing prevents
    that, and nothing needs to. What matters is that only ONE row is written.

    ON CONFLICT DO NOTHING is what guarantees it. Without it the second INSERT
    raises a unique violation, which would be a 500 for somebody holding a
    perfectly good answer.

    The loser gets None back and returns its answer to its user anyway. It just
    does not store it - the winner's row is already there, and its eight
    retrieved_chunks rows with it. Writing again would duplicate those eight and
    quietly double-count every analytics query over that table.

    ONE PERSON CLICKING TWICE
    Not handled here, and does not need to be: the UI disables the ask button
    until the answer arrives.

    And the answer is returned AFTER the write, never before - so a user cannot
    receive an answer, immediately ask the same thing, and miss a cache that was
    still being written.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO questions
                (repository_id, commit_sha, question, question_norm, answer,
                 sources, question_embedding, model, prompt_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            # Both form of ques are stored: raw one for display, normalized one for cache key for lookup.
            # Json() wraps the list for the jsonb columns; psycopg won't convert a plain python list on its own.
            (repo_id, commit_sha, question, normalise_question(question),
             answer_text, Json(sources), question_embedding, model, prompt_version)
        )
        row = cur.fetchone()

    # return the new id of row if written, if there is conflict as question already exists
    # then no new row is inserted and we return none.
    if row is None:
        return None

    return row[0]


def store_retrieved_chunks(conn, question_id, chunks, cited):
    """Store every chunk that was retrieved for one question.

    IN   conn         an open psycopg connection
         question_id  int, from store_question
         chunks       list of dicts, nearest first - what search() returns:
                        {"chunk_id": int, "path": str, "start_line": int,
                         "end_line": int, "content": str, "distance": float}
         cited        set of ints - the citation numbers the answer used, {1, 3}

    OUT  None

    ALL k rows are written, not just the cited ones. A row with cited=false says
    "the search found this and the model ignored it", which is what separates
    retrieval quality from generation quality.

    path, start_line and end_line are copied here rather than linked to
    code_chunks, so this history survives a re-index.
    """
    
    rows = []
    
    # enumerate gives the counter and the item together:
    #     enumerate(chunks, start=1)  ->  rank=1 chunk=chunks[0]
    #                                     rank=2 chunk=chunks[1]
    #                                     rank=3 chunk=chunks[2]
    #
    # start=1 because citation [1] means the FIRST chunk, so rank is already
    # the citation number and there is no +1 anywhere.
    
    for rank, chunk in enumerate(chunks, start=1):
        rows.append((
            question_id, 
            rank,
            chunk["distance"],
            rank in cited,
            chunk["path"],
            chunk["start_line"],
            chunk["end_line"],
        ))
        # One tuple per chunk, in the order the INSERT's %s expect.
        # `rank in cited` is True when the answer cited this chunk.
        #
        # 3 chunks, the answer cited [1] and [3]  ->
        #     (99, 1, 0.18, True,  'src/pipeline/retry.py',    1,  60)
        #     (99, 2, 0.24, False, 'src/pipeline/embedder.py', 61, 120)
        #     (99, 3, 0.29, True,  'src/pipeline/walk.py',     1,  60)
        
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO retrieved_chunks
              (question_id, rank, distance, cited, path, start_line, end_line)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,  
        )
        