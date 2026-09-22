# src/db/chunks.py : reads on the code_chunks table.
#
# Writes go through store.py, which owns every insert in the project. Reads are
# split per table, so anything asking a question of code_chunks lands here.
#
# Handed a connection and a query VECTOR, never a question — embedding belongs
# to the caller, which keeps this module pure SQL and testable with no API key.

def search_chunks(conn, repo_id, query_vector, k=8):
    """Find the k chunks in one repository closest to query_vector.

    IN
      conn          open psycopg connection, already prepare_connection'd
      repo_id       int - which repository to search inside
      query_vector  list of 768 floats, from embedder.embed_query()
      k             how many chunks to return

    OUT
      list of k dicts, nearest first:
        {"chunk_id": 64, "path": "Server/index.js",
         "start_line": 1, "end_line": 60,
         "content": "<the 60 lines>", "distance": 0.0689}

      Fewer than k dicts if the repository has fewer than k chunks.
    """
    
    # the conn owns the transaction (trnasaction begins with first cur.execute), ends with when with of conn is exited
    # this with of cur just closes the cursor object that is used for running statements on psql
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, f.path, c.start_line, c.end_line, c.content,
            c.embedding <=> %s::vector AS distance
            
            FROM code_chunks c
            JOIN files f ON c.file_id = f.id
            WHERE c.repository_id = %s
            ORDER BY distance
            LIMIT %s
            """,
            (query_vector, repo_id, k),
        )
        
        # fetchall() must run before the cursor closes. It returns a LIST OF
        # TUPLES, one per row, columns in SELECT order:
        #   (id, path, start_line, end_line, content, distance)
        rows = cur.fetchall()
        
        # Turn each tuple into a dict so callers use names, not row[i]
        result = []
        for row in rows:
            result.append({
                "chunk_id": row[0],
                "path": row[1],
                "start_line": row[2],
                "end_line": row[3],
                "content": row[4],
                "distance": row[5],
            })
        
        return result

