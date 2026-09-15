from flask import Flask

app = Flask(__name__)
prefix = "/dynamic"


@app.route(prefix + "/items")
def dynamic_items():
    return "dynamic"
