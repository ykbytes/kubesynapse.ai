# KubeSynthAI Web UI — Redesign Prompt

## Current UI Overview

**Tech Stack:** React 18 + TypeScript, Vite 6, Tailwind CSS v4, Radix UI primitives, shadcn/ui component patterns, Lucide icons, Space Grotesk font, React Flow (DAG editor), Monaco Editor, Sonner toasts, cmdk command palette.

**Current Layout:** Classic dashboard shell with a sticky glass TopBar (h-14), collapsible left sidebar (w-64 → w-12) with view tabs and resource list, and a main content area. Mobile uses a bottom tab bar + hamburger sheet.

**Current Theme System:** 4 themes (Dark default, Light, Midnight, Forest) using OKLCH color space in Tailwind v4 `@theme` directive. Primary accent is teal/cyan (`oklch(0.65 0.13 175)`). 24 custom keyframe animations, glass effects, noise texture overlay.

**Major Views:** Landing Page → Auth → Dashboard (Agents, Workflows, Composer, Evals, Catalog, Policies, Intelligence, Settings, Admin, Teams, Health, Audit, Usage).

**Key Strengths:**
- Rich feature set: agent CRUD, chat workbench with SSE streaming, DAG composer, workflow management, evals, skills catalog, HITL approvals
- Solid component architecture: shadcn/ui primitives, CVA variants, consistent patterns
- Theme system with OKLCH colors, extensive animation library
- Mobile responsive with bottom nav

**Key Weaknesses / Redesign Opportunities:**

### 1. Visual Hierarchy & Information Density
- The AgentManagementPanel (1530 lines) and ChatWorkbench (1788 lines) are monolithic and visually dense
- Too many status chips, badges, and indicators competing for attention simultaneously
- Sidebar crams view grid (2x4 or 4x2), search, and resource list into one panel — feels crowded
- No clear visual hierarchy between primary actions, secondary actions, and metadata

### 2. Navigation & Information Architecture
- No URL-based routing — views are state-driven, making bookmarking, deep-linking, and browser history impossible
- 15+ top-level views but sidebar only shows 8 view tabs in a grid — many panels (Teams, Health, Audit, Usage) are orphaned or hard to find
- No breadcrumb system — users lose track of context when drilling into agents → sessions → messages → tool calls
- Inspector drawer (right-side sheet) competes with split-pane agent/chat layout — three-panel layouts feel cramped

### 3. Chat Workbench Experience
- 1788-line component trying to do everything: messages, streaming, tool calls, plans, memory, A2A, subagents, sessions, HITL, artifacts, file browser
- No clear separation between conversation view, tool execution log, and artifact viewer — all compete in the same viewport
- Thinking/reasoning sections and tool call expansions make message threads very tall and hard to scan
- Session management is hidden in a drawer instead of being a first-class sidebar element
- No conversation threading or message grouping by intent/phase

### 4. Workflow Composer
- React Flow canvas is functional but lacks visual polish — nodes look like generic boxes
- No mini-preview of workflow run status on the canvas
- Node palette, properties panel, and canvas compete for space
- Missing: execution heatmap overlay on nodes, dependency impact visualization, run comparison

### 5. Onboarding & Discoverability
- OnboardingTour exists but the UI has so many features that a single tour is insufficient
- No contextual help — tooltips are sparse, complex forms (agent creation, policy editor) have no inline guidance
- Empty states exist but don't guide users to the next action effectively
- Command palette is underutilized — should be the primary power-user interface

### 6. Mobile Experience
- Bottom tab bar only covers 5 tabs — most features are inaccessible on mobile
- Complex panels (agent management, composer, policy editor) are essentially unusable on small screens
- No mobile-optimized simplified views for on-the-go monitoring

### 7. Data Visualization & Observability
- No dashboards for aggregate metrics: agent utilization, workflow success rates, token costs over time
- Health dashboard exists but is a separate panel instead of integrated into the main view
- No trend charts, no sparklines on resource list items, no at-a-glance health indicators
- Intelligence dashboard and Usage dashboard are separate — should be unified into an Observability view

