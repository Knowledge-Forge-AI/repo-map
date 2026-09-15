from fastapi import FastAPI

app = FastAPI()


@app.get("/items/{item_id}", tags=["items"], summary="fixture item summary")
async def read_item(item_id: str):
    return {"item_id": item_id}
