/**
 * Public landing page entry point.
 *
 * This is a standalone build that renders only the marketing landing page
 * and documentation panel — no auth, no console, no agent management.
 * Deployed to https://kubesynapse.ai via FTP.
 */
import React from "react";
import ReactDOM from "react-dom/client";

import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import { LandingPage } from "./components/landing/LandingPage";
import "./styles/globals.css";

const noop = () => {};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LandingPage onLogin={noop} showLogin={false} />
  </React.StrictMode>,
);
