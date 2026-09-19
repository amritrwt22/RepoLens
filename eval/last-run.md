# Retrieval eval - repo 26, k=8

Run 2026-09-19 11:21

## lookup

### walk-skip

**Q:** where does the walker skip directories?

**Expected:** `pipeline/walk.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2146 | `pipeline/walk.py:51-110` |
| 2 | 0.2150 | `pipeline/walk.py:1-60` |
| 3 | 0.2298 | `pipeline/walk.py:151-210` |
| 4 | 0.2418 | `docs/02-walker_generator_yield/generators-and-yield.md:151-210` |
| 5 | 0.2517 | `scripts/dump.py:1-59` |
| 6 | 0.2650 | `docs/02-walker_generator_yield/generators-and-yield.md:101-160` |
| 7 | 0.2700 | `docs/02-walker_generator_yield/generators-and-yield.md:201-260` |
| 8 | 0.2760 | `docs/02-walker_generator_yield/generators-and-yield.md:1-60` |

### walk-maxsize

**Q:** what is the largest file the walker will index?

**Expected:** `pipeline/walk.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2358 | `pipeline/walk.py:1-60` |
| 2 | 0.2380 | `pipeline/walk.py:151-210` |
| 3 | 0.2462 | `docs/09-limits_and_risks/limits-and-gaps.md:1-60` |
| 4 | 0.2523 | `index.py:201-260` |
| 5 | 0.2534 | `docs/02-walker_generator_yield/generators-and-yield.md:151-210` |
| 6 | 0.2569 | `docs/00-rag_pipeline/rag-pipeline.md:151-210` |
| 7 | 0.2573 | `docs/04-scaling/v1-architecture.md:251-310` |
| 8 | 0.2637 | `docs/04-scaling/v1-architecture.md:301-337` |

### chunk-size

**Q:** how many lines is a chunk and how much do they overlap?

**Expected:** `pipeline/chunker.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2104 | `pipeline/chunker.py:1-60` |
| 2 | 0.2604 | `index.py:251-271` |
| 3 | 0.2697 | `pipeline/chunker.py:51-105` |
| 4 | 0.2708 | `pipeline/walk.py:201-211` |
| 5 | 0.2797 | `index.py:201-260` |
| 6 | 0.2815 | `docs/03-embedder/deferred-and-open-questions.md:151-168` |
| 7 | 0.2820 | `docs/09-limits_and_risks/limits-and-gaps.md:1-60` |
| 8 | 0.2838 | `docs/08-index_orchestrator/index-design.md:201-260` |

### prepare-connection

**Q:** what does prepare_connection do?

**Expected:** `db/store.py`, `docs/07-storage/store-functions.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2593 | `docs/07-storage/store-functions.md:51-110` |
| 2 | 0.2994 | `docs/07-storage/store-functions.md:101-160` |
| 3 | 0.3019 | `db/store.py:1-60` |
| 4 | 0.3155 | `db/store.py:101-160` |
| 5 | 0.3199 | `db/store.py:151-196` |
| 6 | 0.3213 | `docs/07-storage/store-functions.md:1-60` |
| 7 | 0.3222 | `pipeline/embedder.py:1-60` |
| 8 | 0.3244 | `pipeline/walk.py:201-211` |

### search-query

**Q:** what SQL runs to find the nearest chunks?

**Expected:** `db/search.py`, `db/schema.sql`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2294 | `db/schema.sql:101-138` |
| 2 | 0.2316 | `db/search.py:1-60` |
| 3 | 0.2460 | `docs/01-schema_db_similarity_search/schema-design.md:101-160` |
| 4 | 0.2503 | `docs/01-schema_db_similarity_search/schema-design.md:151-210` |
| 5 | 0.2513 | `db/schema.sql:1-60` |
| 6 | 0.2547 | `docs/11-retrieval/retrieval-code.md:51-110` |
| 7 | 0.2650 | `db/schema.sql:51-110` |
| 8 | 0.2677 | `docs/07-storage/store-responsibilities.md:51-110` |

### fail-path

**Q:** what happens if indexing fails halfway through?

