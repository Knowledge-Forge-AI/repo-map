from flask import Flask

app = Flask(__name__)


def ping():
    return "pong"


app.add_url_rule("/ping", "ping", ping, methods=["GET"])