---

## Detailed Redesign Prompt

Use this prompt with AI image generators (Midjourney, DALL-E 3, v0 by Vercel, etc.) or as a design brief for a human designer.

---

### Master Prompt: Complete UI Redesign

```
Redesign the web UI for "KubeSynthAI" — a Kubernetes-native AI agent orchestration platform. The current UI is a feature-rich but visually dense dashboard built with React, Tailwind CSS, and shadcn/ui components. Create a modern, clean, and highly usable redesign that addresses the following:

**Design System:**
- Keep the dark theme as default (OKLCH-based: bg oklch(0.145 0.008 274), primary teal oklch(0.65 0.13 175))
- Introduce a proper design token system with semantic color names (surface-elevated-1, surface-elevated-2, text-primary, text-secondary, text-muted, border-subtle, border-default, accent-primary, accent-success, accent-warning, accent-danger)
- Typography: Keep Space Grotesk for headings, introduce Inter for body text. Establish a clear type scale: xs (11px), sm (13px), base (15px), lg (17px), xl (20px), 2xl (24px), 3xl (30px)
- Spacing: 4px base grid (4, 8, 12, 16, 24, 32, 48, 64, 96)
- Border radius: sm (6px), md (8px), lg (12px), xl (16px)
- Shadows: 3 elevation levels (subtle, medium, strong) with colored shadows matching the primary accent

**Layout — Three-Column Dashboard:**
```
+-----+------------------+-------------------+
| Nav | Primary Panel    | Context Panel     |
| 64px| (flex, min 600px)| (320px, collapsible)|
+-----+------------------+-------------------+
```
- **Left Nav (64px):** Icon-only rail with tooltips. Shows: logo, view icons (Agents, Workflows, Composer, Evals, Catalog, Policies, Observability, Settings, Admin), bottom: user avatar, help, notifications. Expandable to 240px on hover showing full labels.
- **Primary Panel:** Main content area. Always shows a page header with title, breadcrumbs, and primary action button. Content scrolls independently.
- **Context Panel (right, 320px):** Replaces the current Inspector sheet. Context-aware — shows details for whatever is selected in the primary panel. Always visible when a selection is active, slides in with a smooth transition. Collapsible to 0.

**Top Bar (48px):**
- Minimal: just brand logo (left), search bar (center, expands on focus), and notification bell + connection status (right).
- Remove namespace switcher, user role, theme picker from top bar — move to a user menu accessed via avatar in the left nav.
- Glass effect: `backdrop-blur-xl bg-background/60 border-b border-border/40`.

**View-Specific Redesign:**

**1. Agents List View (Primary Panel):**
- Card-based grid (3 columns on 1440px+, 2 on 1024px, 1 on <768px) instead of a dense table.
- Each agent card: name (bold), runtime kind badge (colored pill: LangGraph=purple, Goose=green, OpenCode=blue, Codex=orange), status dot, model name, last activity timestamp, sparkline showing invocation count (last 24h).
- Hover state: reveal quick actions (Chat, Edit, Clone, Delete) as icon buttons.
- Top of page: "New Agent" button (primary), filter bar (search, runtime kind filter, status filter, namespace filter), sort dropdown.
- Empty state: illustrated placeholder with "Create your first agent" CTA and link to templates.

**2. Agent Detail View (Split: Primary + Context Panel):**
- Primary panel tabs: Configuration | MCP Servers | Skills | A2A Peers | Git Integration | Sessions.
- Configuration tab: form organized in logical sections (Identity, Runtime Model, Storage, Security) with clear section headers and helper text.
- Context panel: shows recent activity feed (last 10 events), agent metadata (created, updated, namespace, owner), quick stats (total sessions, total invocations, avg response time).

**3. Chat Workbench (Full-width, no context panel):**
- Left sidebar (280px): Session list (searchable, with last message preview and timestamp). Collapsible.
- Main area: Message thread.
  - User messages: right-aligned, rounded bubbles (bg-primary/10, border-primary/30).
  - Agent messages: left-aligned, full-width content blocks.
  - Group related messages (thinking → tool calls → final response) into collapsible "turns" with a summary header.
  - Each turn header shows: turn number, duration, status icon (success/warning/error), expand/collapse chevron.
  - Tool calls: compact inline badges showing tool name and status, expandable to full detail panel below the message.
  - Plan/todo: floating card at top of conversation when active, shows progress bar and checklist.
- Bottom: Compose bar with text input, attachment button, model selector dropdown, and send button. Below compose bar: quick action chips (Subagents, A2A Delegate, HITL Review, View Artifacts).
- Right area (optional, toggleable): Artifact file browser with tree view and preview pane.

**4. Workflows List View:**
- Table view with columns: Name, Phase (colored badge), Current Step, Last Run, Status, Actions.
- Phase badges: Running (animated pulse, emerald), Queued (amber), Succeeded (checkmark, green), Failed (X, red), Waiting-Approval (clock, orange).
- Row hover reveals: Trigger, Inspect, Cancel, Delete actions.
- Summary cards at top: Total Workflows, Running Now, Failed (last 24h), Pending Approvals.

**5. Workflow Composer (Full-screen, no sidebars):**
- Full-viewport React Flow canvas with subtle dot grid background.
- Nodes: Redesigned with runtime-specific icons, colored left border strip (matching runtime kind), status badge (top-right corner), mini sparkline for execution time.
- Edges: Animated dashed lines for active workflows, solid for inactive. Color indicates step status (green=done, amber=running, red=failed, gray=pending).
- Floating toolbar (top-left): Undo, Redo, Auto-Layout, Zoom In/Out, Fit View, Run, Run History.
- Node palette: Floating panel (top-right, collapsible) with draggable node types.
- Properties panel: Slides in from right when a node is selected (replaces context panel).
- Minimap: Bottom-right, shows run status overlay.
- Cycle detection: Red highlight on problematic edges with tooltip explaining the cycle.

**6. Observability View (replaces separate Health, Intelligence, Usage, Audit panels):**
- Tabbed interface: Overview | Agents | Workflows | Costs | Alerts | Audit Log.
- Overview tab: 4 KPI cards (Total Invocations Today, Avg Response Time, Workflow Success Rate, Token Cost This Month) with trend indicators (↑↓ vs previous period).
- Charts: Time series for invocations (line chart), error rate (area chart), token cost breakdown (stacked bar by agent), workflow success/failure ratio (donut chart).
- Alerts table: severity, message, source, timestamp, status.
- Audit log: filterable timeline of user actions and system events.

**7. Settings Panel:**
- Left nav within settings: LLM Providers | Models | API Keys | Branding | Notifications | Danger Zone.
- LLM Providers: Card grid showing configured providers with health status, API key status, and model count. "Add Provider" button.
- Models table: name, provider, capabilities (chat, code, embedding, vision), context window, status.
- Cleaner organization — group related settings, add search within settings.

**8. Policies Editor:**
- Monaco editor takes 60% width, right 40% shows: policy metadata, validation status, affected agents list, policy effect summary.
- Syntax highlighting for YAML/JSON policy documents.
- Validation errors shown inline with red squiggles and a problems panel at the bottom.
- Template library: pre-built policy templates (Input Guardrails, Output Filtering, Tool Restrictions, Memory Limits, Model Allowlist) accessible from a sidebar.

**9. Skills Catalog:**
- Card grid of skills with icon, name, category badge, description (2 lines max), tags.
- Search and filter bar at top.
- Clicking a skill opens detail view in context panel: full description, file list, usage examples, "Attach to Agent" button.
- MCP Tools section below skills: grouped by category (Browser, Code Exec, Database, Documents, Git, GitHub, Kubernetes, Messaging, RAG, Web Search).

**10. Admin Panel:**
- Users table: ID, Username, Role (badge), Namespaces, Status (active/inactive), Last Login, Actions.
- "Add User" button opens a slide-over form.
- System config section: auth provider settings, session timeout, rate limits.

**Mobile Responsive:**
- Bottom tab bar: Agents | Workflows | Chat | Observability | More.
- "More" opens a sheet with remaining views.
- Agent cards: single column, stacked layout.
- Chat: full-screen, session list accessible via swipe from left.
- Composer: not available on mobile — show a message suggesting desktop use.
- All tables: card-based responsive transformation on small screens.

**Micro-interactions & Animations:**
- Page transitions: subtle fade + slide-up on view change.
- Card hover: translateY(-2px) + shadow increase.
- Status changes: color transition + optional pulse animation for active states.
- Loading states: skeleton screens matching final layout shape, not generic spinners.
- Empty states: custom illustrations with clear CTAs, not blank pages.
- Error states: inline banners with actionable recovery steps.
- Streaming indicator: animated dots at end of streaming messages, not a static spinner.
- Command palette (Cmd+K): prominent, searchable, with recent actions, navigation shortcuts, and quick commands.

**Accessibility:**
- All interactive elements: keyboard navigable with visible focus rings.
- Color contrast: WCAG AA minimum (4.5:1 for text, 3:1 for UI components).
- Screen reader: ARIA labels on all icon buttons, live regions for streaming content and status changes.
- Reduced motion: respect `prefers-reduced-motion`, disable non-essential animations.
- Font scaling: UI remains usable at 200% zoom.

**Overall Aesthetic:**
Inspired by Linear, Vercel Dashboard, and Raycast — clean, dense but not cluttered, information-rich with clear visual hierarchy. Dark theme by default with subtle use of color to convey status and type. Glass effects used sparingly (topbar, modals only). Cards have subtle borders, not heavy shadows. Data visualization uses a consistent color palette with clear legends. The UI should feel fast, responsive, and professional — built for engineers who use it daily.
```

