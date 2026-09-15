import React, { useState, useEffect } from "react";
import { Route } from "react-router-dom";

export function App() {
  const [count, setCount] = useState(0);
  useEffect(() => setCount(count + 1), [count]);
  return <Route path="/home" element={<main />} />;
}
