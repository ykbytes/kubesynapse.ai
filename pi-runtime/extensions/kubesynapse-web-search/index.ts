/**
 * kubesynapse Web Search Extension for pi
 *
 * Enables web search capabilities for kubesynapse agents using Brave Search API
 * or a configurable search endpoint. Agents can search the web and retrieve
 * page content for research tasks.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "typebox";

const BRAVE_API_KEY = process.env.BRAVE_API_KEY || "";
const SEARCH_API_URL = process.env.SEARCH_API_URL || "https://api.search.brave.com/res/v1/web/search";

interface SearchResult {
  title: string;
  url: string;
  description: string;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "KUBESYNAPSE_web_search",
    label: "Web Search",
    description: `Search the web for information using Brave Search API.
Use this when you need current information, documentation, or answers not in your training data.
Configured via BRAVE_API_KEY environment variable.`,
    promptSnippet: "Search the web for information via Brave Search API",
    promptGuidelines: [
      "Use KUBESYNAPSE_web_search when you need current or real-world information not available in your training data.",
      "Be specific with your query — include relevant keywords for better results.",
      "Review search results before using them as facts — verify important claims.",
    ],
    parameters: Type.Object({
      query: Type.String({
        description: "The search query. Be specific and include relevant keywords.",
      }),
      count: Type.Optional(
        Type.Number({
          description: "Number of results to return (1-10, default: 5)",
          minimum: 1,
          maximum: 10,
        })
      ),
    }),
    async execute(_toolCallId, params, signal) {
      const query = params.query;
      const count = params.count || 5;

      if (!BRAVE_API_KEY) {
        return {
          content: [
            {
              type: "text",
              text: "Web search is not available: BRAVE_API_KEY is not configured. Ask the platform admin to add a Brave Search API key to enable web search.",
            },
          ],
          details: { error: "no_api_key" },
        };
      }

      try {
        const url = `${SEARCH_API_URL}?q=${encodeURIComponent(query)}&count=${count}`;
        const response = await fetch(url, {
          headers: {
            Accept: "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
          },
          signal,
        });

        if (!response.ok) {
          return {
            content: [
              {
                type: "text",
                text: `Search failed: HTTP ${response.status} — ${response.statusText}`,
              },
            ],
            details: { error: `http_${response.status}` },
          };
        }

        const data = await response.json();
        const results: SearchResult[] = (data.web?.results || []).map(
          (r: Record<string, string>) => ({
            title: r.title || "",
            url: r.url || "",
            description: r.description || "",
          })
        );

        if (results.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `No results found for "${query}".`,
              },
            ],
            details: { results: [] },
          };
        }

        const formatted = results
          .map((r, i) => `${i + 1}. **${r.title}**\n   ${r.url}\n   ${r.description}`)
          .join("\n\n");

        return {
          content: [
            {
              type: "text",
              text: `## Web Search Results for "${query}"\n\n${formatted}`,
            },
          ],
          details: { results, query, count },
        };
      } catch (err: unknown) {
        const errorMsg = err instanceof Error ? err.message : String(err);
        return {
          content: [
            {
              type: "text",
              text: `Search error: ${errorMsg}`,
            },
          ],
          details: { error: errorMsg },
        };
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    if (BRAVE_API_KEY) {
      ctx.ui.notify("Web search enabled via Brave Search API", "info");
    } else {
      ctx.ui.notify("Web search disabled — set BRAVE_API_KEY to enable", "info");
    }
  });
};
