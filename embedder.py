# embedder.py — M3: turn text into vectors using the Gemini embedding API.
#
# A class rather than a function because it holds state that outlives one
# call: the API client, the model name, the dimension.
# Notes: docs/03-embedder/embedder-class.md

import math

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Reads .env so genai.Client() can find GEMINI_API_KEY.
load_dotenv()


# task_type tells the model what ROLE the text plays. There is no neutral
# option: omitting it applies the default, which behaves like a query — so
# code chunks would be embedded as if they were questions.
DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"     # a thing to be found later
QUERY_TASK = "CODE_RETRIEVAL_QUERY"      # natural language searching for code


class Embedder:

    # __init__ is the constructor. `self` is C++'s `this`, written out.
    def __init__(self, client=None, model="gemini-embedding-001", dimension=768):
        # Passing a client in is how a test swaps the real API for a fake.
        if client is None:
            client = genai.Client()

        # Members are created here by assignment. No declaration elsewhere.
        self.client = client
        self.model = model
        self.dimension = dimension

    # Leading underscore = internal. Convention, not enforced.
    def _embed(self, texts, task_type):
        result = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                output_dimensionality=self.dimension,
                task_type=task_type,
            ),
        )

        # One request, one vector per input, same order as `texts`.
        # gemini-embedding-001 does NOT normalise below 3072 dimensions
        # (|v| ~= 0.58 at 768), so we do it here — in the one place both
        # documents and queries pass through.
        vectors = []
        for embedding in result.embeddings:
            v = embedding.values

            total = 0.0
            for x in v:
                total = total + x * x
            length = math.sqrt(total)

            # Same direction, |v| becomes 1.
            unit = []
            for x in v:
                unit.append(x / length)

            vectors.append(unit)

        return vectors

    def embed_documents(self, texts):
        """Code chunks, for storage. List in, list of vectors out."""
        return self._embed(texts, DOCUMENT_TASK)

    def embed_query(self, text):
        """One question. Returns ONE vector, not a list of one."""
        vectors = self._embed([text], QUERY_TASK)
        return vectors[0]


if __name__ == "__main__":
    embedder = Embedder()

    texts = [
        "const verifyToken = (req, res, next) => { jwt.verify(token, SECRET); }",
        "function calculateInvoiceTotal(items) { return items.reduce(...); }",
    ]

    vectors = embedder.embed_documents(texts)
    print(f"sent {len(texts)} texts, got {len(vectors)} vectors")
    print(f"vector length: {len(vectors[0])}")

    query_vector = embedder.embed_query("how does authentication work?")
    print(f"query vector length: {len(query_vector)}")


# =========================================================================
#  Embedder — structure
# =========================================================================
#
#  As a C++ header:
#
#      class Embedder {
#      private:
#          Client      client;      // API key + open connection
#          std::string model;       // "gemini-embedding-001"
#          int         dimension;   // 768
#          std::vector<std::vector<float>> _embed(vector<string>, string);
#      public:
#          Embedder(Client c = nullptr, string model = "...", int dim = 768);
#          std::vector<std::vector<float>> embed_documents(vector<string>);
#          std::vector<float>              embed_query(string);
#      };
#
#  METHODS
#    _embed(texts, task_type)   prefixed strings -> vectors, same order.
#      [internal]               The only method that calls the API.
#
#    embed_documents(texts)     chunk texts -> list of 768-float vectors.
#                               Indexing time. task_type=RETRIEVAL_DOCUMENT.
#
#    embed_query(text)          one question -> ONE 768-float vector.
#                               Question time. task_type=CODE_RETRIEVAL_QUERY.
#
#  Two methods, not one with a flag: forgetting the flag would embed a
#  question as a document, which throws no error and quietly ruins search.
#
#  MEASURED FACTS (batching_test.py, index_experiment.py)
#    - gemini-embedding-001 returns N vectors from N inputs in ONE request.
#      355 chunks = 4 requests. gemini-embedding-2 sends one request PER
#      input (hit the 100/min free-tier quota) and collapses a plain list
#      into a single aggregated vector.
#    - The API does NOT normalise below 3072 dims (|v| ~= 0.58 at 768), so
#      _embed does it. Cosine was already unaffected; normalising makes
#      <#> (inner product) safe rather than silently length-biased.
#    - Free tier: 100 embed requests/minute. 429 carries a retryDelay field.
#
#  NOT here: buffering, counting chunks, the database. That is index.py (M4).
#
#  TODO: retry using the 429's retryDelay; split lists over batch_size;
#        guard the 8,192-token limit (silently truncated, never rejected).
# =========================================================================
