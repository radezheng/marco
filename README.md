# Marco Regime Monitor (MVP)

用免费官方数据源把 [index.md](index.md) 的宏观监控清单落成：
- 可执行：🟢🟡🔴 指标状态 + A/B/C（Risk-On/Neutral/Risk-Off）仓位模板（到资产大类/板块）
- 可复盘：PostgreSQL 存历史原始值/派生值/状态/模板选择
- 可升级：可选接入 Azure OpenAI `gpt-5.2-chat` 生成“为什么变红/本周总结”

## 运行（本地）

1) 启动 Postgres

```bash
cd "$PWD"
docker compose up -d
```

2) 后端（FastAPI）

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 按需修改 .env（DATABASE_URL）
uvicorn app.main:app --reload --port 8000
```

3) 拉取数据并计算状态（手动触发一次）

```bash
cd backend
source .venv/bin/activate
python -m app.ingest
```

4) 前端（Vite + React）

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。

建议：后端与前端分别在两个终端窗口前台运行（不要用 `&` 放到后台），避免 macOS 下后台进程读取 TTY 被系统暂停导致“连接成功但页面空白”。

如果你确实要后台启动，确保重定向 stdin：

```bash
nohup npm run dev -- --host 127.0.0.1 --port 5173 </dev/null > ../frontend.vite.log 2>&1 &
```

## 环境变量

后端见 [backend/.env.example](backend/.env.example)。

### 访问统计（Telemetry，可选）

为便于你自己判断“页面访问人数/次数”，后端提供一个非常轻量的访问统计记录：

- 记录内容（MVP）：时间戳、页面路径、前端 session_id（本地 localStorage 随机生成）、粗粒度 IP 网段（IPv4 /24 或 IPv6 /48）、User-Agent、Referrer、Accept-Language，以及基于（网段+UA+盐）的 `visitor_hash`（用于近似 UV）。
- 隐私策略：不存完整 IP；`visitor_hash` 由服务端加盐计算。
- 关闭方式：设置 `TELEMETRY_ENABLED=false`。

查看统计：

- `GET /api/telemetry/stats?days=30` 返回近 N 天 PV（次数）/ sessions（会话数）/ visitors（近似人数）及按日 PV。

## 说明

- 数据源：优先用 FRED 的公开 CSV 图表导出（不需要 API key），必要时可换成对应官网 CSV。
- 判定：规则引擎做数值与状态，LLM 只做解释与总结（可选）。

## 界面与图表说明

### 1) 系统状态（Regime A/B/C）

- **A（Risk-On，绿）**：核心信号整体处于“舒适区”（多为 🟢）。
- **B（Neutral，黄）**：信号分化/过渡期（既不是全绿，也没进入显著应激）。
- **C（Risk-Off，红）**：核心信号出现明显压力（多红，或波动结构进入应激）。

说明：这是“状态识别（Regime Monitor）”输出，用于回答“是否需要提高/降低风险承受度”，不是点位预测。

### 2) Drivers（为什么是这个状态）

Drivers 面板展示 `core` 核心信号集合（当前 MVP 约 4 个）：

- `synthetic_liquidity`：合成流动性方向（见下方“合成流动性（周变化）”）。
- `credit_spread`：信用压力（用 **HY OAS** 作为 CDX 的官方可复盘替代）。
- `funding_stress`：美元资金压力（用 `SOFR - IORB` 或 `SOFR - EFFR` 作为免费官方替代）。
- `vix_structure`：波动结构（优先用 `VIX - VXV`，若无 VXV 则退化为 VIX 水平分位数）。

面板会统计 🟢🟡🔴 的数量，并保留 Raw JSON（折叠）便于排查。

### 3) 指标状态卡片（🟢🟡🔴）

每张指标卡片的颜色来自“滚动历史分位数阈值”（默认 3 年窗口）：

- 🟢：低于 90% 分位（压力低/结构健康）
- 🟡：介于 90%–95% 分位（需要关注）
- 🔴：高于 95% 分位（需要行动/提升防守）

卡片里会优先把 `details` 解析成可读字段（阈值/当前值/结构标签），同时保留 Raw JSON（折叠）。

### 4) 图表（时间序列）分别代表什么

前端图表区的每一张图，来自 `/api/observations/{seriesKey}`：

- `synthetic_liquidity_delta_w`：**合成流动性周变化**（WALCL - TGA - RRP 的 1 期差分；WALCL 为周频，所以 1 期≈一周）。
- `hy_oas`：**信用压力代理**（HY OAS；免费、连续、可复盘）。
- `funding_spread`：**资金压力代理**（`SOFR - IORB`；若缺 IORB 则用 `SOFR - EFFR`）。
- `treasury_realized_vol_20d`：**美债波动代理**（10Y 收益率变动的 20 日实现波动，年化）。
- `vix_slope`：**VIX 结构**（`VIX - VXV`；负值通常对应 contango，正值偏 backwardation/应激）。
- `usd_twi_broad`：**美元强弱（官方替代 DXY）**（Fed Broad Trade-Weighted USD Index）。

注意：在“只用免费官方数据”的约束下，部分原始指标（如 CDX、DXY、FRA–OIS）会用最接近的官方可复盘代理替代；替代关系在 Drivers 里也会注明。


### 派生序列（项目内计算，不直接从外部拉取）

- `synthetic_liquidity_level`：WALCL - WTREGEN - RRPONTSYD
- `synthetic_liquidity_delta_w`：`synthetic_liquidity_level` 的 1 期差分（WALCL 周频，1 期≈一周）
- `funding_spread`：SOFR - IORB（若缺 IORB 则 SOFR - EFFR）
- `vix_slope`：VIXCLS - VXVCLS
- `treasury_realized_vol_20d`：DGS10 日变动的 20 日实现波动（年化）

### 对应的“原始官方页面”（可选，用于交叉核对）

（本项目实际拉取仍以 FRED CSV 为主；以下链接用于核对口径与制度变更）

- Federal Reserve H.4.1（资产负债表）：https://www.federalreserve.gov/releases/h41/
- U.S. Treasury Daily Treasury Statement（财政每日报表，含 TGA）：https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/
- NYFed ON RRP（操作与统计页面）：https://www.newyorkfed.org/markets/desk-operations/reverse-repo
- Cboe Volatility Index（VIX 家族说明）：https://www.cboe.com/tradable_products/vix/

---

## 每个图表表示什么（口径 / 怎么来的 / 现实含义）

下面按前端“时间序列图表区”的每张图，给出**计算口径**、**现实含义**与**常见解读**。这些解释旨在帮助“看懂监控面板”，不构成交易建议。

### 1) 合成流动性（周变化）`synthetic_liquidity_delta_w`

- **怎么来的（口径）**：
	- 先构造：`synthetic_liquidity_level = WALCL - WTREGEN - RRPONTSYD`
		- `WALCL`：美联储总资产（周频，H.4.1）
		- `WTREGEN`：TGA（财政部在 Fed 的一般账户）
		- `RRPONTSYD`：隔夜逆回购余额（ON RRP）
	- 再取 1 期差分：`delta_w = level.diff(1)`（因为 WALCL 周频，1 期≈一周）。
- **单位**：原始序列为 USD；前端会把显示做换算（例如 bn USD），不改变底层存储。
- **现实里代表什么**：用“Fed 资产扩张（+）/财政抽水（-）/RRP 吸水（-）”粗略近似**系统净流动性**的方向变化。
- **怎么解读**：
	- 上行（正周变化）：往往对应风险资产环境更友好、融资条件相对宽松（但并非充分条件）。
	- 下行（负周变化）：往往对应流动性边际收缩，若叠加信用/资金/波动压力更容易进入防守。

### 2) HY OAS（信用压力）`hy_oas`

- **怎么来的（口径）**：直接使用 FRED 的 `BAMLH0A0HYM2`（ICE BofA US High Yield OAS）。
- **单位**：bps（基点）。
- **现实里代表什么**：高收益债相对无风险利率的“超额利差”，是**信用风险溢价**与**风险偏好**的综合温度计。
- **怎么解读**：
	- 利差扩张：信用环境变差/违约担忧上升/风险偏好下降。
	- 利差收敛：信用环境改善/风险偏好回升。
	- 本项目用其作为“信用压力”的免费官方可复盘代理（替代 CDX 等付费指标）。

### 3) 资金压力（SOFR 相对 IORB/EFFR）`funding_spread`

- **怎么来的（口径）**：`funding_spread = SOFR - IORB`；若缺 IORB，则退化为 `SOFR - EFFR`。
- **单位**：bps。
- **现实里代表什么**：衡量“担保融资利率（SOFR）”相对政策利率/有效联邦基金利率的偏离，可视作**美元短端资金是否紧张**的近似代理。
- **怎么解读**：
	- 走阔：资金面更紧（融资需求上升、质押品/流动性偏紧等），可能对风险资产不利。
	- 走窄/为负：资金面更松。
	- 注意：单一利差会受制度、准备金分布、季末效应等影响，宜与信用/波动指标联合看。

### 4) 美债实现波动（10Y，20 日年化）`treasury_realized_vol_20d`

- **怎么来的（口径）**：基于 10Y 收益率 `DGS10` 的日变动，计算 20 个交易日滚动标准差并年化（项目内派生）。
- **单位**：%（年化波动率；口径是“收益率变动”的波动）。
- **现实里代表什么**：利率市场的不确定性与“定价噪声”。利率波动上升时，通常会抬升风险资产的折现率不确定性与杠杆资金的保证金压力。
- **怎么解读**：
	- 上升：利率不确定性加大，风险平价/杠杆策略更可能去杠杆；宏观冲击期更常见。
	- 下降：利率环境更稳定。

### 5) VIX 结构（近月 - 3M）`vix_slope`

- **怎么来的（口径）**：`vix_slope = VIXCLS - VXVCLS`（若 `VXVCLS` 不可用，会退化为仅用 VIX 水平分位数做判断）。
- **单位**：VIX 点位差（不是 bps）。
- **现实里代表什么**：反映波动率期限结构：
	- 负值（近月 < 3M）：更常见于 contango（市场更“平静”）。
	- 正值（近月 > 3M）：更常见于 backwardation（短期应激/对冲需求强）。
- **怎么解读**：期限结构比单看 VIX 水平更“状态型”，对识别应激阶段通常更敏感。

### 6) 广义美元指数（官方替代 DXY）`usd_twi_broad`

- **怎么来的（口径）**：直接使用 `DTWEXBGS`（Fed Broad Trade-Weighted U.S. Dollar Index）。
- **单位**：指数点（无量纲）。
- **现实里代表什么**：美元相对主要贸易伙伴货币的综合强弱，常与全球金融条件、外债压力与风险偏好同向或交织。
- **怎么解读**：
	- 美元走强：对非美金融条件偏紧、对大宗与新兴市场有时偏逆风。
	- 美元走弱：全球金融条件可能更友好（但仍取决于驱动因素：增长/利差/风险偏好）。

