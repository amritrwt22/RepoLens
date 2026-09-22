from fastapi import FastAPI    # pull FastAI class out of fastapi package

app = FastAPI()     # create the application object, holds list of routes


@app.get("/health")     # Decorator line: register the function below as handler for Get/ health endpoint
def health():
    return {"status": "ok"}     # return a python dict, fastapi convert it into JSON and send with status 200 to client


    


