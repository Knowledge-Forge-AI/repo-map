from fastapi import FastAPI

app = FastAPI()
prefix = "/dynamic"


@app.get(prefix + "/items")
def dynamic_items():
    return {}