---

### Individual View Prompts (for targeted redesign images)

#### Prompt: Agents List + Detail View
```
Design a dashboard view for "KubeSynthAI" showing a list of AI agents as cards in a 3-column grid. Each card shows: agent name (bold), a colored runtime badge (LangGraph=purple, Goose=green, OpenCode=blue), a green status dot, the model name in muted text, last activity time, and a small sparkline chart showing invocation count. Top of page has a "New Agent" primary button and a filter bar with search input, runtime dropdown, and status filter. Right side has a 320px context panel showing recent activity feed and agent stats. Dark theme with OKLCH colors: background oklch(0.145 0.008 274), cards oklch(0.185 0.011 274), primary teal oklch(0.65 0.13 175). Clean, Linear-inspired design.
```

#### Prompt: Chat Workbench
```
Design a chat interface for "KubeSynthAI" — an AI agent workbench. Left sidebar (280px) shows a searchable list of chat sessions with last message preview. Main area shows a message thread with grouped "turns" — each turn has a collapsible header showing turn number, duration, and status. Inside a turn: user message (right-aligned bubble), agent thinking section (collapsed by default), tool call badges (compact inline pills showing tool name and status), and the agent's final response. Bottom compose bar has text input, model selector dropdown, and send button. Below compose bar: quick action chips (Subagents, A2A Delegate, Artifacts). Dark theme, clean spacing, Inter font for body text. Professional developer tool aesthetic.
```

