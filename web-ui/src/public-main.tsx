import React from "react";
import ReactDOM from "react-dom/client";

import { LandingPage } from "./components/LandingPage";
import "./styles/globals.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LandingPage onLogin={() => {}} />
  </React.StrictMode>,
);
