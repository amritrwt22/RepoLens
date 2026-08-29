# index_experiment.py — M3 experiment on real data.
#
# Runs walker -> chunker -> embedder over a whole repository and measures
# what the docs do not tell us. Deliberately NO retries and NO guards:
# this is a controlled experiment, and a failure here is information.
#
# See docs/03-embedder/deferred-and-open-questions.md
#
# Run:  python index_experiment.py ~/Desktop/projects/WorkWave-main

import sys
import time
import math
from pathlib import Path
import logging

from walk import find_source_files
from chunker import chunk_text
from embedder import Embedder

logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


BATCH_SIZE = 20

# The API caps each input at 8,192 tokens and SILENTLY truncates anything
# longer. Code is roughly 4 characters per token, so this is our warning
# line. Rough on purpose — a real token count costs an extra API call.
CHARS_PER_TOKEN = 4
TOKEN_LIMIT = 8192
CHAR_LIMIT = TOKEN_LIMIT * CHARS_PER_TOKEN


def cosine_distance(a, b):
    """0 = identical direction, 1 = unrelated, 2 = opposite."""
    dot = 0.0
    sum_a = 0.0
    sum_b = 0.0
    for i in range(len(a)):
        dot = dot + a[i] * b[i]
        sum_a = sum_a + a[i] * a[i]
        sum_b = sum_b + b[i] * b[i]
    return 1 - dot / (math.sqrt(sum_a) * math.sqrt(sum_b))


root = Path(sys.argv[1])
embedder = Embedder()


# ---------------------------------------------------------------------
# STEP 1 — collect every chunk in the repository.
#
# Held in memory only because this is a one-off experiment and we want
# to time the API separately from the walking. The real pipeline (M4)
# streams and never holds them all at once.
# ---------------------------------------------------------------------

print("walking and chunking...")
walk_start = time.time()

chunks = []          # each entry: {"path", "start_line", "end_line", "content"}
files_seen = 0

for f in find_source_files(root):
    files_seen = files_seen + 1
    for c in chunk_text(f["content"]):
        chunks.append({
            "path": f["path"],
            "start_line": c["start_line"],
            "end_line": c["end_line"],
            "content": c["content"],
        })

walk_seconds = time.time() - walk_start

print(f"  files:  {files_seen}")
print(f"  chunks: {len(chunks)}")
print(f"  time:   {walk_seconds:.2f}s")
print()


# ---------------------------------------------------------------------
# STEP 2 — how close are we to the silent-truncation limit?  (D1)
# ---------------------------------------------------------------------

print("chunk sizes (D1 — silent truncation risk)")

longest = 0
longest_path = ""
total_chars = 0
over_limit = 0

for c in chunks:
    n = len(c["content"])
    total_chars = total_chars + n
    if n > longest:
        longest = n
        longest_path = f"{c['path']}:{c['start_line']}-{c['end_line']}"
    if n > CHAR_LIMIT:
        over_limit = over_limit + 1

average = total_chars / len(chunks)

print(f"  average chunk: {average:.0f} chars  (~{average / CHARS_PER_TOKEN:.0f} tokens)")
print(f"  longest chunk: {longest} chars  (~{longest / CHARS_PER_TOKEN:.0f} tokens)")
print(f"                 {longest_path}")
print(f"  limit:         {CHAR_LIMIT} chars  (~{TOKEN_LIMIT} tokens)")
print(f"  headroom:      {100 * longest / CHAR_LIMIT:.1f}% of the limit used by the worst chunk")
print(f"  over limit:    {over_limit} chunks")
print()


# ---------------------------------------------------------------------
# STEP 3 — one request with 1 text, then one with 100.  (Q1)
#
# If a 100-input call takes about as long as a 1-input call, the SDK
# genuinely batches. If it takes ~100x longer, it is looping internally
# and our batch_size buys nothing.
# ---------------------------------------------------------------------

print("timing (Q1 — is a 100-input call one request or 100?)")

texts = []
for c in chunks:
    texts.append(c["content"])

t0 = time.time()
embedder.embed_documents(texts[:1])
one_seconds = time.time() - t0

t0 = time.time()
first_batch = embedder.embed_documents(texts[:BATCH_SIZE])
hundred_seconds = time.time() - t0

print(f"  1 text:    {one_seconds:.2f}s")
print(f"  100 texts: {hundred_seconds:.2f}s")
print(f"  ratio:     {hundred_seconds / one_seconds:.1f}x")

if hundred_seconds < one_seconds * 10:
    print("  -> looks like ONE request. Batching works.")
else:
    print("  -> looks like it LOOPS internally. Batching buys nothing.")

print(f"  got {len(first_batch)} vectors back from 100 inputs")
print()


# ---------------------------------------------------------------------
# STEP 4 — embed everything, in batches, timing each one.  (Q2, Q3)
# ---------------------------------------------------------------------

print(f"embedding all {len(chunks)} chunks in batches of {BATCH_SIZE}...")

vectors = []
run_start = time.time()
batch_number = 0
start = 0

while start < len(texts):
    batch = texts[start:start + BATCH_SIZE]
    batch_number = batch_number + 1

    t0 = time.time()
    batch_vectors = embedder.embed_documents(batch)
    seconds = time.time() - t0

    for v in batch_vectors:
        vectors.append(v)

    print(f"  batch {batch_number}: {len(batch)} texts -> "
          f"{len(batch_vectors)} vectors in {seconds:.2f}s")

    start = start + BATCH_SIZE

run_seconds = time.time() - run_start

print()
print(f"  total:     {run_seconds:.2f}s for {len(vectors)} vectors")
print(f"  requests:  {batch_number}")
print(f"  estimated cost: ${(total_chars / CHARS_PER_TOKEN) * 0.15 / 1_000_000:.4f}")
print()

# If these ever disagree, a vector is stored against the wrong chunk.
if len(vectors) != len(chunks):
    print(f"  MISMATCH: {len(chunks)} chunks but {len(vectors)} vectors")
else:
    print("  count matches — vector i corresponds to chunk i")
print()


# ---------------------------------------------------------------------
# STEP 5 — search it. This is M5 without the database.
# ---------------------------------------------------------------------

QUESTIONS = [
    "how does authentication work?",
    "how are chat messages sent and received?",
    "how is a booking created?",
]

for question in QUESTIONS:
    query_vector = embedder.embed_query(question)

    results = []
    for i in range(len(vectors)):
        d = cosine_distance(query_vector, vectors[i])
        results.append((d, i))

    results.sort()

    print(f'"{question}"')
    rank = 1
    for distance, i in results[:5]:
        c = chunks[i]
        print(f"  {rank}. {distance:.3f}  {c['path']}:{c['start_line']}-{c['end_line']}")
        rank = rank + 1
    print()
