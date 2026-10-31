<div align="center">

# RepoLens

**Ask a codebase a question. Get an answer cited to exact file paths and line numbers.**

[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/fastapi-0.141-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Postgres](https://img.shields.io/badge/postgres-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Gemini](https://img.shields.io/badge/gemini-embedding--001-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Status](https://img.shields.io/badge/status-M7%20of%20M9-orange)](#status)

</div>

---

> You want to understand a codebase you did not write — a library you depend on, a project you are
> about to contribute to, a service you have just inherited. Reading it takes days. Search finds
> string matches, not explanations. The README is nine months old.
>
> The usual answer is to clone it and point an AI editor at it: a local copy, a setup, and a token
> bill for every question. And the model will still confidently describe
> `server/middleware/auth.js` when the file is really `Server/middlewares/AuthMiddleware.js`.
>
> **RepoLens takes a GitHub URL.** It indexes the repository once, then answers questions about it
> in plain language — and every claim points at the lines it came from, **read out of the database
> rather than written by the model**. So the answer can be checked rather than trusted.

---

```mermaid
graph TD
    U[GitHub URL] --> CL[clone]
    CL -->|a temporary folder| A[Repository]
    A -->|source files| B[walk]
    B -->|60-line windows| C[chunk]
    C -->|768-dim vectors| D[embed]
    D --> DB[(Postgres + pgvector)]
    CL -.->|deleted afterwards| CL
    Q[Question] --> QE[embed]
    QE --> S[search]
    DB -->|top 8 chunks| S
    S --> P[prompt]
    P --> G[Gemini]
    G -->|answer + citations list| V[validate]
    V --> R[Cited answer]
    DB -.->|path · lines · link| R
```

**The model only ever writes a number.** The file path and line range on every citation are read
straight out of the database, so a citation cannot point at a file that does not exist.

---

## What it looks like

```console
$ python -m src.services.answer amritrwt22 RepoLens "how does retry decide how long to wait?"

INFO pipeline.llm: generated: 5409 prompt tokens, 149 response tokens

How long the retry waits depends on which error came back:

- **429 — quota exhausted.** The free-tier budget recovers all at once on a
  measured ~60 second boundary, so retry waits for that boundary rather than
  backing off [1].
- **5xx — server error.** Recovery time is unknown, so the wait doubles each
  attempt and is multiplied by a random 0.8–1.2 [2].
- **4xx — our mistake.** Never retried. Waiting cannot fix a wrong request [1].

> **Tip** — the random multiplier does nothing with one worker, but leaving it
> out causes a synchronised retry spike the moment you scale [2].

[1] src/pipeline/retry.py:1-60
[2] src/pipeline/retry.py:101-147
```

Ask it something the repository does not contain and it says so, rather than inventing an answer:

```console
$ python -m src.services.answer amritrwt22 RepoLens "how does billing work in this project?"

I don't have enough information in the available documents to answer this question.
```

---

## The one design decision everything rests on

**The model writes a number. Python writes the path.**

```
we send        →   the 8 chunks, numbered 1..8, and the shape the reply must match
                   { "answer": string, "citations": [integer] }

model returns  →   { "answer":    "Retry waits for the quota boundary [1].",
                     "citations": [1] }

we validate    →   drop any number outside 1..8
we look up     →   chunks[0]   path     src/pipeline/retry.py
                               lines    1-60
                               commit   3599ffd

we return      →   [1] src/pipeline/retry.py:1-60
                   github.com/amritrwt22/RepoLens/blob/3599ffd/src/pipeline/retry.py#L1-L60
```

**`citations` is a field, not something read back out of the prose.** `response_schema` turns on
constrained decoding, so the model can only emit a list of integers. Nothing regexes the answer.

**The path never passes through the model.** It comes from the same database row as the chunk, and
so does the link. A model that has read millions of repositories has a strong sense of what a path
*usually* looks like, so `Server/middlewares/AuthMiddleware.js` drifts to
`server/middleware/auth.js` — plausible, wrong, invisible. A number has no such gravity, and
because the numbers are a gap-free `1..k`, checking them is arithmetic.

**The link is pinned to the commit sha, not a branch.** `/blob/main` would point at the file as it
is today, so the lines would drift the moment someone edited it.

| Failure | Caught by |
|---|---|
| `[9]` cited when only 8 chunks were sent | `src/pipeline/citations.py` — arithmetic |
| An answer with no citation at all | `src/pipeline/citations.py` — arithmetic |
| The model writes `[1, 2]` and a text parser sees only the first | **impossible** — `citations` is a list, never prose |
| A path that does not exist | **impossible by construction** |
| A link whose lines shifted after someone edited the file | the commit sha in the URL |
| `[1]` cited for a claim that `[4]` supports | the eval set — needs judgement |

---

## Quick start

**Requires** Docker, Python 3.11+, the `psql` client, and a
[Gemini API key](https://aistudio.google.com/apikey) (free tier is enough).

```bash
git clone https://github.com/amritrwt22/RepoLens.git
cd RepoLens

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # fill in GEMINI_API_KEY and DATABASE_URL

docker compose up -d         # Postgres 16 + pgvector on port 5433
psql postgresql://repolens:repolens@localhost:5433/repolens -f src/db/schema.sql
```

Index a repository, then ask it things:

```bash
python -m src.services.index https://github.com/amritrwt22/RepoLens
# files: 28 lines: 4802 chunks: 104

# run it again and nothing happens — the repository is already on that commit
python -m src.services.index https://github.com/amritrwt22/RepoLens
# already indexed at df48637, nothing to do

python -m src.services.answer amritrwt22 RepoLens "how does authentication work?"
```

Retrieval alone, without spending a generation call. This one takes the numeric id, as
`eval/` does, so look it up first:

```bash
psql postgresql://repolens:repolens@localhost:5433/repolens \
  -c "SELECT id, owner, repo, commit_sha, chunk_count FROM repositories ORDER BY id;"

python -m src.pipeline.retriever <repo_id> "how does authentication work?"
```

Serve the repository reads over HTTP:

```bash
uvicorn src.api.main:app --reload
# http://127.0.0.1:8000/docs
```

Everything runs with `-m` from the repository root — imports are absolute, so
`python src/pipeline/walk.py` will not work.

---

## How it works

```
              ┌─────────────────── INDEXING ───────────────────┐
   URL   ──►  clone  ──►  walk  ──►  chunk  ──►  embed  ──►  Postgres
              a temp    28 files  104 chunks   768-dim      + pgvector
              folder,                          vectors
              deleted
              afterwards

              ┌────────────────── ANSWERING ──────────────────┐
   question    ──►  embed  ──►  <=> search  ──►  prompt  ──►  cited answer
                    768-dim     top 8 chunks    + rules
```

| Stage | File | What it does |
|---|---|---|
| Clone | `src/pipeline/clone.py` | a GitHub URL becomes a temporary folder, deleted once indexing has read it |
| Walk | `src/pipeline/walk.py` | a generator yielding one file at a time — never loads the repository into memory |
| Chunk | `src/pipeline/chunker.py` | 60-line windows with 10 lines of overlap |
| Embed | `src/pipeline/embedder.py` | batched, normalised, retries on quota exhaustion |
| Store | `src/db/store.py` | six tables, three transactions |
| Search | `src/db/ask_store.py` | one SQL query, cosine distance, `LIMIT 8` |
| Answer | `src/services/answer.py` | orchestrates the five steps, owns the transaction |
| Serve | `src/api/` | the FastAPI application, the pool, and the routers |

### Six tables

```mermaid
erDiagram
    repositories ||--o{ indexing_jobs : "one per attempt"
    repositories ||--o{ files : ""
    files        ||--o{ code_chunks : ""
    repositories ||--o{ questions : ""
    questions    ||--o{ retrieved_chunks : ""
```

| Table | Holds | |
|---|---|---|
| `repositories` | `owner · repo · commit_sha · counts · indexed_at` | what we have indexed |
| `indexing_jobs` | `from_sha · to_sha · status · conclusion · error · timing` | one row per attempt, and how it went |
| `files` | `path · language · line_count · content` | |
| `code_chunks` | `content · start_line · end_line · embedding vector(768)` | |
| `questions` | `question · answer · sources · commit_sha · embedding` | every answer, pinned to the commit — so asking the same question twice costs no API call |
| `retrieved_chunks` | `rank · distance · cited` | which chunks were retrieved, and which the answer actually used |

**A repository row is what exists; a job row is what happened to it.** They are separate so a
failed re-index lands on the job — the repository keeps pointing at the last commit that indexed
successfully, and carries on answering questions.

`code_chunks.repository_id` is denormalised on purpose: every similarity search filters by
repository, and without it each search would need a join to `files` first.

### One code path, three outcomes

Looking up a repository also returns the commit it was last indexed at. That single value decides
the run — there is no separate "first time" branch anywhere:

```mermaid
graph TD
    S[look up the repository] --> Q{what commit<br/>was it last<br/>indexed at?}
    Q -->|nothing stored| A[index it]
    Q -->|an older commit| B[re-index it]
    Q -->|the same commit| C[skipped]
    A --> D[(stored)]
    B --> D
```

Deleting old content removes nothing when there is none, and a repository that has never been
indexed cannot match the commit about to be indexed. The third case is recorded as **`skipped`**,
so a run that did nothing is distinguishable from one that indexed everything.

### Three transactions

```mermaid
graph TD
    T1[T1 · open the run<br/>upsert the repository<br/>open the job row] --> C1[COMMIT]
    C1 --> T2[T2 · swap the content<br/>delete old · write new<br/>move commit_sha · close the job]
    T2 -->|all of it| C2[COMMIT]
    T2 -->|anything raised| T3[T3 · ROLLBACK<br/>record the reason on the job]
    T3 --> C3[COMMIT]
    C2 --> OK[on the new commit]
    C3 --> OLD[still on the old commit,<br/>still answering questions]
```

T1 commits alone so both rows survive whatever happens next. T2 is all-or-nothing, because a
half-indexed repository looks present and answers from a fraction of the code — and the delete
belongs inside it, so a question asked mid-run is still answered from the old files.

### The HTTP API

```
GET  /health                            {"status": "ok"}
GET  /v1/repositories                   the gallery - every indexed repository
GET  /v1/repositories/{owner}/{repo}    one repository, in whatever state it is in
```

The gallery costs **two queries, not one per card**: the repository rows from
`repositories`, the language mix from `files`, matched on the id afterwards and then
dropped. `owner` and `repo` are matched case-insensitively against the
`owner_norm`/`repo_norm` unique index, so `/RepoLens` and `/repolens` are the same
repository.

| | |
|---|---|
| **200** | including an empty gallery. The collection exists and happens to hold nothing, so a 404 would be a lie — the URL names something real |
| **404** | no repository by that owner and name |
| **503** | Postgres unreachable. Every route fails the same way, so it is one handler on the application rather than one per route |
| **500** | anything unhandled. The body is `internal error` and nothing more — an exception can name columns and hosts; the traceback goes to the log instead |

A repository row carries two independent facts, which is why the response keeps them
apart: `commit_sha` says whether it can be **asked about**, and `job` says how its
**last indexing run went**. A repository can hold a good `commit_sha` and a failed
last run at once, still answering from the older commit.

**`POST /v1/repositories/{owner}/{repo}/questions` is next** — the first endpoint
that is not a database read.

---

## Design decisions

### The embedding model

`gemini-embedding-001` returns one vector per input from a single request, which is what
chunk-level retrieval needs — every chunk gets its own point in the space.

### `task_type` has no neutral default

```python
DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"     # a thing to be found later
QUERY_TASK    = "CODE_RETRIEVAL_QUERY"   # natural language searching for code
```

Omitting it applies a default that behaves like a query — so code chunks would be embedded as if
they were questions, and the asymmetry retrieval depends on would be lost.

### 768 dimensions, not 1536 or 3072

pgvector's HNSW index caps at 2,000 dimensions. A larger vector would mean no index later, which
matters the moment the corpus outgrows a sequential scan.

### Why the model is told when to refuse, rather than using a distance threshold

The obvious design is "if the nearest chunk is further than X, refuse." It was tested and does
not work:

```
WorkWave  · answerable questions     0.25 – 0.29
RepoLens  · unanswerable questions   0.28+
```

The bands overlap **across repositories**, so no single threshold separates them. Refusal is an
instruction in the prompt instead, and the eval measures whether it fires.

---

## Evaluation

`eval/` measures whether retrieval returns the right file, over 21 questions in five groups —
straightforward lookups, deliberately rambling questions, exact identifiers, conceptual "why"
questions, and questions the repository genuinely cannot answer.

Ground truth is at **file level**, not line level, so the eval survives a future change to how
chunks are cut.

```bash
python -m eval.run <repo_id>        # retrieval — no generation calls
```

### Baseline — RepoLens, 49 files, 238 chunks · 2026-09-19

| group | n | @1 | @2 | @3 | @5 | @8 |
|---|---|---|---|---|---|---|
| lookup | 6 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 |
| rambling | 4 | 0.50 | 0.75 | 0.75 | **1.00** | 1.00 |
| identifier | 4 | 0.50 | **1.00** | 1.00 | 1.00 | 1.00 |
| conceptual | 4 | 0.50 | 0.75 | **1.00** | 1.00 | 1.00 |
| **all** | **18** | **0.67** | **0.89** | **0.94** | **1.00** | **1.00** |

**Refusal.** Three questions about things the repository does not contain. Two produced the exact
refusal sentence and cited nothing at all — the system declines rather than inventing.

The third is the interesting one. It asked about a concept with a close neighbour in the codebase,
and the model answered about the neighbour: every claim true, every citation valid, but not the
question that was asked. That is exactly the line between what arithmetic can verify and what needs
judgement — and locating that line is what an eval set is for.

### What the eval decided

**recall@5 is 1.00 across every group** — the correct file is always retrieved, whatever shape the
question takes.

Rank 1 is where the groups separate: `lookup` reaches 1.00 immediately, `rambling` 0.50. A long
conversational question dilutes the embedding — one signal word competing with twenty others, the
rest pulling the vector toward prose rather than code.

Every rambling question is still answered correctly by rank 5, and all eight retrieved chunks
reach the model regardless. **That is why query rewriting is deferred rather than built** — it
would reorder a result set that already contains the answer.

---

## Deliberately not built

Each of these has a design and a trigger condition. They are choices, not gaps.

| Not built | Why | Trigger to revisit |
|---|---|---|
| **Hybrid search** (BM25 + RRF) | recall@8 is already **1.00** — the correct file is always retrieved. Hybrid reorders a set that is already complete, and all 8 chunks go to the model anyway | recall@8 drops below 1.00 |
| **Reranking** | same reason. Improves ordering inside a complete set | `k` is reduced to save tokens or latency |
| **Query rewriting** | would fix the rambling case, but costs an extra model call on every question to buy ordering we do not need | recall@8 drops on rambling questions |
| **Rate limiter** | one worker plus retry is sufficient. The quota is per project, so parallel workers cannot help | more than one indexing process |
| **Celery / Redis** | nothing runs long enough to need a queue yet | indexing moves behind an HTTP request |
| **LangChain** | every part here is one file we can read. A framework would hide the parts that are the point | — |
| **A dedicated vector database** | a few hundred chunk rows. Postgres already holds the relational data, and one database beats two | the corpus outgrows a sequential scan |

The fourth column is the point. *"We did not build it"* is a weaker statement than *"we measured
it, and here is the number that would change our mind."*

---

## Layout

```
src/                  everything Python imports
  services/           complete workflows — the CLI entry points
    index.py          walk → chunk → embed → store
    answer.py         question → chunks → prompt → model → cited answer

  pipeline/           single-purpose components
    clone.py          a GitHub URL becomes a folder, and is deleted afterwards
    walk.py           generator over source files, prunes before descending
    chunker.py        pure function — text in, line windows out
    embedder.py       Gemini embedding client, batching and normalisation
    retriever.py      a question becomes the k nearest chunks
    prompter.py       the two strings the model is sent, and the prompt hash
    llm.py            Gemini chat client
    citations.py      the model's [1] becomes a path, a line range and a URL
    retry.py          429 vs 5xx vs 4xx, three different responses

  db/                 everything that touches Postgres
    schema.sql        six tables, with the reasoning in comments
    store.py          every write on the indexing path
    ask_store.py      the ask path — the `<=>` query, the cache, its writes
    repositories.py   reads on repositories — the gallery, and one by name
    files.py          reads on files — lines per language
    jobs.py           reads on indexing_jobs — the latest run

  api/                the HTTP layer, and nothing else
    main.py           the application, and the global 503 and 500 handlers
    dependencies.py   the pool, lending one connection per request
    routers/
      repositories.py the /v1/repositories endpoints

prompts/
  _system.md          role, tone, rules, injection boundary, worked examples
  ask.md              what differs for the Ask lens — 128 tokens against 859

eval/
  questions.json      21 questions, five groups, file-level ground truth
  run.py              captures what retrieval returned, for scoring afterwards
  refusal.py          does it admit when it does not know
```

Dependencies point one way: **api → services → pipeline → db**. A component never knows a
workflow exists, which is why `chunker.py` can be tested with a string literal and swapped
for tree-sitter without touching anything else.

`prompts/` sits outside `src/` because nothing imports it — it is content, read at runtime by
path, so a prompt change shows in a diff as a change to text rather than to code. It is split for
the same reason `services/` and `pipeline/` are: the rules are identical across lenses and only
the task differs. The Ask lens file is 128 tokens against the shared file's 859, so a second lens
duplicates almost nothing.

---

## Status

| | |
|---|---|
| ✅ M0 | Postgres 16 + pgvector in Docker |
| ✅ M1 | Walker — 69,052 files scanned, 153 kept (WorkWave) |
| ✅ M1.5 | Clone — a GitHub URL becomes a folder, deleted once indexed |
| ✅ M2 | Chunker — 355 chunks, 60-line windows (WorkWave) |
| ✅ M3 | Embedder + retry — survives quota exhaustion |
| ✅ M4 | Storage — six tables, three transactions, one code path for index and re-index |
| ✅ M5 | Retrieval — cosine search, cited chunks |
| ✅ M6 | Answers — cited, and refuses when the chunks do not cover the question |
| 🚧 M7 | HTTP API — the two read endpoints are live, the ask endpoint is next |
| ⬜ M8 | Web interface |
| ⬜ M9 | Deployment |

---

<div align="center">
<sub>Built to be explainable. Every decision above has a measurement behind it.</sub>
</div>
