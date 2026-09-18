# Refusal check - repo 26

Run 2026-09-18 12:20

A question this repository cannot answer should produce the refusal
sentence and cite nothing.

### billing - PASS

**Q:** how does billing work in this project?

- refused: True
- chunks cited: 0 (expected 0)

**Answer given:**

```
I don't have enough information in the available documents to answer this question.
```

### recommendation-engine - **FAIL**

**Q:** how does the recommendation engine rank results?

- refused: False
- chunks cited: 1 (expected 0)

**Answer given:**

```
The recommendation engine uses vector similarity to find and rank code chunks that match a user's question [2]. 

### How it works

- **Question to vector:** An embedder converts the user's text question into a list of 768 floating-point numbers [2].
- **Angle over length:** The database compares this query vector against stored code chunk vectors using cosine distance via the `<=>` operator [2, 8]. This measures the angle between them while completely ignoring how long the files are, meaning a short file and a long file about the same topic match equally well [7, 8].
- **Sorting:** The database orders the results from lowest distance to highest, where lower numbers mean a closer match (0 is identical, 1 is unrelated, and 2 is opposite) [7, 8].
- **Top matches:** The query grabs the best matches using `LIMIT 8` [2].

> **Tip** - the database search itself is kept pure SQL and never imports the embedder, which keeps it testable without needing an API key [2]
```

### mobile-app - PASS

**Q:** how does the mobile app talk to the server?

- refused: True
- chunks cited: 0 (expected 0)

**Answer given:**

```
I don't have enough information in the available documents to answer this question.
```

---

**2/3 refused correctly.**