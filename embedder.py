# embedder.py — M3: turn text into vectors using the Gemini embedding API.
#
# A class, not a function, because it holds state that outlives one call:
# the API client, the model name, the dimension.
# See docs/embedder-class.md and docs/cpp-to-python-oop.html

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Reads the .env file so that genai.Client() can find GEMINI_API_KEY.
load_dotenv()


# gemini-embedding-2 has no task_type parameter, so the task instruction
# is written into the text itself. Documents and queries get different
# ones. These are module-level constants (C++: a `const` at file scope).
DOCUMENT_PREFIX = "code snippet: "
QUERY_PREFIX = "code retrieval query: "


class Embedder:

    # __init__ is the constructor. `self` is the object itself —
    # C++'s `this`, except you must write it out every time.
    def __init__(self, client=None, model="gemini-embedding-2", dimension=768):

        # Python has no overloading, so defaults do that job.
        # client=None means "make one yourself", but a test can pass a
        # fake client in instead.
        if client is None:
            client = genai.Client()

        # Members are created here by assignment. There is no
        # declaration anywhere else, and no initialiser list.
        self.client = client
        self.model = model
        self.dimension = dimension

    # A leading underscore means "internal — don't call from outside".
    # It is a convention, not enforced. C++: private.
    def _embed(self, texts):

        # Passing plain strings would return ONE combined embedding for the whole list. 
        # Wrapping each text in its own Content object is what makes the API give us one vector per text.
        contents = []
        for text in texts:
            part = types.Part(text=text)
            content = types.Content(parts=[part])
            contents.append(content)

        result = self.client.models.embed_content(
            model=self.model,
            contents=contents,
            config=types.EmbedContentConfig(
                output_dimensionality=self.dimension
            ),
        )

        # result.embeddings is a list of objects. The numbers we want
        # are on each object's .values attribute.
        vectors = []
        for embedding in result.embeddings:
            vectors.append(embedding.values)

        return vectors

    # Public method: embed code chunks for storage.
    # Returns one vector per text, in the same order as the input.
    def embed_documents(self, texts):

        prefixed = []
        for text in texts:
            prefixed.append(DOCUMENT_PREFIX + text)

        return self._embed(prefixed)

    # Public method: embed a user's question. Returns ONE vector.
    def embed_query(self, text):

        prefixed = QUERY_PREFIX + text

        # _embed always takes a list and returns a list, so we pass a
        # list of one and take element 0 back out.
        vectors = self._embed([prefixed])
        return vectors[0]


# Runs only when this file is executed directly.
# C++ equivalent: int main().
if __name__ == "__main__":

    embedder = Embedder()

    texts = [
        "const verifyToken = (req, res, next) => { jwt.verify(...) }",
        "const sendResetEmail = (to) => { transporter.sendMail(...) }",
        "function calculateInvoiceTotal(items) { return items.reduce(...) }",
    ]

    vectors = embedder.embed_documents(texts)

    print(f"sent {len(texts)} texts, got {len(vectors)} vectors")
    print(f"each vector length: {len(vectors[0])}")

    query_vector = embedder.embed_query("how does authentication work?")
    print(f"query vector length: {len(query_vector)}")

# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python embedder.py
# sent 3 texts, got 3 vectors
# each vector length: 768
# query vector length: 768





# =========================================================================
#  Embedder — structure
# =========================================================================
#
#  As a C++ header:
#
#      class Embedder {
#      private:
#          Client      client;      // API key + open connection
#          string model;       // "gemini-embedding-2"
#          int         dimension;   // 768
#          vector<vector<float>> _embed(vector<string> texts);

#      public:
#          Embedder(Client c = nullptr, string model = "...", int dim = 768);
#          vector<vector<float>> embed_documents(vector<string>);
#          vector<float>              embed_query(string);
#      };
#
#  METHODS
#    _embed(texts)            list of prefixed strings -> list of vectors,
#      [internal]             same order. The only method that calls the API.
#
#    embed_documents(texts)   list of chunk texts -> list of 768-float vectors.
#                             Used at indexing time. Adds DOCUMENT_PREFIX.
#
#    embed_query(text)        one question -> ONE 768-float vector.
#                             Used at question time. Adds QUERY_PREFIX.
#
#  Two methods, not one with a flag: forgetting the flag would embed a
#  question as a document, which throws no error and quietly ruins search.
#
#  NOT here: buffering, counting chunks, the database. That is index.py (M4).
#
#  TODO: retry/backoff, splitting long lists into several requests,
#        guarding chunks over the 8,192-token limit.
# =========================================================================