**Expected:** `index.py`, `docs/07-storage/transactions-and-failure.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.1851 | `docs/07-storage/transactions-and-failure.md:1-60` |
| 2 | 0.1855 | `docs/07-storage/transactions-and-failure.md:151-188` |
| 3 | 0.2153 | `index.py:201-260` |
| 4 | 0.2209 | `docs/07-storage/transactions-and-failure.md:51-110` |
| 5 | 0.2242 | `docs/08-index_orchestrator/index-design.md:301-360` |
| 6 | 0.2250 | `docs/08-index_orchestrator/index-design.md:251-310` |
| 7 | 0.2254 | `docs/08-index_orchestrator/index-design.md:51-110` |
| 8 | 0.2266 | `docs/08-index_orchestrator/index-design.md:351-371` |

## rambling

### jitter-rambling

**Q:** can u explain if we have used jitter and why and where and how in detail, idk what jitter is so explain first what jitter is

**Expected:** `pipeline/retry.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2896 | `docs/13-answering/temperature-and-sampling.md:1-60` |
| 2 | 0.2995 | `docs/13-answering/temperature-and-sampling.md:51-110` |
| 3 | 0.3005 | `prompts/_system.md:1-60` |
| 4 | 0.3041 | `docs/11-retrieval/retrieval-code.md:101-124` |
| 5 | 0.3054 | `pipeline/retry.py:1-60` |
| 6 | 0.3064 | `prompts/ask.md:1-16` |
| 7 | 0.3088 | `docs/04-scaling/v1-architecture.md:1-60` |
| 8 | 0.3096 | `docs/04-scaling/v1-architecture.md:201-260` |

### batching-rambling

**Q:** i dont really get the batching thing, like what decides when a batch gets sent off and why do we even need batches in the first place

**Expected:** `index.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2066 | `docs/03-embedder/embedder-class.md:151-210` |
| 2 | 0.2183 | `index.py:201-260` |
| 3 | 0.2203 | `docs/03-embedder/embedder-class.md:301-360` |
| 4 | 0.2246 | `docs/08-index_orchestrator/index-design.md:201-260` |
| 5 | 0.2268 | `docs/08-index_orchestrator/index-design.md:151-210` |
| 6 | 0.2281 | `docs/03-embedder/embedder-class.md:101-160` |
| 7 | 0.2354 | `index.py:251-271` |
| 8 | 0.2407 | `docs/03-embedder/embedder-class.md:51-110` |

### pipeline-rambling

**Q:** im new to this repo, can someone walk me through what actually happens from the moment a repo is uploaded until its searchable

**Expected:** `index.py`, `docs/00-rag_pipeline/rag-pipeline.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.1643 | `docs/00-rag_pipeline/rag-pipeline.md:51-110` |
| 2 | 0.1958 | `docs/04-scaling/v1-architecture.md:1-60` |
| 3 | 0.2048 | `index.py:201-260` |
| 4 | 0.2074 | `docs/08-index_orchestrator/index-design.md:301-360` |
| 5 | 0.2106 | `docs/00-rag_pipeline/rag-pipeline.md:101-160` |
| 6 | 0.2107 | `docs/08-index_orchestrator/index-design.md:1-60` |
| 7 | 0.2107 | `index.py:1-60` |
| 8 | 0.2114 | `docs/08-index_orchestrator/index-design.md:51-110` |

### answer-rambling

**Q:** so once we have the chunks what happens next, how does that turn into something a person can read with the file links and everything

**Expected:** `answer.py`, `docs/13-answering/answering-code.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2470 | `answer.py:51-110` |
| 2 | 0.2545 | `docs/08-index_orchestrator/index-design.md:351-371` |
| 3 | 0.2623 | `prompts/ask.md:1-16` |
| 4 | 0.2641 | `index.py:101-160` |
| 5 | 0.2642 | `index.py:1-60` |
| 6 | 0.2649 | `docs/07-storage/store-responsibilities.md:51-110` |
| 7 | 0.2716 | `index.py:201-260` |
| 8 | 0.2719 | `docs/11-retrieval/retrieval-code.md:1-60` |

## identifier

### max-batch-chars

**Q:** what is MAX_BATCH_CHARS set to and why

**Expected:** `index.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.1846 | `index.py:251-271` |
| 2 | 0.1912 | `docs/08-index_orchestrator/index-design.md:201-260` |
| 3 | 0.2067 | `docs/03-embedder/embedder-class.md:151-210` |
| 4 | 0.2173 | `docs/03-embedder/embedder-class.md:101-160` |
| 5 | 0.2182 | `docs/08-index_orchestrator/index-design.md:151-210` |
| 6 | 0.2222 | `index.py:201-260` |
| 7 | 0.2231 | `docs/03-embedder/deferred-and-open-questions.md:151-168` |
| 8 | 0.2253 | `docs/03-embedder/embedder-class.md:301-360` |

### task-type

**Q:** what is CODE_RETRIEVAL_QUERY used for

