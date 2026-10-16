# 接入指南 · Codex（终端/代码 Agent）

本模板在 Codex 这类以**命令行 + 代码文件**为主的环境中的用法。目标：换数据后能一键跑通、
生成可在浏览器打开的看板。

## 1. 环境能力

- 运行 shell、Python，读写文件；无飞书/豆包专有能力，不依赖它们；
- 所有操作通过脚本完成，不要求手工处理。

## 2. 安装依赖

```bash
python3 -m pip install -r scripts/requirements.txt
```

## 3. 数据目录约定（示例）

```
project/
  data/                 # 按月明细 xls/xlsx
  output/               # 自动生成
  scripts/
  docs/
```

## 4. 一键构建数据

```bash
python3 scripts/run_pipeline.py \
  --input data/ \
  --output output/ \
  --exclude $(cat exclude.txt 2>/dev/null) \
  --role-hint role_hint.json
```

- `exclude.txt` 每行一个误命名文件（可选）；
- 产出 `output/dashboard_data.json`。

## 5. 渲染 HTML

- 用 `prompts/build-dashboard.md` 作为实现规约，写一个单文件 HTML；
- 推荐内联：ECharts + `dashboard_data.json`，得到"双击即可离线打开"的成品；
- 可在脚本里增加一个简单的渲染步骤（如把 JSON 注入模板占位符），实现完全一键：
  ```
  python3 scripts/build_html.py --data output/dashboard_data.json \
      --template templates/dashboard.html --out output/销售数据看板.html
  ```
  （按需自行实现，模板包未强制提供。）

## 6. 验证

- 先对数据层：`03_aggregate.py` 打印的总销售额/成本/毛利/客户数与 README 示例对照；
- 再对页面：按 `prompts/qa-checklist.md`；
- 用 headless 浏览器（如已安装）可快速确认无控制台错误：
  ```bash
  # 可选：python3 - <<'PY' ... playwright ...
  ```
- 不做过度 Debug；确定性错误修复后重跑。

## 7. 交付

- 交付 `output/销售数据看板.html`（文件路径），告知用浏览器打开；
- 保持单文件、无外部依赖；不交付临时 master.pkl。

## 8. 工程约束（避免历史 bug）

- 不硬编码年份/月数/路径；目标块、盈亏线、月数全部随筛选动态计算；
- 客户名转义；图表实例 dispose；框选入口可发现；
- 口径以 `docs/01`、`docs/03` 为唯一权威。
