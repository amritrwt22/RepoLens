-- RepoLens schema — six tables: repositories, indexing_jobs, files,
-- code_chunks, questions, retrieved_chunks.
--
-- Shape is dimension-and-fact: `repositories` is the product, and anything
-- done *to* a repo gets its own table with an FK back, not a column here.
-- Vectors are 768-dim, cosine (<=>) — pgvector's HNSW caps at 2,000 dims.
--
-- Column-by-column reasons: docs/18-repolens_design/schema-design.md
-- Apply: psql postgresql://repolens:repolens@localhost:5433/repolens -f src/db/schema.sql
--
-- This file drops and recreates — safe only while the data is throwaway. Delete
-- the DROP at the first real deploy and move to numbered migrations.

CREATE EXTENSION IF NOT EXISTS vector;

-- Wipe the tables first, so running this file always rebuilds them from scratch.
DROP TABLE IF EXISTS retrieved_chunks, questions, code_chunks,
                     files, indexing_jobs, repositories CASCADE;

-- One row per repo. The root — everything else points back here.
--
-- commit_sha = can we answer questions yet.
--   first index:  NULL until it succeeds, so nothing is servable before that
--   re-index:     keeps the old commit the whole time, and only moves if the
--                 new one succeeds — so a failed re-index still answers fine
--
-- Run state (queued / running / failed) lives on indexing_jobs, because one
-- status column could not say "usable" and "last attempt failed" at once.
--
-- The three counts are copies written at the end of an index, so the gallery
-- does not recount per card.

CREATE TABLE repositories (
    id          serial primary key,
    owner       text not null,
    repo        text not null,

    commit_sha  text,                 -- NULL = never indexed, nothing to answer from
    file_count  integer,              -- NULL = not known yet; 0 = a real empty repo
    chunk_count integer,
    total_lines integer,

    created_at  timestamptz not null default now(),
    indexed_at  timestamptz,          -- when the currently served index finished

    UNIQUE (owner, repo)              -- one row per repo, and the lookup key for
                                      -- GET /v1/repositories/{owner}/{repo}
);

-- One row per index attempt. status = where the run is, conclusion = how it ended.
-- conclusion stays NULL until status reaches 'completed'.
-- from_sha NULL = this was the repo's first index.

CREATE TABLE indexing_jobs (
    id             serial primary key,
    repository_id  integer not null references repositories(id) on delete cascade,

    from_sha       text,                  -- NULL = first index
    to_sha         text not null,         -- the commit this run targets

    status         text not null 
                   CHECK (status IN ('queued','in_progress','completed')),
    conclusion     text                   -- NULL until completed
                   CHECK (conclusion IN ('success','failure','cancelled')),

    error          text,                  -- set only on failure
    started_at     timestamptz,           -- NULL while queued
    finished_at    timestamptz            -- NULL until completed
);

-- One row per source file the walker kept. content is the full text — stored so
-- re-chunking does not have to re-read the original tree.

CREATE TABLE files (
    id             serial primary key,
    repository_id  integer not null references repositories(id) on delete cascade,

    path           text not null,      -- relative to repo root, e.g. "src/db/store.py"
    language       text not null,
    line_count     integer not null,
    content        text not null,

    UNIQUE (repository_id, path)       -- same path twice in one repo is a bug
);

-- One row per 60-line chunk, with its embedding. This is what vector search reads.
--
-- repository_id is duplicated here on purpose: search filters on it directly
-- (WHERE repository_id = ...) instead of joining files to narrow the rows.
-- The join to files is only for the citation path.
--
-- No commit_sha: a re-index replaces every chunk in the same transaction that
-- moves repositories.commit_sha, so these rows always match it.

CREATE TABLE code_chunks (
    id             serial primary key,
    repository_id  integer not null references repositories(id) on delete cascade,
    file_id        integer not null references files(id) on delete cascade,

    content        text not null,
    start_line     integer not null,
    end_line       integer not null,
    embedding      vector(768) not null,   -- 768 dims, compared with <=> (cosine)

    UNIQUE (file_id, start_line)           -- two chunks of one file starting at
                                           -- the same line is a bug
);

