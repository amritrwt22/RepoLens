# Retrieval eval

Does search find the right file? Twenty-one questions, ground truth at file level.

```
python -m eval.run <repo_id>     ->  writes eval/last-run.md
```

`run.py` only captures - it writes every chunk that came back for every question. Scoring is done
afterwards against that file, so a metric can be recomputed without spending quota again.

Questions with an empty `files` list are unanswerable on purpose. They are skipped here; they exist
for the answer-level eval later, which will check that the model refuses.

---

## Baseline - repo 26, 2026-09-18

238 chunks, 49 files. First run.

| group | n | @1 | @2 | @3 | @4 | @5 | @6 | @7 | @8 |
|---|---|---|---|---|---|---|---|---|---|
| lookup | 6 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| rambling | 4 | 0.50 | 0.75 | 0.75 | 0.75 | **1.00** | 1.00 | 1.00 | 1.00 |
| identifier | 4 | 0.50 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| conceptual | 4 | 0.50 | 0.75 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| **ALL** | **18** | **0.67** | **0.89** | **0.94** | 0.94 | **1.00** | 1.00 | 1.00 | 1.00 |

Rank of the first correct file, per question:

```
lookup        [1, 1, 1, 1, 1, 1]
identifier    [1, 1, 2, 2]
conceptual    [1, 1, 2, 3]
rambling      [1, 1, 2, 5]      <- the only rank above 3 in the whole set
```

---

## Observations

### recall@8 is 1.00, so retrieval is not the bottleneck

The correct file is in the top 5 for every question, and in the top 3 for 94%. All eight chunks go
into the prompt, so whether the right one sits at rank 1 or rank 5 makes little difference to the
model - it reads all of them either way.

### Ranks 4, 6, 7 and 8 never matter

Not one question is *first* found at those positions. On this set, k=5 would lose nothing and k=3
would lose exactly one question. Retrieving 8 currently spends tokens on three chunks that never
contribute.

### Rambling questions are the weakest, as predicted by hand

`jitter-rambling` is the canonical hard case - rank 5, only 1 of 8 chunks from an expected file,
and the tightest distance spread in the set. Long conversational questions dilute the embedding:
the signal word is one of twenty-five, and the rest pulls the vector toward explanatory prose.

Found by hand before the eval existed; the eval reproduced it.

### Spread correlates with rank - a candidate confidence signal

Gap between the nearest and furthest of the eight chunks, averaged by the rank achieved:

| rank achieved | mean spread |
|---|---|
| 1 | 0.0350 |
| 2 | 0.0333 |
| 3 | 0.0227 |
| 5 | 0.0200 |

Monotonic. A tight spread means nothing stood out, so the ordering was close to arbitrary.

This matters because an **absolute** distance threshold was already proven unworkable - WorkWave's
answerable band (0.25-0.29) overlapped RepoLens's unanswerable band (0.28+). Spread is **relative
within one query**, so it sidesteps that objection entirely.

Treat it as a hypothesis: n=18, and it was found after the fact rather than predicted.

### Identifier questions are all found by rank 2

This weakens the case for hybrid search. The prediction was that BM25 would rescue identifier
questions that dense retrieval misses - but none are missed, they are merely second. Hybrid would
move rank 2 to rank 1, which is a much smaller win than "finds what was previously lost".

---

## What the eval itself gets wrong

- **`lookup` scores 1.00 at every cutoff.** It cannot detect improvement, only breakage. It is a
  smoke test, not a measurement.
- **The questions and the ground truth were written by someone who had read the repository**, so
  some questions probably echo the phrasing of the content they target. A set written by a genuine
  newcomer would score worse, and be more honest.
- **18 answerable questions is small.** One question moving changes recall@1 by 0.06.

---

## Refusal check - repo 26, 2026-09-18

`python -m eval.refusal <repo_id>` runs the three unanswerable questions through the full path and
checks two things, both deterministic: the exact refusal sentence appears, and nothing is cited.

**2 of 3 passed.** `billing` and `mobile-app` both refused cleanly and cited nothing.

### The one failure, and why it was left alone

```
Q: how does the recommendation engine rank results?
A: "The recommendation engine uses vector similarity to find and rank code chunks..." [2]
```

There is no recommendation engine in this repository. The model saw "engine that ranks results",
found the vector search, and renamed it.

**Nothing was fabricated.** Cosine distance, the `<=>` operator, `LIMIT 8`, 768-float vectors -
every claim is true and every citation valid. It answered a different question than the one asked.

This is the gap between the two kinds of check:

| Check | Result |
|---|---|
| Are the citation numbers real? | passed |
| Is each claim supported by what it cites? | would pass - they are |
| **Is this an answer to the question asked?** | **failed** |

Structural checks cannot catch it. The answer is well-formed, grounded and cited, and about the
wrong thing.

