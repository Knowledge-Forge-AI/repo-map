from flask import Flask

app = Flask(__name__)


@app.get("/health")
def health():
    return "ok"


@app.route("/users/<user_id>", methods=["GET", "POST"])
def user_detail():
    return user_id
