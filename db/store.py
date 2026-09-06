# db/store.py : the only module that writes to Postgres.
#
# Takes what the pipeline produced in memory and puts it in the three tables. 
# It never walks, chunks or embeds, and it never creates a connection — it is handed one.
# That way the same code works from a script today and from a pooled web request at later stage.

from pgvector.psycopg import register_vector # teaches psycopg the vector type

def prepare_connection(conn):
    """Make one connection ready for storing vectors. Call once after connecting.
    
      Every type in Postgres has a numeric id, assigned when the extension is installed
      in database. So the vector might be type 16485 on my db and something else on other.
      So to identify the data type, our program needs to know the id of the datatype.
      
      register_vector asks the db server for the vector type's id on THIS connection
      and teaches psycopg to convert a python list to and from it. It applies to one 
      connection, not to program - a new connection needs it again.
      
    """
    register_vector(conn)



def store_repository(conn, name):
    """Create the row for one repository and return its generated id.

    status is 'indexing' because work begins immediately — there is no queue
    yet. 'ready' or 'failed' is written at the end of the run.

    Only name and status are inserted. file_count, chunk_count, total_lines,
    indexed_at and error are deferred and stay NULL until the run finishes.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repositories (name, status)
            VALUES (%s, 'indexing')
            RETURNING id
            """,
            (name,),
        )
        # RETURNING makes the INSERT produce a result set holding the row it
        # just wrote. fetchone() takes the next unread row from that result —
        # here the only one, (id,) — and [0] unwraps the single column.
        # The id is returned so files and chunks can point at this repository.
        return cur.fetchone()[0]
    
    
def store_file(conn, repo_id, file):
    """Insert one file row and return its generated id.

    Every column is filled — nothing is deferred, unlike repositories.

    `file` is one dict from pipeline.walk.find_source_files:
        {"path": "Server/index.js", "language": "JavaScript",
         "line_count": 125, "content": "<full text>"}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (repository_id, path, language, line_count, content)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (repo_id, file["path"], file["language"], file["line_count"], file["content"]),
        )
        # Same as above: (file_id,) out of the result, [0] to unwrap it.
        # Every chunk of this file needs this id.
        return cur.fetchone()[0]
    
    
    
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    import psycopg
    
    load_dotenv()
    
    # Hand-written, in the walker's shape. Testing store.py alone — if the
    # walker were involved, a failure here could be either module's fault.
    fake_file = {
        "path": "Server/index.js",
        "language": "JavaScript",
        "line_count": 125,
        "content": "const express = require('express');\n",
    }
    
    
    
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        repo_id = store_repository(conn, "WorkWave-main")
        print("inserted repository id:", repo_id)
        
        file_id = store_file(conn, repo_id, fake_file)
        print("file id:", file_id)