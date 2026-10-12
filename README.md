<div align="center">

# RepoLens

**Ask a codebase a question. Get an answer cited to exact file paths and line numbers.**

[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Postgres](https://img.shields.io/badge/postgres-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Gemini](https://img.shields.io/badge/gemini-embedding--001-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Status](https://img.shields.io/badge/status-M6%20of%20M9-orange)](#status)

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
    G -->|writes citation numbers| V[validate]
    V --> R[Cited answer]
    DB -.->|path + lines| R
```

**The model only ever writes a number.** The file path and line range on every citation are read
straight out of the database, so a citation cannot point at a file that does not exist.

---

## What it looks like

```console
$ python -m src.services.answer 26 "how does retry decide how long to wait?"

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

[1] pipeline/retry.py:1-60
[2] pipeline/retry.py:101-147
```

Ask it something the repository does not contain and it says so, rather than inventing an answer:

```console
$ python -m src.services.answer 26 "how does billing work in this project?"

I don't have enough information in the available documents to answer this question.
```

---

## The one design decision everything rests on

**The model writes a number. Python writes the path.**

```
model produces   →   "Retry waits for the quota boundary [1]."
                                                        ^^^
we look up       →   chunks[0]["path"]        →  "pipeline/retry.py"
                     chunks[0]["start_line"]  →  22
                     chunks[0]["end_line"]    →  61
reader sees      →   [1]  pipeline/retry.py:22-61
```

The file path never passes through the language model. It comes from the same database row the
chunk came from.

This matters because a path is **generated text**, and generated text drifts. A model trained on
millions of public repositories has a strong sense of what a path *usually* looks like, so
`Server/middlewares/AuthMiddleware.js` quietly becomes `server/middleware/auth.js` — close,
plausible, wrong, and invisible to the reader.

A number has no such gravity. And because the numbers are a gap-free `1..k`, validation is
arithmetic: anything outside the range is dropped before it is ever displayed.

| Failure | Caught by |
|---|---|
| `[9]` cited when only 8 chunks were sent | `src/services/answer.py` — arithmetic |
| An answer with no citation at all | `src/services/answer.py` — arithmetic |
| A path that does not exist | **impossible by construction** |
| `[1]` cited for a claim that `[4]` supports | the eval set — needs judgement |

---

## Quick start

**Requires** Docker, Python 3.11+, and a [Gemini API key](https://aistudio.google.com/apikey)
(free tier is enough).

```bash
git clone https://github.com/amritrwt22/RepoLens.git
cd RepoLens

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # then add your GEMINI_API_KEY

docker compose up -d         # Postgres 16 + pgvector on port 5433
psql postgresql://repolens:repolens@localhost:5433/repolens -f src/db/schema.sql
```

Index a repository, then ask it things:

```bash
python -m src.services.index https://github.com/amritrwt22/RepoLens
# files: 25 lines: 3642 chunks: 80

# run it again and nothing happens — the repository is already on that commit
python -m src.services.index https://github.com/amritrwt22/RepoLens
# already indexed at df48637, nothing to do

# find the id it was given
psql postgresql://repolens:repolens@localhost:5433/repolens \
  -c "SELECT id, owner, repo, commit_sha, chunk_count FROM repositories ORDER BY id;"

python -m src.services.answer <repo_id> "how does authentication work?"
```

Retrieval alone, without spending a generation call:

```bash
python -m src.services.retrieve <repo_id> "how does authentication work?"
```

Everything runs with `-m` from the repository root — imports are absolute, so
`python src/pipeline/walk.py` will not work.

---

## How it works

```
              ┌─────────────────── INDEXING ───────────────────┐
   URL   ──►  clone  ──►  walk  ──►  chunk  ──►  embed  ──►  Postgres
              a temp    25 files   80 chunks   768-dim      + pgvector
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
| Search | `src/db/chunks.py` | one SQL query, cosine distance, `LIMIT 8` |
| Answer | `src/services/answer.py` | assembles the prompt, validates the citations |

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
| `questions` | `question · answer · sources · commit_sha · embedding` | every answer, pinned to the commit it was answered against |
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
python -m eval.refusal <repo_id>    # does it admit when it does not know
```

### Baseline — 238 chunks, 49 files

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
| **LangChain** | four moving parts, each understood. A framework would hide the parts that are the point | — |
| **A dedicated vector database** | 355 rows. Postgres already holds the relational data, and one database beats two | the corpus outgrows a sequential scan |

The fourth column is the point. *"We did not build it"* is a weaker statement than *"we measured
it, and here is the number that would change our mind."*

---

## Layout

```
src/                  everything Python imports
  services/           complete workflows — the CLI entry points
    index.py          walk → chunk → embed → store
    retrieve.py       question → embed → search → cited chunks
    answer.py         chunks → prompt → model → cited answer

  pipeline/           single-purpose components
    clone.py          a GitHub URL becomes a folder, and is deleted afterwards
    walk.py           generator over source files, prunes before descending
    chunker.py        pure function — text in, line windows out
    embedder.py       Gemini embedding client, batching and normalisation
    llm.py            Gemini chat client
    retry.py          429 vs 5xx vs 4xx, three different responses

  db/                 everything that touches Postgres
    schema.sql        six tables, with the reasoning in comments
    store.py          every write in the project
    chunks.py         reads on code_chunks — the similarity query

  main.py             the FastAPI application
  dependencies.py     the connection pool, as a dependency

prompts/
  _system.md          role, tone, rules, injection boundary, worked examples
  ask.md              what differs for the Ask lens — 128 tokens against 859

eval/
  questions.json      21 questions, five groups, file-level ground truth
  run.py              captures what retrieval returned, for scoring afterwards
  refusal.py          does it admit when it does not know
```

Dependencies point one way: **services → pipeline → db**. A component never knows a workflow
exists, which is why `chunker.py` can be tested with a string literal and swapped for tree-sitter
without touching anything else.

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
| ✅ M1 | Walker — 69,052 files scanned, 153 kept |
| ✅ M1.5 | Clone — a GitHub URL becomes a folder, deleted once indexed |
| ✅ M2 | Chunker — 355 chunks, 60-line windows |
| ✅ M3 | Embedder + retry — survives quota exhaustion |
| ✅ M4 | Storage — six tables, three transactions, one code path for index and re-index |
| ✅ M5 | Retrieval — cosine search, cited chunks |
| ✅ M6 | Answers — cited, and refuses when the chunks do not cover the question |
| ⬜ M7 | HTTP API |
| ⬜ M8 | Web interface |
| ⬜ M9 | Deployment |

---

## Where this is going

Everything above runs today, from a command line. The web application it becomes is already
designed — the shape below is decided, not speculative.

### A lens is not a prompt preset

```
lens  =  retrieval strategy  +  prompt  +  output format
```

The retrieval half is what makes it a lens. **Setup Lens finds `README`, `Dockerfile` and
`package.json` by filename and never runs a similarity search at all.** Architecture Lens samples
breadth-first across top-level directories rather than taking the nearest eight chunks. Same
pipeline underneath, genuinely different behaviour.

Lenses answer the questions a newcomer has **before they know enough to ask one.** That is the
whole thesis: a search box is useless to someone who does not yet know the vocabulary.

| Lens | Answers | Retrieval | Output |
|---|---|---|---|
| **Ask** ✅ | a follow-up, once you have the vocabulary | top-`k` by `<=>` | cited prose |
| **Setup** | how do I run it? | README, Dockerfile, manifests — by name | steps to run |
| **Architecture** | how is this built? | breadth sample across top-level dirs | Mermaid diagram + prose |
| **Onboarding** | where do I start? | entry points, routes, config | ordered reading list |

Those four are v1. Flow, API, Data, Security, History and Interview follow the same shape — a
retrieval strategy and an output format — which is the point of defining a lens this way rather
than as a prompt.

### Two surfaces, no overlap

| | Holds | Indexed by | Login |
|---|---|---|---|
| **Gallery** | well-known public repositories — React, FastAPI, Redis | us, by hand | ❌ browse and ask freely |
| **My repos** | a user's own repositories, public or private | that user | ✅ GitHub OAuth |

**Login means persistence and privacy, never access.** Everything in the gallery is open to
everyone, with no account. A visitor clicks React and gets a cited answer immediately — that is
the full demo, and it needs no auth at all.

Only we add to the gallery. Listing other people's repositories means owning moderation, spam and
takedowns, which is a cost surface with no early payoff.

### Staging

| | Ships | Login |
|---|---|---|
| **v1** | gallery, three lenses, Ask underneath | ❌ |
| **v2** | GitHub OAuth, index your own repos, **Interview Lens** | ✅ |
| **v3** | named spaces, several repositories per space | ✅ |
| **v4** | ask across every repository in a space | ✅ |

Cross-repository search is already paid for: `code_chunks.repository_id = %s` becomes
`= ANY(%s)`.

### The architecture it grows into

```
browser
   │
   ▼
FastAPI ──────────────────┬─────────────────────────┐
   │                      │                         │
   │ GET /repositories    │ POST /repositories      │ POST /ask
   │ (instant — reads     │ (returns a job id       │ (retrieve → prompt
   │  precomputed output) │  immediately)           │  → stream back)
   ▼                      ▼                         ▼
Postgres            Redis queue              Gemini
+ pgvector               │
  · repositories         ▼
  · indexing_jobs    worker process
  · files                │  clone → walk → chunk → embed → store
  · code_chunks          │  then run every precomputed lens once
  · lens_outputs  ◄──────┘
```

Three pieces the web application adds, each introduced by a measured reason rather than a schedule:

| | Why it becomes necessary |
|---|---|
| **Background jobs** (Redis + a worker) | indexing a large repository takes minutes. No HTTP request survives that, so `POST /repositories` has to return a job id and finish the work elsewhere |
| **`lens_outputs` table** | Architecture and Setup are generated **once at index time**, not per visit. It is what makes the gallery instant, and it removes the latency objection entirely — nobody minds that generation took ten minutes if it happened last Tuesday |
| **Streaming** (SSE) | an answer takes about three seconds. Total time is the same either way; three seconds of blank screen feels broken, and text appearing at 200 ms feels instant |

### What indexing gains next

`commit_sha` already earns its place three times over: re-indexing the same commit is a no-op,
citations pin to a snapshot so they never rot when a file changes, and the gallery can show
*"indexed at `df48637`."*

AST-aware chunking with tree-sitter is the next upgrade, respecting function and class boundaries
rather than fixed 60-line windows. The timing matters more than the change: it has to land
**before the gallery is seeded**, because re-chunking means re-embedding — five free minutes today,
hours of paid API once fifty repositories are indexed.

---

<div align="center">
<sub>Built to be explainable. Every decision above has a measurement behind it.</sub>
</div>
