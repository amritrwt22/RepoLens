# db/store.py : the only module that writes to Postgres.
#
# Takes what the pipeline produced in memory and puts it in the three tables. 
# It never walks, chunks or embeds, and it never creates aconnection — it is handed one.
# That way the same code works from a script today and from a pooled web request at later stage.

def store_repository(conn, name):
    """Create the row for one repository and return its generated id.

    status is 'indexing' because work begins immediately — there is no queue yet. 'ready' or 'failed' is written at the end of the run.
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
        return cur.fetchone()[0] # cur.fetchone() returns the first row from query result, [0] gets value at first column. 
    # so cur.fetchone() gives the row (id,), [0] gives the id of repo we just inserted, return the id. 
    # we insert the repo, generate repo_id, return it so it can be used to put in files and chunks tables
    
    
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    import psycopg
    
    load_dotenv()
    
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        repo_id = store_repository(conn, "WorkWave-main")
        print("inserted repository id:", repo_id)