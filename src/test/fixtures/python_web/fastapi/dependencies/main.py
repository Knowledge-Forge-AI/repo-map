from fastapi import Depends, FastAPI

app = FastAPI()


def current_user(api_key="fake-fastapi-default-secret"):
    return api_key


@app.get("/me")
def me(user=Depends(current_user)):
    return {"user": "fixture"}


app.include_router(api_router)
