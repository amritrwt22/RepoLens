# batching_test.py — does any model/shape give us N embeddings in ONE request?
#
# The 429 from index_experiment.py proved gemini-embedding-2 with Content
# objects sends one HTTP request PER INPUT: a single call with 100 texts
# consumed 100 requests of a 100-per-minute quota.
#
# This tries the alternatives. The signal is TIME: if 20 texts take about
# as long as 1 text, it was one request. If ~20x longer, it looped.
#
# Uses 20 texts per test, so the whole script costs ~40 requests worst case.
#
# Run:  python batching_test.py

import time

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = genai.Client()

N = 20
DIM = 768

texts = []
for i in range(N):
    texts.append(f"function handler{i}(req, res) {{ res.json({{ id: {i} }}); }}")


def timed_call(label, model, contents, dimension=DIM):
    """Make one embed_content call, report vectors returned and time taken."""
    print(f"--- {label}")
    print(f"    model: {model}")
    try:
        t0 = time.time()
        result = client.models.embed_content(
            model=model,
            contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=dimension),
        )
        seconds = time.time() - t0

        count = len(result.embeddings)
        length = len(result.embeddings[0].values)
        print(f"    vectors returned: {count}")
        print(f"    dimensions:       {length}")
        print(f"    time:             {seconds:.2f}s")
        return seconds, count

    except Exception as e:
        # Print the message rather than a traceback — a 429 here is data,
        # not a crash.
        print(f"    FAILED: {type(e).__name__}")
        print(f"    {str(e)[:300]}")
        return None, None


# Baseline: one text, one model. Everything else is compared to this.
print()
base_seconds, _ = timed_call("BASELINE — 1 text", "gemini-embedding-001", texts[:1])
print()

# Test A: gemini-embedding-001 with a plain list of strings.
# Reportedly returns individual embeddings for each string in a list.
a_seconds, a_count = timed_call(
    f"TEST A — {N} raw strings", "gemini-embedding-001", texts
)
print()

# Test B: gemini-embedding-001 with Content objects, for comparison.
contents = []
for t in texts:
    contents.append(types.Content(parts=[types.Part(text=t)]))

b_seconds, b_count = timed_call(
    f"TEST B — {N} Content objects", "gemini-embedding-001", contents
)
print()

# Test C: gemini-embedding-2 with plain strings.
# Docs say this returns ONE aggregated embedding. Confirming.
c_seconds, c_count = timed_call(
    f"TEST C — {N} raw strings", "gemini-embedding-2", texts
)
print()


# ---------------------------------------------------------------- verdict
print("=" * 60)
print("VERDICT")
print()

if base_seconds is None:
    print("  baseline failed — probably still rate limited. Wait a minute.")
else:
    print(f"  baseline (1 text): {base_seconds:.2f}s")
    print()

    for label, seconds, count in [
        (f"A  001 + {N} strings ", a_seconds, a_count),
        (f"B  001 + {N} Contents", b_seconds, b_count),
        (f"C  002 + {N} strings ", c_seconds, c_count),
    ]:
        if seconds is None:
            print(f"  {label}: failed")
            continue

        ratio = seconds / base_seconds
        if count == N and ratio < 5:
            note = "ONE REQUEST — this is what we want"
        elif count == N:
            note = f"{count} vectors but {ratio:.0f}x slower — looped"
        elif count == 1:
            note = "aggregated into a single vector — unusable"
        else:
            note = "unexpected"

        print(f"  {label}: {count} vectors, {ratio:.1f}x baseline -> {note}")




# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python batching_test.py

# --- BASELINE — 1 text
#     model: gemini-embedding-001
#     vectors returned: 1
#     dimensions:       768
#     time:             0.63s

# --- TEST A — 20 raw strings
#     model: gemini-embedding-001
#     vectors returned: 20
#     dimensions:       768
#     time:             1.60s

# --- TEST B — 20 Content objects
#     model: gemini-embedding-001
#     vectors returned: 20
#     dimensions:       768
#     time:             1.80s

# --- TEST C — 20 raw strings
#     model: gemini-embedding-2
#     vectors returned: 1
#     dimensions:       768
#     time:             3.29s

# ============================================================
# VERDICT

#   baseline (1 text): 0.63s

#   A  001 + 20 strings : 20 vectors, 2.6x baseline -> ONE REQUEST — this is what we want
#   B  001 + 20 Contents: 20 vectors, 2.9x baseline -> ONE REQUEST — this is what we want
#   C  002 + 20 strings : 1 vectors, 5.3x baseline -> aggregated into a single vector — unusable
# (venv) (base) amrit@Amrittts-Macbook-Air repolens % 