-- The answer cache. An ask looks here first; a hit skips Gemini entirely.
--
-- commit_sha is a frozen copy, not a foreign key: an answer outlives the commit
-- it was written against, so it must remember which one it cited.
--
-- The UNIQUE key is the cache lookup. Changing the commit, the model or the
-- prompt version makes a new row, so old answers are never served after a
-- re-index or a model/prompt change.
--
-- A failed Gemini call writes no row at all, so the next ask can retry. A
-- refusal does get stored — it is a valid answer, with sources = [].

CREATE TABLE questions (
    id                 serial primary key,
    repository_id      integer not null references repositories(id) on delete cascade,

    commit_sha         text not null,
    question           text not null
                       CHECK (char_length(question) BETWEEN 10 AND 500),
    question_norm      text not null,   -- trimmed, lowercased, inner spaces collapsed
    answer             text not null,
    sources            jsonb not null,  -- [] on a refusal

    question_embedding vector(768),     -- stored now; nothing reads it yet
    model              text not null,
    prompt_version     text not null,

    created_at         timestamptz not null default now(),

    UNIQUE (repository_id, commit_sha, question_norm, model, prompt_version)
);

-- One row per chunk search returned for a question (8 per answer), with its
-- rank, distance, and whether Gemini actually cited it.
--
-- This is the only data here that cannot be rebuilt: re-indexing replaces every
-- chunk, so what search returned for an old question is gone unless captured now.
--
-- path/start_line/end_line are a snapshot, NOT a foreign key to code_chunks —
-- an FK with ON DELETE CASCADE would wipe this history on every re-index, which
-- is exactly what the table exists to survive.
--
-- No commit_sha (join to questions) and no github_url (build it from sha + path
-- + lines): this table is read rarely, so deriving beats storing copies.

CREATE TABLE retrieved_chunks (
    id             serial primary key,
    question_id    integer not null references questions(id) on delete cascade,

    rank           integer not null,   -- 1..8, the order search returned them
    distance       real not null,      -- the <=> cosine score, lower = closer
    cited          boolean not null,   -- did Gemini use it in the answer?

    path           text not null,
    start_line     integer not null,
    end_line       integer not null
);


-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------
-- Postgres builds an index by itself when a constraint has to search the whole
-- table. PRIMARY KEY and UNIQUE do: to reject a duplicate they must know
-- whether the value is already somewhere in the table, and the index is what
-- makes that fast.
--
-- CHECK and NOT NULL only look at the row being written, so they search
-- nothing and need no index. FOREIGN KEY searches the parent table, where that
-- key is already indexed, so it adds nothing on the child side.
--
-- A composite index also serves a lookup on its leading columns alone, so
-- UNIQUE (a, b, c) covers a, and (a, b), with no extra index.
--
--
-- 6 from the primary keys — one per table:
--
--   repositories(id)   indexing_jobs(id)   files(id)
--   code_chunks(id)    questions(id)       retrieved_chunks(id)
--
--
-- 4 from the UNIQUEs:
--
--   repositories      (owner, repo)
--   files             (repository_id, path)
--   code_chunks       (file_id, start_line)
--   questions         (repository_id, commit_sha, question_norm, model, prompt_version)
--
--
-- And by the leftmost rule, those four also cover:
--
--   repositories (owner)          files (repository_id)
--   code_chunks  (file_id)        questions (repository_id)
--
-- ---------------------------------------------------------------------------
--
--
-- Not covered by anything above. One is made now; the rest wait until the
-- query that needs them exists.
--
--   code_chunks      (repository_id)   MADE — every search filters on it, and
--                                      this table grows with every repo
--
--   indexing_jobs    (repository_id)   DEFERRED — the query arrives with
--                                      GET /{owner}/{repo}; a few dozen rows
--                                      scan faster than an index anyway
--
--   retrieved_chunks (question_id)     DEFERRED — nothing reads this table yet
--
--   code_chunks      (embedding)       DEFERRED — HNSW is approximate. Under a
--                                      few thousand chunks a full scan is both
--                                      faster and exact. Measure with
--                                      EXPLAIN ANALYZE before adding it
-- ---------------------------------------------------------------------------

CREATE INDEX ON code_chunks (repository_id);
