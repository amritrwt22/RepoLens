# Refusal check - repo 26

Run 2026-09-19 11:21

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
- chunks cited: 2 (expected 0)

**Answer given:**

```
The recommendation engine works by turning a search question into a list of numbers and comparing those numbers against every stored code chunk in the database using geometry [2, 8].

### How ranking works

- **Translation:** The system takes your plain text question and runs it through an embedder to produce a 768-element list of numbers, or a vector [2, 3].
- **Angle comparison:** It uses the pgvector cosine distance operator (`<=>`) to measure the angle between the question vector and the embedding of every code chunk in the repository [2, 8].
- **Sorting:** It orders the results from lowest distance to highest distance and limits the output to the top 8 matches (`ORDER BY ... LIMIT 8`) [2, 4, 8].

### Why it is built that way

- **Pure SQL search:** The database search code never imports the embedder and stays pure SQL so it remains testable without an API key [2].
- **Length independence:** Cosine distance measures angle and ignores vector length. This means a 200-line file and a 20-line file about the same topic match a query equally well—it cares what the text is about, not how much of it there is [7, 8].

> **Tip** - The core retrieval step comes down to a single SQL query line: `ORDER BY embedding <=> :question_vector LIMIT 8` [8]
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