**Expected:** `pipeline/embedder.py`, `retrieve.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2363 | `docs/11-retrieval/retrieval-code.md:1-60` |
| 2 | 0.2416 | `retrieve.py:1-60` |
| 3 | 0.2505 | `docs/11-retrieval/retrieval-code.md:101-124` |
| 4 | 0.2507 | `docs/11-retrieval/retrieval-code.md:51-110` |
| 5 | 0.2527 | `docs/01-schema_db_similarity_search/schema-design.md:151-210` |
| 6 | 0.2553 | `docs/07-storage/store-functions.md:101-160` |
| 7 | 0.2613 | `docs/01-schema_db_similarity_search/schema-design.md:101-160` |
| 8 | 0.2697 | `answer.py:201-226` |

### register-vector

**Q:** what does register_vector do

**Expected:** `db/store.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2594 | `docs/07-storage/store-functions.md:51-110` |
| 2 | 0.2652 | `db/store.py:1-60` |
| 3 | 0.2828 | `pipeline/embedder.py:151-191` |
| 4 | 0.2879 | `docs/07-storage/store-functions.md:101-160` |
| 5 | 0.2961 | `pipeline/embedder.py:1-60` |
| 6 | 0.2969 | `docs/07-storage/store-responsibilities.md:51-110` |
| 7 | 0.2971 | `pipeline/embedder.py:51-110` |
| 8 | 0.2985 | `index.py:151-210` |

### skip-dirs

**Q:** what is in SKIP_DIRS

**Expected:** `pipeline/walk.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2752 | `pipeline/walk.py:1-60` |
| 2 | 0.2847 | `pipeline/walk.py:51-110` |
| 3 | 0.2949 | `pipeline/walk.py:151-210` |
| 4 | 0.2995 | `scripts/dump.py:1-59` |
| 5 | 0.3187 | `docs/07-storage/store-functions.md:101-160` |
| 6 | 0.3233 | `docs/02-walker_generator_yield/generators-and-yield.md:151-210` |
| 7 | 0.3267 | `docs/README.md:101-137` |
| 8 | 0.3282 | `index.py:1-60` |

## conceptual

### why-cosine

**Q:** why did we choose cosine distance instead of euclidean?

**Expected:** `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md`, `db/schema.sql`

| # | distance | chunk |
|---|---|---|
| 1 | 0.1874 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:101-160` |
| 2 | 0.1960 | `scripts/similarity_check.py:51-110` |
| 3 | 0.1964 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:351-410` |
| 4 | 0.1982 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:251-310` |
| 5 | 0.1987 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:301-360` |
| 6 | 0.2095 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:201-260` |
| 7 | 0.2113 | `docs/01-schema_db_similarity_search/cosine-distance-and-trigonometry.md:401-434` |
| 8 | 0.2117 | `scripts/similarity_check.py:101-160` |

### why-denormalise

**Q:** why is repository_id stored on code_chunks when it could be reached through files?

**Expected:** `db/schema.sql`, `docs/01-schema_db_similarity_search/schema-design.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2053 | `docs/07-storage/store-responsibilities.md:151-176` |
| 2 | 0.2128 | `docs/01-schema_db_similarity_search/schema-design.md:51-110` |
| 3 | 0.2206 | `db/schema.sql:51-110` |
| 4 | 0.2210 | `docs/07-storage/store-functions.md:101-160` |
| 5 | 0.2216 | `db/schema.sql:101-138` |
| 6 | 0.2285 | `docs/01-schema_db_similarity_search/schema-design.md:1-60` |
| 7 | 0.2319 | `docs/01-schema_db_similarity_search/schema-design.md:151-210` |
| 8 | 0.2319 | `docs/07-storage/store-functions.md:201-224` |

### vector-dims

**Q:** how many dimensions do the embeddings have and why that number?

**Expected:** `db/schema.sql`, `CLAUDE.md`, `pipeline/embedder.py`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2120 | `pipeline/embedder.py:1-60` |
| 2 | 0.2229 | `pipeline/embedder.py:51-110` |
| 3 | 0.2258 | `docs/03-embedder/embedder-design.md:101-160` |
| 4 | 0.2270 | `docs/03-embedder/embedder-design.md:51-110` |
| 5 | 0.2284 | `pipeline/embedder.py:151-191` |
| 6 | 0.2331 | `docs/03-embedder/embedder-design.md:1-60` |
| 7 | 0.2345 | `docs/03-embedder/embedder-design.md:201-242` |
| 8 | 0.2347 | `docs/03-embedder/embedder-class.md:1-60` |

### asymmetric-embedding

**Q:** why are questions and code embedded differently?

**Expected:** `pipeline/embedder.py`, `docs/03-embedder/embedder-class.md`

| # | distance | chunk |
|---|---|---|
| 1 | 0.2289 | `scripts/similarity_check.py:101-160` |
| 2 | 0.2322 | `docs/03-embedder/embedder-design.md:101-160` |
| 3 | 0.2371 | `pipeline/embedder.py:151-191` |
| 4 | 0.2373 | `scripts/similarity_check.py:151-175` |
| 5 | 0.2429 | `pipeline/embedder.py:51-110` |
| 6 | 0.2469 | `docs/12-product/product.md:301-318` |
| 7 | 0.2475 | `docs/03-embedder/embedder-design.md:201-242` |
| 8 | 0.2516 | `docs/03-embedder/embedder-class.md:51-110` |

## unanswerable
