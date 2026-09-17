import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import "./index.css";

try {
  const storedMode = window.localStorage.getItem("ui_next_color_mode");
  const prefersDark = storedMode ? storedMode === "dark" : true;
  document.documentElement.classList.toggle("dark", prefersDark);
} catch {
  document.documentElement.classList.add("dark");
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
