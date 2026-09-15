from fastapi import FastAPI

app = FastAPI()


def auth_dependency(access_token="fake-fastapi-token-secret"):
    return access_token
