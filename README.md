<div align="center">

# RepoLens

**Ask a codebase a question. Get an answer cited to exact file paths and line numbers.**

[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Postgres](https://img.shields.io/badge/postgres-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Gemini](https://img.shields.io/badge/gemini-embedding--001-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev)
[![Status](https://img.shields.io/badge/status-M6%20of%20M9-orange)](#status)

</div>

---

> A developer joins a team and is handed a repository with 153 files. Nobody has time to walk
> them through it. Search finds string matches, not explanations. The README is nine months old.
>
> RepoLens answers questions about that repository in plain language, and **every claim points at
> the lines it came from**, so the answer can be checked rather than trusted.

---

```mermaid
graph TD
    A[Repository] -->|153 files| B[walk]
    B -->|60-line windows| C[chunk]
    C -->|768-dim vectors| D[embed]
    D --> DB[(Postgres + pgvector)]
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
$ python -m answer 26 "how does retry decide how long to wait?"

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
$ python -m answer 26 "how does billing work in this project?"

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
| `[9]` cited when only 8 chunks were sent | `answer.py` — arithmetic |
| An answer with no citation at all | `answer.py` — arithmetic |
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
psql postgresql://repolens:repolens@localhost:5433/repolens -f db/schema.sql
```

Index a repository, then ask it things:

```bash
python -m index ~/path/to/some-repo
# files: 153 lines: 14808 chunks: 355

# find the id it was given
psql postgresql://repolens:repolens@localhost:5433/repolens \
  -c "SELECT id, name, status, chunk_count FROM repositories ORDER BY id;"

python -m answer <repo_id> "how does authentication work?"
```

Retrieval alone, without spending a generation call:

```bash
python -m retrieve <repo_id> "how does authentication work?"
```

Everything runs with `-m` from the repository root — imports are absolute, so
`python pipeline/walk.py` will not work.

---

## How it works

```
                    ┌──────────── INDEXING ─────────────┐
   repository  ──►  walk  ──►  chunk  ──►  embed  ──►  Postgres
                    153 files   355 chunks  768-dim     + pgvector
                                            vectors

                    ┌──────────── ANSWERING ────────────┐
   question    ──►  embed  ──►  <=> search  ──►  prompt  ──►  cited answer
                    768-dim     top 8 chunks    + rules
```

| Stage | File | What it does |
|---|---|---|
| Walk | `pipeline/walk.py` | a generator yielding one file at a time — never loads the repository into memory |
| Chunk | `pipeline/chunker.py` | 60-line windows with 10 lines of overlap |
| Embed | `pipeline/embedder.py` | batched, normalised, retries on quota exhaustion |
| Store | `db/store.py` | three tables, two transactions |
| Search | `db/search.py` | one SQL query, cosine distance, `LIMIT 8` |
| Answer | `answer.py` | assembles the prompt, validates the citations |

### Three tables

```sql
repositories  id · name · status · file_count · chunk_count · total_lines
files         id · repository_id · path · language · line_count · content
code_chunks   id · repository_id · file_id · content · start_line · end_line
              · embedding vector(768)
```

`code_chunks.repository_id` is denormalised on purpose: every similarity search filters by
repository, and without it each search would need a join to `files` first.

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

**Refusal — 2 of 3.** Three questions about things the repository does not contain. Two produced
the exact refusal sentence and cited nothing at all.

The third asked about a concept that has a close neighbour in the codebase, and the model answered
about the neighbour instead — every claim true, every citation valid, but not the question that was
asked. That is precisely the line between what arithmetic can verify and what needs judgement, and
knowing where that line sits is what the eval is for.

### What the eval decided

`rambling` is the weakest group — **0.50** at rank 1, against `lookup`'s 1.00. A long
conversational question dilutes the embedding: the one signal word is competing with twenty-odd
others, and the rest pulls the vector toward prose rather than code.

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
index.py            walk → chunk → embed → store
retrieve.py         question → embed → search → cited chunks
answer.py           chunks → prompt → model → cited answer

pipeline/
  walk.py           generator over source files, prunes before descending
  chunker.py        pure function — text in, line windows out
  embedder.py       Gemini embedding client, batching and normalisation
  llm.py            Gemini chat client
  retry.py          429 vs 5xx vs 4xx, three different responses

db/
  schema.sql        three tables, with the reasoning in comments
  store.py          six write functions
  search.py         the one similarity query

prompts/
  _system.md        role, tone, rules, injection boundary, worked examples
  ask.md            what differs for the Ask lens — 128 tokens against 859

eval/
  questions.json    21 questions, five groups, file-level ground truth
  run.py            captures what retrieval returned, for scoring afterwards
  refusal.py        does it admit when it does not know
```

`prompts/` is split because the rules are identical across lenses and only the task differs. The
Ask lens file is 128 tokens against the shared file's 859 — a second lens duplicates almost
nothing.

---

## Status

| | |
|---|---|
| ✅ M0 | Postgres 16 + pgvector in Docker |
| ✅ M1 | Walker — 69,052 files scanned, 153 kept |
| ✅ M2 | Chunker — 355 chunks, 60-line windows |
| ✅ M3 | Embedder + retry — survives quota exhaustion |
| ✅ M4 | Storage — three tables, two transactions, 5.6 min end to end |
| ✅ M5 | Retrieval — cosine search, cited chunks |
| ✅ M6 | Answers — cited, and refuses when the chunks do not cover the question |
| ⬜ M7 | HTTP API |
| ⬜ M8 | Web interface |
| ⬜ M9 | Deployment |

---

## Where this is going

Everything above is a command line. The product it is being built into is a web application, and
the shape is already decided.

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
| **Setup** | how do I run it? | README, Dockerfile, manifests — by name | steps to run |
| **Architecture** | how is this built? | breadth sample across top-level dirs | Mermaid diagram + prose |
| **Onboarding** | where do I start? | entry points, routes, config | ordered reading list |
| **Ask** ✅ | a follow-up, once you have the vocabulary | top-`k` by `<=>` | cited prose |
| *Flow* | how does a request travel? | route → handler → database | sequence diagram |
| *API* | what is the public surface? | route and handler definitions | endpoint table |
| *Data* | what does it store? | models, schemas, migrations | ER diagram |
| *Security* | where is auth, validation, secrets? | top-`k` on security concepts | cited findings |
| *History* | who owns this? where is it messy? | `git log --numstat`, **no embeddings** | hotspots and owners |
| *Interview* | what will I be asked about this? | the **whole** repo, at index time | a Q&A set |

Only `Ask` exists today. The first four ship in v1; the italics are later.

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
  · files            worker process
  · code_chunks          │  clone → walk → chunk → embed → store
  · lens_outputs  ◄──────┘  then run every precomputed lens once
```

Three pieces that do not exist yet, each with a reason rather than a schedule:

| | Why it becomes necessary |
|---|---|
| **Background jobs** (Redis + a worker) | indexing takes ~5.6 minutes. No HTTP request survives that, so `POST /repositories` has to return a job id and finish the work elsewhere |
| **`lens_outputs` table** | Architecture and Setup are generated **once at index time**, not per visit. It is what makes the gallery instant, and it removes the latency objection entirely — nobody minds that generation took ten minutes if it happened last Tuesday |
| **Streaming** (SSE) | an answer takes about three seconds. Total time is the same either way; three seconds of blank screen feels broken, and text appearing at 200 ms feels instant |

### And the parts of indexing that are still manual

`commit_sha` is one column that solves three problems at once: re-indexing the same commit becomes
a no-op, citations pin to a snapshot so they never rot when a file changes, and the gallery can
show *"indexed at `50113da1`, 12 commits behind main."*

Chunking is currently fixed 60-line windows, which can cut a function in half. AST-aware chunking
using tree-sitter would respect real boundaries — and it has to happen **before the gallery is
seeded**, because re-chunking means re-embedding, which is five free minutes today and hours of
paid API once fifty repositories are indexed.

---

<div align="center">
<sub>Built to be explainable. Every decision above has a measurement behind it.</sub>
</div>
