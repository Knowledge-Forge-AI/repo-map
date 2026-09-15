import React from "react";
import { helper } from "./util.mjs";
import "./styles.css";
export { helper } from "./util.mjs";

export function main() {
  return fetch("https://example.invalid/api?token=placeholder");
}

class Runner {
  start() {
    return helper();
  }
}

const App = () => <main />;
const COUNT = 3;