#### Prompt: Workflow Composer
```
Design a full-screen workflow DAG editor for "KubeSynthAI". A large canvas with a subtle dot grid background shows interconnected nodes representing agent steps. Nodes are rectangular with rounded corners, a colored left border strip (blue/purple/green), an icon, the agent name, and a small status badge in the top-right corner. Edges are animated dashed lines showing data flow. A floating toolbar (top-left) has undo, redo, auto-layout, zoom controls, and a "Run" button. A node palette (top-right, floating) has draggable step types. A minimap in the bottom-right shows the full graph overview. One node is selected, and a properties panel slides in from the right showing configuration fields. Dark theme, sleek, inspired by React Flow and Figma.
```

#### Prompt: Observability Dashboard
```
Design an observability dashboard for "KubeSynthAI" — an AI agent platform. Top row: 4 KPI cards showing Total Invocations Today (12,847, ↑12%), Avg Response Time (2.3s, ↓5%), Workflow Success Rate (97.8%), Token Cost This Month ($1,247). Below: a large line chart showing invocations over time (7 days), an area chart for error rate, a stacked bar chart for token cost breakdown by agent, and a donut chart for workflow success/failure ratio. Bottom section: an alerts table with severity icons, messages, sources, and timestamps. Tabs at top: Overview | Agents | Workflows | Costs | Alerts | Audit Log. Dark theme with teal accent, clean data visualization, modern SaaS dashboard aesthetic.
```

