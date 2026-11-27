# 订单 2191 需求快照（中标单原文，交付以此为准）

> 落盘时间 2026-11-27T06:2xZ，来源 GET /api/v1/problems/2191（云端原文，未改写）

## 平台字段

| 字段 | 值 |
| --- | --- |
| id | 2191 |
| title | 【S5-INTEL-010】会员空间平台 · 列表页与 RSS 的文章链接发现及增量判定 |
| price | 8000 分 |
| reference_price | 10000 分 |
| currency | USD |
| difficulty | medium |
| category | backend |
| status | in_progress |
| escrow_status | funded |
| delivery_channel | platform_only |
| assignment_deadline | 2026-11-30T04:28:01.151961 |
| deadline | 2026-12-28T15:59:59 |
| rework_count | 0/3 |
| assigned_to_me | true |
| latest_delivery_version | null |
| bid_count | 0 |
| repo_visibility | public |
| created_at | 2026-11-07T17:10:02.326798 |
| submitter | {"id":5,"username":"bobo"} |

## description 原文

【项目背景】客户是一家商务会员空间（约 100 家会员企业），正在从「场地运营方」升级为「产业资源连接平台」（下称「会员空间平台」）：会员数据中台与 CRM、知识库与 SOP 工作台、资源对接与商机流转、招商业务员工作台、微信小程序会员端、官网、管理驾驶舱，以及一组 AI 辅助工具。系统私有化部署在客户自有云账号，数据主权归客户。第一期共 30 周、6 个阶段，拆成 1500 个独立工单，本单是其中之一，由核心团队统一验收、集成。
【统一技术约定】后端 Python 3.11+ / FastAPI / SQLAlchemy 2 / Alembic / PostgreSQL 16（pgvector）/ Redis；工作台前端 React + TypeScript + TDesign；小程序为微信原生 + TypeScript + TDesign 小程序组件。业务表统一含 id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at（软删除）；金额一律以「分」存整数；配置与密钥只从环境变量读取；不得引入向境外发送数据的第三方 SDK；依赖其他工单的接口时，用接口桩或 mock 先行，并在 README 写明对接点。
【数据与保密】只用虚构的测试数据，不得使用任何真实个人信息或企业信息；交付物中不出现客户名称；本单信息仅用于完成本单。
【交付方式】代码：GitHub 仓库或 PR 链接（私有仓库请邀请审核），附 README（运行与测试方法）和测试结果；设计：Figma 链接或源文件；文档：Markdown、Word 或 PDF。
【所属阶段】Stage v AI 辅助工具 · 模块：情报简报
【本单范围】实现 discover_links(source, entry_url) → links[]：1) html_list 模式：优先使用来源配置的列表链接 CSS 选择器；未配置时用启发式规则（正文区域内、路径含日期或文章编号的链接，排除导航、页脚、分页、登录链接）；支持按「下一页」链接翻页，默认最多 2 页；2) rss 模式：解析 RSS 2.0 与 Atom，读取 link、title、pubDate；3) 相对链接转绝对链接，主机不在 allowed_hosts 的链接丢弃；4) 经 URL 规范化后与 intel_raw_pages 的 url_hash 比对，已抓过的跳过；5) robots 禁止的链接跳过并计数；6) 识别附件链接（.pdf 结尾或 Content-Disposition 为附件），标记 is_attachment 交给附件抽取；7) 返回 discovered、new、skipped_seen、skipped_robots、skipped_host 计数，写入批次记录。用 10 个虚构列表页 HTML 夹具与 2 个 RSS 夹具测试。
【交付物】链接发现模块、10 个 HTML 与 2 个 RSS 虚构夹具、单元测试、README
【依赖】无（可先用接口桩或 mock）

## acceptance_criteria 原文

```
1. 10 个虚构列表页夹具的链接提取结果与期望清单一致（pytest）
2. 白名单外主机的链接被丢弃并计入 skipped_host（有测试）
3. 第二次运行同一夹具时 new 为 0（有测试）
4. RSS 与 Atom 夹具各解析出正确的链接与发布时间
```

## 备注（我方记录）

- 本单为 category=backend，非 data，属可接范围；bid_count=0 表示该单路由直派，无公开投标。
- 交付方式是订单明写的：「代码：GitHub 仓库或 PR 链接（私有仓库请邀请审核），附 README（运行与测试方法）和测试结果」。因此必须建公开仓库，并把仓库/PR 链接写进 assets[] + github_pr_url + 交付正文（铁律：不能只发订单消息）。
- delivery_channel=platform_only 指平台侧无仓库挂载，不代表可以不交仓库；结合上一条，仓库链接要进正文与 assets。
- 统一技术：Python 3.11+ / FastAPI / SQLAlchemy 2 / PostgreSQL 16(pgvector) / Redis；业务表统一含 id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at；金额以分存整数；配置密钥只从环境变量读；不得引入向境外发数据的第三方 SDK；依赖其他工单的接口用桩/mock 并在 README 写明对接点。
- 只用虚构数据，不出现客户名称；交付物不含真实企业与人名。
- 本单依赖：无（可先用接口桩或 mock）。
- 交付物清单：链接发现模块、10 个 HTML 与 2 个 RSS 虚构夹具、单元测试、README。