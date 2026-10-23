# JaCoCo 覆盖率模块 MVP · Python 平台前后端并行开发计划

## Context

设计文档 [jacoco-coverage-design.html](computer://c:\Users\gg.zhao\code-case-platform\jacoco-coverage-design\jacoco-coverage-design.html) 已定稿（15 章 + 14 节前端交互）。用户要求 **Python 平台部分先行独立开发、前后端并行**。本计划只覆盖 M0-M3 核心 MVP（任务 CRUD + 手动触发 + 多服务并行采集 + WebSocket 进度 + 报告查看 + 行级覆盖代码浏览），定时 cron / 阈值告警 / 增量 diff / 需求第三方联动 / GraalVM 兜底 全部划入二期。

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| 异步任务引擎 | **沿用 arq**（项目已有 `qa.execution` / `qa.code_case` 队列），不引入 Celery |
| 实时进度 | **第一期就要 WebSocket**，项目目前无 WS 基础设施，需新建 `app/core/ws_manager.py` |
| MVP 范围 | **M0-M3**：CRUD + 手动触发 + 多服务并行 + WS 进度 + 报告查看 + 行级覆盖代码浏览 |
| 前后端并行契约 | **Pydantic schemas + 空路由 stub 先行**（Day 1），前端拿到真实路径即可开工 |

## 与现状的差异（需在实现时处理）

1. 设计文档中 Celery → 实际用 **arq**（API 一致：`pool.enqueue_job` + `_queue_name` + `_job_id`）
2. 设计文档假设存在 WebSocket → 实际**需从零搭建**（FastAPI WebSocket + Redis pub/sub 跨进程广播）
3. 设计文档 S14 的"git diff → 增量覆盖率"后端算法 → **划入二期**；MVP 前端 Diff 页只渲染行级覆盖 + 文件源码，不做 git diff 对比

## 开发阶段

### Phase 0 · 契约对齐（Day 1，串行，阻塞后续所有并行工作）

**产出**：
1. `backend/app/modules/coverage_java/schemas.py` — 全部 Pydantic schemas（Task / Run / Report / WsMessage / FileCoverage）
2. `backend/app/api/v1/coverage_java.py` — 全部 REST 路由 stub，返回 hardcoded mock 数据
3. `backend/app/api/v1/ws_coverage.py` — WebSocket 路由 stub（接受连接，定时推 mock snapshot）
4. `backend/app/main.py` — 注册路由 + WS
5. `frontend/src/api/coverage.ts` — 前端 API 封装（对接 stub 路由，立刻可跑通）
6. `frontend/src/types/coverage.ts` — TypeScript interface（与 Pydantic schema 对齐）

**验收**：后端 `uvicorn` 起服务，前端能调通所有 stub API 并收到 WS mock 推送。

### Phase 1 · 并行开发（Day 2-6）

#### 后端链路（5 个工作日）

**Step B1 · 数据模型 + 迁移**（Day 2）
- 新文件：`backend/app/db/models/coverage_java.py`
  - `CoverageTask`：`project_id` `name` `services JSON` `branch` `diff_base_branch` `requirement_ref` `owner_id` `status` `current_run_id` `last_completed_at` `last_failed_at` `created_by/updated_by` + 复用 `SoftDeleteMixin` 与 `generate_id` 雪花主键
  - `JavaCoverageRun`：`task_id` `trigger_type` `overall_status` `services_total/completed/failed` `started_at` `finished_at`
  - `JavaCoverageReport`：`run_id` `task_id` `service_name` `commit_sha` `status` `progress` `stage` `stage_detail` `line_rate` `branch_rate` `lines_covered` `lines_total` `branches_covered` `branches_total` `line_coverage_json JSON` `xml_report_path` `html_report_path` `exec_file_path` `build_log_path` `error_message` + `service_errors JSON`
- 迁移：`cd backend && alembic revision --autogenerate -m "add coverage_java tables"`，参照基线迁移 [20261019_0940_2b9f94c1d0a7_baseline_schema.py](file:///c:/Users/gg.zhao/code-case-platform/backend/migrations/versions/20261019_0940_2b9f94c1d0a7_baseline_schema.py) 调整 `autoincrement=False` 与 FK-safe downgrade
- 注册：`backend/app/db/models/__init__.py` 导出新模型

**Step B2 · Service 层**（Day 3-4）
- 新目录：`backend/app/modules/coverage_java/`
  - `repository.py` — 3 张表的 CRUD（参照 [code_case/repository.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/modules/code_case/repository.py)）
  - `build_service.py` — git clone → 检测 maven/gradle → 注入 `-javaagent:jacocoagent.jar=destfile=...` → `mvn clean test` 子进程；输出 `workspace/<task_id>/<run_id>/<service>/coverage.exec`
  - `report_service.py` — 调 `java -jar jacococli.jar report coverage.exec --classfiles ... --xml report.xml --html report/`，产物路径写入 DB
  - `xml_parser.py` — 解析 JaCoCo XML：`<counter type="LINE|BRANCH">` 聚合 + `<line nr ci cb>` 行级
  - `service.py` — 编排：对每个 service 顺序执行 build→report→parse→upload MinIO→写库，**每个关键节点发 WS 广播**
  - `minio_client.py` — 复用 [report/service.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/modules/report/service.py) 的 MinIO 上传逻辑
- 关键依赖：`git`、`mvn`/`gradle`、`java` 在 worker 机器 PATH 上；JaCoCo jar 路径走 settings

**Step B3 · arq 任务**（Day 4 下午）
- 新文件：`backend/app/workers/coverage_java_tasks.py`
  - `COVERAGE_JAVA_QUEUE = "qa.coverage_java"`
  - `run_coverage_collection_task(ctx, task_id, run_id)` 顺序执行 N 个 service（MVP 不做并行，避免 JVM 资源爆）
  - `enqueue_coverage_collection(task_id, run_id)` API 侧投递
- 更新 [workers/settings.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/workers/settings.py)：新增 `CoverageJavaWorkerSettings`（独立队列、`job_timeout=3600`、`max_jobs=1` 保守起步）
- 启动命令：`python -m arq app.workers.settings.CoverageJavaWorkerSettings`

**Step B4 · WebSocket 基础设施 + 真实 API 实现**（Day 5）
- 新文件：`backend/app/core/ws_manager.py`
  - `ConnectionManager`：`connect(websocket, channel)` / `disconnect` / `broadcast(channel, message)`
  - 跨进程：arq worker 写 Redis pub/sub 频道 `coverage:task:{task_id}`，FastAPI WS 进程订阅
- 新文件：`backend/app/api/v1/ws_coverage.py`
  - `WS /ws/coverage/tasks/{task_id}/progress`：连接即推 snapshot；订阅 Redis 频道转发消息
- 替换 stub：`backend/app/api/v1/coverage_java.py` 全部路由接真实 service
  - `POST /projects/{pid}/coverage-tasks`（create）
  - `GET /projects/{pid}/coverage-tasks`（list + 筛选）
  - `GET /projects/{pid}/coverage-tasks/{task_id}`（detail）
  - `PATCH` / `DELETE`
  - `POST .../trigger`（生成 run + N 个 report 占位 → arq 投递 → 返回 run_id + reports）
  - `POST .../cancel`（更新 run.overall_status=cancelled，arq 侧通过轮询 DB 状态中断）
  - `GET .../runs`、`GET /coverage/runs/{run_id}/reports`、`GET /coverage/reports/{report_id}`
  - `GET /coverage/reports/{report_id}/files`（文件列表 + 行级覆盖）
  - `GET /coverage/reports/{report_id}/file-content?path=`（文件源码 + 行级标记）
  - `GET /coverage/reports/{report_id}/build-log`
- 权限：所有路由挂 `Depends(get_current_user)` + `require_project_permission("coverage:*")`

**Step B5 · 配置**（Day 5）
- 更新 [core/config.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/core/config.py)：
  - `jacoco_agent_jar_path: str`
  - `jacoco_cli_jar_path: str`
  - `coverage_workspace_dir: str = "./workspace/coverage"`
  - `coverage_java_max_concurrency: int = 1`
  - `coverage_java_default_timeout: int = 1800`

#### 前端链路（5 个工作日，与后端并行）

**Step F1 · API + Types**（Day 2，Phase 0 完成后立即可做）
- 新文件：`frontend/src/types/coverage.ts`（与 Pydantic schema 对齐的 TS interface）
- 新文件：`frontend/src/api/coverage.ts`（参照 [api/test-plan.ts](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/api/test-plan.ts) 的 axios 封装模式）

**Step F2 · Pinia Store**（Day 2-3）
- 新文件：`frontend/src/stores/coverage.ts`（参照设计文档 S10.1）
  - state：`tasks` / `currentTask` / `currentRunReports` / `currentReport` / `codeDiff` / `ws` / `wsConnected` / `filters`
  - actions：`fetchTasks / createTask / updateTask / deleteTask / triggerCollection / cancelCollection / connectProgressWS / disconnectProgressWS / _applyProgressUpdate / _fallbackToPolling / fetchTaskDetail / fetchCodeDiff`

**Step F3 · 路由 + 菜单**（Day 3）
- 更新 [router/index.ts](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/router/index.ts)：在 `/:projectCode` 子路由下注册
  - `/coverage` → `CoverageListView.vue`
  - `/coverage/:taskId` → `CoverageDetailView.vue`
  - `/coverage/:taskId/code` → `CoverageCodeView.vue`
- 更新项目侧边栏菜单（如适用，参照现有模块）

**Step F4 · 页面与组件**（Day 3-5）
- 新目录：`frontend/src/views/coverage/`
  - `CoverageListView.vue` — 表格 + 筛选 + 新建/编辑弹窗（参照 [TestPlanView.vue](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/views/test-plan/TestPlanView.vue) 的 `el-table` + `el-dialog`）
  - `CoverageDetailView.vue` — 任务元信息 + 当前 run 进度（多服务行）+ 历史 run strip + 各服务覆盖率环形 + 行级覆盖入口按钮
  - `CoverageCodeView.vue` — 文件树 + 代码区，行级覆盖标记（绿/红/黄），tooltip 显示 ci/cb
  - `components/CoverageTaskFormDialog.vue` — 创建/编辑表单（项目下拉 + 服务多选 + 分支 + diff_base_branch + requirement_ref + cron_expr）
  - `components/ServiceProgressRow.vue` — 单服务进度条 + 状态 + 错误按钮 + 重试按钮
  - `components/RunHistoryStrip.vue` — 历史 run 时间线（MVP 简化版，无对比弹窗）
  - `components/CoverageRing.vue` — 环形进度（复用 el-progress type="circle"）

**Step F5 · WebSocket 客户端**（Day 5）
- 新文件：`frontend/src/utils/progress-ws.ts`
  - `ProgressWSClient`：连接超时 2s 降级轮询、断线指数退避重连（1s/2s/4s/8s 最多 5 次）
  - 消息分发：根据 `type` 更新 store

**Step F6 · Mock 数据**（Day 2 起）
- 新文件：`frontend/src/api/__mocks__/coverage.ts`（Phase 0 stub 未就绪时备用；stub 就绪后删除）

### Phase 2 · 联调（Day 7）

1. 前端把 axios baseURL 从 mock 切到真实后端
2. 端到端流程：创建任务 → 触发 → WS 进度实时刷新 → 完成后查看报告 → 行级覆盖代码页
3. 边界用例：触发 409、WS 断线降级、单服务失败重试、取消后状态残留
4. 修复联调发现的 schema 不一致 / 状态机 bug

## 文件清单

### 后端新增（全部新文件，不改现有业务代码）

```
backend/app/modules/coverage_java/
  __init__.py
  schemas.py            # Phase 0
  repository.py         # Step B1
  service.py            # Step B2
  build_service.py      # Step B2
  report_service.py     # Step B2
  xml_parser.py         # Step B2
  minio_client.py       # Step B2
backend/app/db/models/coverage_java.py        # Step B1
backend/app/api/v1/coverage_java.py           # Phase 0 stub → Step B4 实
backend/app/api/v1/ws_coverage.py             # Phase 0 stub → Step B4 实
backend/app/core/ws_manager.py                # Step B4
backend/app/workers/coverage_java_tasks.py    # Step B3
backend/migrations/versions/<timestamp>_add_coverage_java.py  # Step B1
```

### 后端修改

- `backend/app/db/models/__init__.py`（注册新模型）
- `backend/app/main.py`（注册路由 + WS）
- `backend/app/workers/settings.py`（新增 `CoverageJavaWorkerSettings`）
- `backend/app/core/config.py`（新增 5 个 settings 字段）

### 前端新增（全部新文件）

```
frontend/src/types/coverage.ts
frontend/src/api/coverage.ts
frontend/src/stores/coverage.ts
frontend/src/utils/progress-ws.ts
frontend/src/views/coverage/
  CoverageListView.vue
  CoverageDetailView.vue
  CoverageCodeView.vue
  components/
    CoverageTaskFormDialog.vue
    ServiceProgressRow.vue
    RunHistoryStrip.vue
    CoverageRing.vue
```

### 前端修改

- `frontend/src/router/index.ts`（新增 3 条子路由）

## 复用现有资产（不要重造）

- 后端：`get_db` / `get_current_user` / `require_project_permission`（[api/deps.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/api/deps.py)）；`generate_id` 雪花 ID（[core/snowflake.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/core/snowflake.py)）；`SoftDeleteMixin`；`redis_client`；arq `create_pool` 模式（[workers/tasks.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/workers/tasks.py)）；MinIO 上传逻辑（[modules/report/service.py](file:///c:/Users/gg.zhao/code-case-platform/backend/app/modules/report/service.py)）
- 前端：axios 实例 + 拦截器（[api/client.ts](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/api/client.ts)）；`el-table` + `el-dialog` + `el-progress` 模式（[TestPlanView.vue](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/views/test-plan/TestPlanView.vue)、[PlanRunReportView.vue](file:///c:/Users/gg.zhao/code-case-platform/frontend/src/views/test-plan/PlanRunReportView.vue)）

## 验证方式

### 后端单测 / 手测
- `cd backend && alembic upgrade head`（在测试库验证迁移）
- `cd backend && alembic downgrade -1`（确认可回滚）
- `pytest backend/tests/test_coverage_java_*.py`（如有时间补，MVP 不强制）
- 手测：`curl -X POST /api/v1/projects/1/coverage-tasks` → `POST .../trigger` → 观察 arq worker 日志 + WS 客户端

### 前端
- `cd frontend && npm run dev`
- 访问 `/:projectCode/coverage` 走完一遍：创建任务 → 触发 → 看进度 → 查看报告 → 看代码

### 端到端
- 准备一个 demo Maven 项目（设计文档 S13 有快速启动命令），注入 JaCoCo agent，跑一次完整流程

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| arq worker 与 FastAPI WS 进程间消息同步 | Redis pub/sub，worker publish、WS 进程 subscribe；arq 的 `redis_settings` 已就绪 |
| 目标 Java 项目构建失败 | MVP 不解决；build_log 上传 MinIO，前端可查看 |
| WS 跨进程广播丢消息 | snapshot 消息保证前端重连后能拉最新状态；进度消息允许丢 |
| 多服务并行资源爆 | MVP 顺序执行（`max_jobs=1`），二期再做并发 |
| 行级覆盖数据量大 | `line_coverage_json` 按文件懒加载，详情接口按需返回 |

## 二期占位（不在本计划）

- 增量覆盖率（git diff merge-base + diff2html）
- 定时调度（cron_expr + scheduler_scan_task 模式）
- 阈值告警 + 飞书通知
- GraalVM native image 兜底 / Shell 脚本模式
- 需求第三方平台联动
- 历史 run 对比弹窗
- 多服务并行采集
