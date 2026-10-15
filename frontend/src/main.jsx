import React from "react";
import { createRoot } from "react-dom/client";
import App, { ApiErrorBoundary } from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ApiErrorBoundary onUnauthorized={() => sessionStorage.removeItem("token")}>
      <App />
    </ApiErrorBoundary>
  </React.StrictMode>,
);