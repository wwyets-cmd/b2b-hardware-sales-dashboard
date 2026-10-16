# 接入指南 · 豆包工作（Doubao Work / 豆包办公）

本模板在豆包工作（云电脑、Python + 终端 + 文件交付）中的标准用法。

## 1. 环境能力

- 有终端（Bash）、文件读写、`present_files` 交付；
- 已装 Python3，按需安装 `pandas / numpy / xlrd / openpyxl`（见 `scripts/requirements.txt`）；
- 用户上传的附件可同时拿到**本地路径**与 **URL**。

## 2. 取数

- 让用户把按月导出的《单位销售明细》xls/xlsx 放入一个目录（或直接读取附件目录）；
- 记录误命名/重复导出文件，作为 `--exclude`；
- 公司年度目标、固定费用由用户单独提供（不来自明细）。

## 3. 运行

```bash
# 安装依赖（首次）
pip install -r scripts/requirements.txt

# 一键
python scripts/run_pipeline.py \
  --input  <明细目录> \
  --output <输出目录> \
  --exclude 误命名文件.xls \
  --role-hint role_hint.json     # 可选：业务员/客服名单
```

产出 `master.pkl` 与 `dashboard_data.json`。

## 4. 渲染

- 按 `prompts/build-dashboard.md` 生成单文件 HTML（内联 ECharts）；
- 遵循 `docs/04` 五页结构与 `docs/01` 口径；
- 数据较大时，可把 `dashboard_data.json` 内联进 HTML（自包含、双击可开）。

## 5. 自检与交付

- 按 `prompts/qa-checklist.md` 逐项核对；
- 可用 `html` skill 的 `shot.py` 出桌面/移动截图核对；
- 交付：`present_files` 提交 HTML（文件名语义化，如"销售数据看板.html"）；
  若用户要链接，可发布为 doubao-html 后交付链接；
- 不把中间 `master.pkl` 作为交付物（除非用户要求）。

## 6. 注意

- 不硬编码任何本地路径或年份；
- 飞书相关能力（如 lark-cli）可选，本模板不依赖它；
- 控制台无错误、框选可用、空态正常后再交付。
