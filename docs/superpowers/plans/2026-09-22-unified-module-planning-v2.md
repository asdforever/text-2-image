# Unified Module Planning V2 Implementation Plan

> **For agentic workers:** Execute the approved design below with test-first implementation and independent code review. Continue without another design approval; the linked task already contains approval to implement.

**Goal:** New hero and suite compilations use a fixed short selected-style seed and one model call per image task to produce style refinement, composition and content; the server renders the image prompt.

**Architecture:** V2 是唯一编译与确认路径。固定风格种子、单次结构化模块规划和服务端合成结果都写入冻结快照；旧 V1 任务及风格规划模板已清理。

**Tech Stack:** Python/FastAPI/Pydantic, React/TypeScript, pytest and Playwright.

**Spec:** User-approved final design in Codex task `01a0a991-7b8f-7182-a212-399144253b21`, last handoff at 2026-09-22 14:05 UTC.

## 当前实施状态（2026-09-23）

后续用户明确要求移除 V1 回退、旧任务及旧风格规划模板；下面最初的检查清单是历史计划，V1 兼容和回退条款已经失效。实现和实际行为以 [统一模块规划](../../unified-module-planning-v2.md) 为准。旧批次和规划已删除；项目与素材随后由用户自行删除。
