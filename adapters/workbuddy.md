# 接入指南 · WorkBuddy

本模板在 WorkBuddy（通用 AI 工作助手，具备终端与文件系统）中的用法。
**脚本平台无关，不依赖飞书/豆包专有 API。**

## 1. 环境能力假设

- 可执行 shell 命令、读写工作区文件；
- 可用 Python3；如缺少依赖，用 pip 安装；
- 交付以工作区文件 + 打开方式为准。

## 2. 准备依赖

```bash
pip install -r scripts/requirements.txt
```

## 3. 放入数据

- 把按月导出的销售明细（`.xls` / `.xlsx`）放到一个目录，例如 `data/`；
- 用文件名或月份识别误命名/重复文件，在 `--exclude` 中剔除；
- 目标、固定费用等由用户单独提供。

## 4. 一键跑数据

```bash
python scripts/run_pipeline.py --input data/ --output output/ \
  --exclude 误命名.xls [--role-hint role_hint.json]
```

产物：`output/master.pkl`、`output/dashboard_data.json`。

## 5. 渲染看板

- 阅读 `prompts/build-dashboard.md` 与 `docs/04`，生成**自包含单文件 HTML**；
- ECharts 可用本地文件或 CDN（`https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js`，
  备用 `https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js`）；
- 若要双击离线可用，把 ECharts 与 JSON 都内联进 HTML。

## 6. 自检与交付

- 按 `prompts/qa-checklist.md` 核对；
- 交付 HTML 文件，并告知打开方式（浏览器直接打开）；
- 如 HTML 依赖同目录资源，提醒连同目录一起提供（建议直接内联，避免该问题）。

## 7. 与平台无关的注意点

- 所有路径用相对路径或参数传入，不写死；
- 年份、月数、盈亏线、目标块全部从数据现算（见 build-dashboard 第三节）；
- 该环境若没有"发布链接"能力，交付文件即可；有则按其发布方式给链接。
