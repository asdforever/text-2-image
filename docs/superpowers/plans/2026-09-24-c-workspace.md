# C workspace implementation plan

> Execute with subagent-driven-development, preserving existing local changes. No commit or deployment requested.

**Goal:** Implement the approved C homepage and project workspace as working UI.

**Architecture:** Reuse current routing, generation state and backend APIs. Replace page composition and visual presentation; keep task progress truthful and canvas embedded. Use isolated C styles for the approved surfaces and shared navigation.

**Tech Stack:** React, TypeScript, existing CSS, Playwright.

**Spec:** Approved interactive `picagent-c-flow-prototype.html`, September 24 conversation. Forest green #17745a, paper #f6f8f5, ink #18231f, borders #dce5df. Homepage recommendation/activity split and horizontal recent projects; workspace left configuration and right image cards. Preserve dark theme, keyboard access and responsive layouts.

- [x] Homepage: real recommendation, independent task activity, empty/error/loading states; verify workflow-home and recent-project tests.
- [x] Creation: optional image, editable filename-derived name, retry upload using same project; verify mock mutation tests.
- [x] Workspace: C navigation/header/tabs/config/results grid, compact status and embedded canvas; preserve all existing generation actions and batch provenance.
- [x] Verification: typecheck/build, focused route/generation tests, browser screenshots and read-only real app check.

Ruling: Work in the existing checkout to preserve extensive user changes and running local preview. Do not create a clean worktree that excludes these changes.

Validation: production build passes; 14 distinct focused E2E cases passed across homepage, creation, gallery, mobile, canvas, uploads and row layout; 12 focused unit tests passed. Broader hero-suite file still contains preexisting stale module-count/editable-prompt/legacy-canvas assumptions; not reported as fully passing. Gallery expectations updated for the new modal. Read-only real homepage/workspace screenshots reviewed. Review fixes: measured virtual rows, restored navigation icons at 1200px, aligned drawer breakpoint at 1023px.
