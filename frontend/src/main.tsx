import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

async function start() {
  const response = await fetch("/runtime-config.json", { cache: "no-store" });
  if (!response.ok) throw new Error("Could not load application configuration");
  window.passitConfig = await response.json();
  const { default: App } = await import("./App");
  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

void start().catch(() => {
  document.getElementById("root")!.textContent =
    "Could not load application configuration. Please refresh and try again.";
});