**Deliberately not fixed.** The rule that would catch it is one line - *"if the question names
something that does not appear in the chunks, say so before answering anything adjacent"* - but:

- the failure is benign: nothing invented, everything cited
- it needs an unusual input: a missing concept that has a close cousin present. The two questions
  without a cousin both passed
- with n=1 there is no way to tell whether the rule helps or just adds tokens

Revisit if real users hit it, or if a larger unanswerable set shows it is common rather than a
one-off.

---

## Ideas raised, and how ranking is actually improved

Two ideas came out of reading the table, plus the mechanism behind reranking. Recorded because
they are the options if retrieval ever does need work.

### Turn every question into a lookup question

Straight out of the results: **`lookup` scores 1.00 at rank 1 while rambling scores 0.50.** So put
an LLM in front of the vector search, and have it rewrite whatever the user typed into the terse,
specific form that already works.

```
"can u explain if we have used jitter and why and where and how in detail,
 idk what jitter is so explain first what jitter is"
        |
        v   LLM rewrite
"jitter implementation retry backoff"
        |
        v   embed and search
rank 2 instead of rank 5
```

This is **query rewriting**, and it is a standard production technique rather than a workaround.
Measured: the bare phrase `jitter` ranks the right chunk at **2**, the terse phrasing at **7**, the
rambling one at **17** on the older index. Phrasing is worth fifteen places.

**What it would actually buy is efficiency, not accuracy.** Everything already lands in the top 5.
Getting everything to rank 1-2 would let `k` drop from 8 to 3 - roughly 2,000 prompt tokens instead
of 5,000, cheaper and faster. But it costs an extra LLM call of about 500 ms, which eats the speed
gain. Close to a wash at this size.

**Send the original question to the answering model, not the rewrite.** The rewrite is a search
key. The user's own words carry intent the rewrite deliberately throws away - "idk what jitter is
so explain first" is noise for searching and signal for answering.

### Route the question: what is for the database, what is for the model

A second and arguably better use of the same LLM call: decide **whether to search at all**.

"hi", "what can you do?", "thanks" - none of these should trigger a vector search. Nor should
"write me a regex". An upfront classifier decides: is this a question about the repository, or
something the model answers directly?

This is **query routing**. It is how the empty-state problem gets handled gracefully instead of
returning eight irrelevant chunks and a refusal. Worth building when there are real users typing
real things, not before.

### Reranking, and the model distinction behind it

The question worth asking first: **does rank even matter when all 8 chunks go into the prompt?**

Mostly it does not - the model reads all of them. Rank matters only when you want to send *fewer*
chunks, when the context is long enough for lost-in-the-middle to bite, or because the citation
list shown to the reader is ordered.

If it did matter, reranking is how it gets fixed, and it rests on two kinds of model:

| | How it works | Cost |
|---|---|---|
| **Bi-encoder** - what we use | query and chunk are embedded **separately**, then compared by distance | chunks are embedded once at index time. Very fast |
| **Cross-encoder** - a reranker | query and chunk go in **together**, one model, out comes a relevance score | cannot be precomputed. Far too slow to run over every chunk |

The bi-encoder's weakness is that the two texts never meet: the model never sees this query beside
this chunk, so it cannot notice that this particular chunk answers this particular question. The
cross-encoder can, because it attends across both at once.

Hence the standard shape:

```
cheap and wide   ->  bi-encoder retrieves 50 from 238
expensive, narrow ->  cross-encoder rescores those 50
                  ->  keep the best 8
```

Using an LLM as the reranker is a real variant of the same idea, just slower and dearer than a
purpose-built cross-encoder.

---

## Decision: retrieval work is deferred

**Not building hybrid search, reranking or query rewriting.**

Every one of them improves ordering inside a result set that is already complete. recall@8 is
1.00; there is nothing left to find. A day of work would move rank 2 to rank 1, and the model -
which reads all eight chunks - would not notice.

Hybrid search was already on ON-PLATE as the next retrieval task, and it is what most RAG guides
recommend at this stage. The measurement shows it would improve a number that is already at its
maximum.

### Triggers to revisit

| Build | When |
|---|---|
| **Reranking** | recall@1 matters because k has been reduced to save tokens or latency |
| **Hybrid search** | recall@8 drops below 1.00 on identifier questions |
| **Query rewriting** | recall@8 drops below 1.00 on rambling questions |
| **Any of them** | a repository 10x this size, or a harder question set, breaks recall@8 |

The common trigger is **recall@8 falling below 1.00.** While it holds, retrieval is finished.

### What is unmeasured, and now carries the real risk

Nothing here tests the answer. Open questions with no number attached:

- is the answer factually correct?
- is each citation attached to the claim it actually supports?
- does the model refuse when it should? The three unanswerable questions are sitting unused

That is the answer-level eval, and it becomes worth building when there is something to tune -
which will be after the next lens and the API, not before.
