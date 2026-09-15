from flask import Flask

app = Flask(__name__)
app.config["SECRET_KEY"] = "fake-flask-web-secret"
app.config["DATABASE_URL"] = "postgres://user:fake-flask-db-secret@example.invalid/app"
