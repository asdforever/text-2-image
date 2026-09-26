# PicAgent Studio UI Demo

## Run

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

Open `http://127.0.0.1:5174/`. The demo is a standalone frontend with mock data and local browser persistence.

## Screenshots

- Three-column workbench: [`artifacts/spec-base-tab.png`](../artifacts/spec-base-tab.png)
- Base-image workspace: [`artifacts/spec-base-tab.png`](../artifacts/spec-base-tab.png)
- Suite configuration and plan review: [`artifacts/spec-suite-config.png`](../artifacts/spec-suite-config.png)
- Suite canvas and task lineage: [`artifacts/spec-suite-canvas.png`](../artifacts/spec-suite-canvas.png)

## Verified Journeys

1. Create a project, upload three source images, select three cards, batch-generate white-background images, and download `picagent-base-images-3.zip`.
2. Open 主图, select up to eight product assets and one or more of the eight main-image modules, then generate results directly in the right panel.
3. Open 详情图, select up to four product assets and one to five of the eighteen detail modules, generate an editable plan, then generate and reorder the module images.
4. Switch 白底图, 主图, 详情图, and 视频 without mixing the two generation drafts; inspect the independent panel scrolling at 1440×960 and 1280×720.

## Generation Workbench Architecture

- `GenerationWorkspaceLayout` provides the shared desktop split view: a 360–408px configuration rail, an independently scrolling result region, and a fixed submit footer. Below 1024px the configuration rail becomes an Escape-closeable drawer.
- Hero and suite drafts are persisted by `projectId + mode`, so navigating between output types does not overwrite either configuration.
- 主图 uses direct generation: validation creates one module task for every selected main-image module.
- 详情图 uses two stages: the first action creates editable copy/visual plans, and the second generates images from the confirmed order.
- Generated assets are appended to the existing project asset collection. Completed modules survive partial failures; failed modules can be retried without resubmitting successful modules.

## Scope Notes

## Acceptance Evidence

- Responsive browser check: 1440x900 and 1920x1080 fit without horizontal overflow; the right panel remains rendered at 200px in the acceptance viewport.
- Virtual-scroll check: 100 simulated items use 34 virtual rows and render 13 cards at once; 145 sampled frames average 7.02ms (142.5 estimated FPS; 37.5ms maximum sampled interval).
- Demo recording: artifacts/page@d7229e4f5b0e0335686ac05df9b8b310.webm, 194.2 seconds and 8,285,747 bytes. It covers base-image batch generation, Suite planning/canvas navigation, asset/history inspection, keyboard tab switching, and virtual-grid scrolling.
- The virtual-scroll result is a browser-side acceptance sample, not a Chrome DevTools Performance panel trace. Task 13.6 remains open until that trace is captured.
- Video generation remains a placeholder in this frontend change; the recording covers implemented workflows only.

- Generation and image editing use deterministic mock fixtures with simulated asynchronous delays.
- Video generation is intentionally a placeholder in this frontend change.