#### Prompt: Policies Editor
```
Design a policy editor for "KubeSynthAI". Split layout: left 60% is a Monaco code editor showing a YAML policy document with syntax highlighting. Right 40% is an info panel showing: policy name, description, validation status (green checkmark), affected agents list (4 agents with status badges), and a policy effect summary chart. Bottom of editor: a problems panel showing validation errors (currently none). Left edge: a template library sidebar with pre-built policy templates (Input Guardrails, Output Filtering, Tool Restrictions, Model Allowlist). Dark theme, professional developer tool aesthetic, clean typography.
```

#### Prompt: Mobile Responsive View
```
Design a mobile view of "KubeSynthAI" on an iPhone-sized screen. Bottom tab bar with 5 icons: Agents, Workflows, Chat, Observability, More. Main screen shows agent cards in a single-column list — each card has agent name, runtime badge, status dot, and last activity time. Top bar has hamburger menu (left), brand logo (center), notification bell and search icon (right). Pull-to-refresh gesture implied. Dark theme, large touch targets (44px minimum), clean mobile layout. Professional app aesthetic.
```

---

## Implementation Priority

If implementing incrementally, tackle in this order:

| Phase | Scope | Impact |
|---|---|---|
| **Phase 1** | Navigation overhaul (icon rail + breadcrumbs + URL routing), top bar simplification | Highest — fixes discoverability |
| **Phase 2** | Agent list → card grid, agent detail → tabbed + context panel | High — most-used view |
| **Phase 3** | Chat workbench restructuring (session sidebar, turn grouping, artifact panel) | High — most complex view |
| **Phase 4** | Observability dashboard (unify Health + Intelligence + Usage + Audit) | Medium — consolidation win |
| **Phase 5** | Workflow composer polish (node redesign, edge status colors, execution heatmap) | Medium — power user view |
| **Phase 6** | Mobile optimization (responsive tables → cards, simplified composer, touch-friendly) | Medium — accessibility |
| **Phase 7** | Micro-interactions, skeleton loaders, empty states, command palette expansion | Polish — quality of life |

---

## Design Inspiration References

| Reference | What to Borrow |
|---|---|
| **Linear** | Clean density, keyboard-first UX, command palette, status indicators |
| **Vercel Dashboard** | Card layouts, deployment lists, project health indicators |
| **Raycast** | Command palette as primary interface, extensions marketplace pattern |
| **GitHub** | File tree + preview split, inline code review, status badges |
| **Datadog** | Observability dashboards, time series charts, alert management |
| **Figma** | Canvas-based editor UX, floating toolbars, property panels |
| **Notion** | Block-based content, inline editing, clean typography hierarchy |
| **Stripe Dashboard** | Data visualization, KPI cards with trends, clean tables |

---

*Generated for KubeSynthAI Web UI — React + Tailwind CSS + shadcn/ui dashboard.*
