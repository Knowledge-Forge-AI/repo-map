import express from "express";

const http = require("node:http");
const app = express();
const router = express.Router();

module.exports = createServer;
exports.health = health;

const secretEnv = process.env.SECRET_TOKEN;
const publicPort = import.meta.env.PUBLIC_PORT;

app.use("/api", router);
app.get("/health", authMiddleware, healthHandler);
router.post("/users", validateUser, createUser);
app.get(routeName, dynamicHandler);
app.use((err, req, res, next) => next(err));

function createServer() {
  return http.createServer(app);
}

function health(req, res) {
  res.json({ ok: true, publicPort });
}
