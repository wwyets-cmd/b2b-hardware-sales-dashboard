# 建材五金 B2B 销售数据看板 · 跨环境规则模板

> 把管家婆等进销存系统导出的多份《单位销售明细》，一键转换成一套**全局联动、自包含、
> 可离线打开**的经营看板，并配套客户分层、流失/骤降预警、SKU 动销分析、品类赚钱矩阵和
> 增长建议。**规则与脚本与平台无关**，可在豆包工作、WorkBuddy、Codex CLI、本地命令行等
> 环境直接运行。

## 它解决什么问题

个体户/批发商每月从进销存系统导出一堆 Excel，却很难快速看清：

- **机会**：哪些客户值得深挖、哪些品类赚钱、哪些新客是真客户、增长点在哪；
- **风险**：哪些大客户在流失、哪些在骤降、哪些 SKU 常年不动、库存和回款是否有问题；
- **复用**：换一个月、换一年、换一个 AI 工具，规则不重写、口径不走样。

## 快速开始（命令行，任意环境）

```bash
# 1) 准备依赖（仅 pandas + xlrd + openpyxl）
pip install -r scripts/requirements.txt

# 2) 一键跑通：提取 → 品牌/品类匹配 → 聚合
python scripts/run_pipeline.py \
  --input  /path/to/你的明细xls目录 \
  --output /path/to/输出目录

# 产出：dashboard_data.json（结构化数据）
# 3) 用你所在环境的渲染能力，按 docs/04-dashboard-structure.md 生成看板 HTML
```

在 AI 助手环境里，把本目录交给助手，让它读取 `SKILL.md` 并上传明细，即可直接生成看板。

## 目录结构

```
b2b-sales-dashboard-template/
├── SKILL.md                          # 跨环境 skill 主文件（规则总入口）
├── README.md                         # 本文件
├── docs/
│   ├── 01-business-rules.md          # 业务口径：单位/同比/调货/新客/沉睡/活跃/流失/骤降/动销
│   ├── 02-customer-segmentation.md   # 客户六分层 + RFM 三维
│   ├── 03-metrics-dictionary.md      # 指标字典：每个指标的定义/公式/判定依据
│   ├── 04-dashboard-structure.md     # 五页看板结构 + 模块清单 + 图表选型
│   └── 05-data-schema.md             # 输入表头别名 + 字段 + 输出 JSON schema
├── scripts/
│   ├── 01_extract.py                 # 读取多份 xls/xlsx，字段自动识别，合并长表
│   ├── 02_classifier.py              # 品牌/品类自动判定（规则可维护）
│   ├── 03_aggregate.py               # 清洗/分层/预警/多维聚合 → dashboard_data.json
│   ├── run_pipeline.py               # 一键串联
│   └── requirements.txt
├── prompts/
│   ├── build-dashboard.md            # 给 LLM 的完整构建指令
│   ├── qa-checklist.md               # 交付前自检清单（bug 检查标准化）
│   └── analysis-recommendation.md    # 增长建议（产品×市场矩阵）
├── adapters/
│   ├── doubao-work.md                # 豆包工作接入
│   ├── workbuddy.md                  # WorkBuddy 接入
│   └── codex.md                      # Codex CLI 接入
└── templates/                        # 看板渲染参考（按需）
```

## 设计原则

1. **口径即资产**：规则文档是核心，脚本是规则的实现；两者必须一致。
2. **平台无关**：纯 Python 脚本不依赖任何平台 API，平台只负责取数和交付。
3. **数据保真**：所有数字从明细现算、可追溯，缺失留空并标注，不编造。
4. **门槛透明**：客户分层门槛、品类剔除等取舍一律在图表上写明。

## 适配范围

- 行业：建材、五金、家居橱柜五金、胶业等 B2B 分销（默认规则）。
- 数据源：管家婆《单位销售明细》等含"客户/商品/业务员/金额/数量/成本"的导出。
- 其他 B2B 行业可复用"分层/动销/预警/矩阵"骨架，仅替换行业配置（品牌、品类、门槛）。

## License

MIT
