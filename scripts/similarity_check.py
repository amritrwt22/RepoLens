# similarity_check.py — M3 acceptance test.
#
# Everything so far proved the plumbing works: vectors come back, right
# count, right length. This proves the thing the product actually depends
# on — that similar code lands closer together than unrelated code.
#
# Run from the repo root:  python -m scripts.similarity_check
# (-m, not a direct path, so `from embedder import ...` resolves)

import math

from embedder import Embedder


# Five short snippets. Two are about authentication, the rest are not.
# Each is a (label, code) pair so the output is readable.
SNIPPETS = [
    ("auth-jwt",
     "const verifyToken = (req, res, next) => { "
     "const token = req.headers.authorization; jwt.verify(token, SECRET); next(); }"),

    ("auth-password",
     "async function checkPassword(plain, hashed) { "
     "return await bcrypt.compare(plain, hashed); }"),

    ("email",
     "const sendResetEmail = (to, link) => { "
     "transporter.sendMail({ to, subject: 'Reset', html: link }); }"),

    ("invoice",
     "function calculateInvoiceTotal(items) { "
     "return items.reduce((sum, i) => sum + i.price * i.qty, 0); }"),

    ("db-connect",
     "mongoose.connect(process.env.MONGO_URI).then(() => console.log('db up'));"),
]


def cosine_distance(a, b):
    """Cosine distance between two vectors. 0 = identical direction,
    1 = unrelated, 2 = opposite. Lower means more similar.

    Written by hand rather than imported so we can check later that
    pgvector's <=> operator produces the same numbers.
    """
    # Dot product: multiply matching positions, add them all up.
    dot = 0.0
    for i in range(len(a)):
        dot = dot + a[i] * b[i]

    # Magnitude of each vector: Pythagoras in 768 dimensions.
    sum_a = 0.0
    sum_b = 0.0
    for i in range(len(a)):
        sum_a = sum_a + a[i] * a[i]
        sum_b = sum_b + b[i] * b[i]

    length_a = math.sqrt(sum_a)
    length_b = math.sqrt(sum_b)

    similarity = dot / (length_a * length_b)
    return 1 - similarity


embedder = Embedder()

# Split the pairs into two parallel lists. Position i in `labels`
# describes position i in `texts` — and later in `vectors` too.
labels = []
texts = []
for label, code in SNIPPETS:
    labels.append(label)
    texts.append(code)

vectors = embedder.embed_documents(texts)

print(f"embedded {len(vectors)} snippets, {len(vectors[0])} dimensions each")
print()


# ---------------------------------------------------------------- test 1
# Distance from every snippet to every other snippet.

print("TEST 1 — do similar chunks cluster?")
print()

# Header row.
header = " " * 15
for label in labels:
    header = header + f"{label:>15}"
print(header)

for i in range(len(vectors)):
    row = f"{labels[i]:<15}"
    for j in range(len(vectors)):
        d = cosine_distance(vectors[i], vectors[j])
        row = row + f"{d:>15.3f}"
    print(row)

print()

auth_to_auth = cosine_distance(vectors[0], vectors[1])
auth_to_invoice = cosine_distance(vectors[0], vectors[3])

print(f"auth-jwt <-> auth-password : {auth_to_auth:.3f}")
print(f"auth-jwt <-> invoice       : {auth_to_invoice:.3f}")

if auth_to_auth < auth_to_invoice:
    print("PASS — the two auth snippets are closer to each other")
else:
    print("FAIL — something is wrong with the embeddings")

print()


# ---------------------------------------------------------------- test 2
# A question, embedded with the QUERY prefix, ranked against all five.
# This is the whole product in miniature: question in, ranked code out.

question = "how does authentication work?"
query_vector = embedder.embed_query(question)

print(f'TEST 2 — ranking for: "{question}"')
print()

# Build (distance, label) pairs so we can sort by distance.
results = []
for i in range(len(vectors)):
    d = cosine_distance(query_vector, vectors[i])
    results.append((d, labels[i]))

# sort() on a list of tuples orders by the first element — the distance.
results.sort()

rank = 1
for distance, label in results:
    print(f"  {rank}. {label:<15} {distance:.3f}")
    rank = rank + 1

print()

top_two = [results[0][1], results[1][1]]
if "auth-jwt" in top_two and "auth-password" in top_two:
    print("PASS — both auth snippets ranked top 2")
else:
    print(f"FAIL — top 2 were {top_two}")




# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python similarity_check.py
# embedded 5 snippets, 768 dimensions each

# TEST 1 — do similar chunks cluster?

#                       auth-jwt  auth-password          email        invoice     db-connect
# auth-jwt                 0.000          0.298          0.288          0.369          0.320
# auth-password            0.298          0.000          0.291          0.351          0.322
# email                    0.288          0.291          0.000          0.345          0.312
# invoice                  0.369          0.351          0.345          0.000          0.374
# db-connect               0.320          0.322          0.312          0.374          0.000

# auth-jwt <-> auth-password : 0.298
# auth-jwt <-> invoice       : 0.369
# PASS — the two auth snippets are closer to each other

# TEST 2 — ranking for: "how does authentication work?"

#   1. auth-password   0.398
#   2. auth-jwt        0.405
#   3. db-connect      0.424
#   4. email           0.437
#   5. invoice         0.509

# PASS — both auth snippets ranked top 2