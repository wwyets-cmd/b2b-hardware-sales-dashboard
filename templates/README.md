# templates/

本目录用于放置**看板渲染参考**，按需使用，不强制。

可放内容：

- `dashboard.html`：最小 HTML 骨架（含 ECharts 引用、左侧导航、`CHARTS={}` 管理、
  hash 路由），作为渲染起点；
- 或你自己沉淀的"成品看板样例"，供 `prompts/build-dashboard.md` 对齐风格。

约定：

- 若渲染环境已能按 `docs/04` + `prompts/build-dashboard.md` 直接生成单文件 HTML，
  本目录可以保持为空；
- 若要实现完全一键（Codex/命令行），可在此放带占位符的模板，再写一个 `build_html.py`
  把 `dashboard_data.json` 注入占位符（见 `adapters/codex.md`）。

保持单文件、原生 JS、内联 ECharts；不要引入框架或构建工具。
