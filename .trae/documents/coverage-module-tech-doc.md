# 覆盖率模块技术实现文档

## 1. 架构总览

覆盖率模块由两层能力叠加构成：

- **MVP采集层**：单次采集任务的触发、构建、JaCoCo执行、报告生成，解决"这一次跑出来的覆盖率是多少"。
- **账本累积层**（在MVP基础上新增）：跨多次采集的覆盖率合并，解决"方法没改就不该丢覆盖、方法改了就该清零重新验证"的核心业务问题。

两层通过 `coverage_java/service.py` 中的顶层 `CoverageJavaService` 编排衔接：每次采集任务（`run`）产出JaCoCo报告后，若任务开启了账本模式，则将本次exec/XML解析结果交给 `ledger_service.py` 做账本合并，而不是简单覆盖上一次的统计。

技术栈：FastAPI + SQLAlchemy async（MySQL） + arq（Redis队列，独立于Celery） + WebSocket（实时进度） + Vue3/Element Plus前端。

## 2. 数据模型

六张核心表，分两组：

**采集执行记录组**
- `coverage_tasks`：覆盖率任务定义（关联项目、代码仓库、采集模式单测/运行时、调度配置）
- `java_coverage_runs`：每次采集的执行记录（状态、开始/结束时间、commit信息）
- `java_coverage_reports`：每次run产出的报告（总体覆盖率、分母分子、MinIO报告文件地址）

**账本累积组**
- `coverage_ledgers`：账本头，每个任务对应一本账，记录当前累积的整体覆盖率快照
- `coverage_ledger_files`：按文件维度存储累积后的逐行覆盖数据，核心字段 `lines_json`（行号→覆盖状态的映射）
- `coverage_ledger_events`：每次合并操作的审计记录，记录本次合并的 `methods_kept/methods_reset/methods_removed/methods_added` 统计和 `mismatch_classes_json`（本次整类重算的类清单）

四表之间的关系：一个task对应一个ledger，一个ledger下有多个ledger_file（按源文件拆分），每次run触发一次合并会产生一条ledger_event，并更新对应ledger_file的lines_json。

## 3. 核心算法

### 3.1 方法单元解析与指纹（java_method_parser.py）

用 javalang 做AST解析定位方法声明的起始行，再用括号匹配算法向下扫描确定方法体的精确结束行（AST本身不提供可靠的结束行号）。每个方法单元确定后，对方法体文本（忽略空白和注释）计算SHA-1指纹，作为判断"方法是否被修改"的依据——指纹不同即认为方法改动过。

### 3.2 方法级迁移判定（ledger_migrator.py）

拿旧账本和新一轮源码解析结果做方法级比对，产出四种状态：

- **kept**：方法指纹未变，旧覆盖数据原样搬运（这是"继承"角标的来源，因为搬运的是近似值而非本次exec实测值）
- **reset**：方法指纹变化，清零覆盖数据，等待本次新采集的exec数据覆盖
- **removed**：方法在新源码中消失，从账本里剔除，直接影响分母下降
- **added**：方法是新出现的，覆盖数据初始为全未覆盖，分母上升

### 3.3 Class级mismatch处理

迁移是方法级的精细操作，但如果整个类的字节码CRC64与账本记录的历史值不匹配（比如类结构发生了JaCoCo无法用方法级对齐处理的大改动），则放弃方法级迁移，直接对该类做整类重算，不参与kept/reset/removed/added的精细判定。这类发生mismatch的类会记录在 `coverage_ledger_events.mismatch_classes_json` 里用于审计。

### 3.4 合并逻辑（ledger_merger.py + ledger_service.py）

`ledger_service.py` 是账本编排核心，先判断"账本对齐方向"（当前源码相对账本是新增了commit还是回退），然后调用 `ledger_migrator` 得出方法级迁移方案，再调用 `ledger_merger` 把两层数据叠加：

- 迁移层给出的kept方法行覆盖（搬运值）
- 本次exec报告给出的实测行覆盖（精确值，针对reset/added方法以及mismatch类）

最终合并出的逐行覆盖写回 `coverage_ledger_files.lines_json`，并更新 `coverage_ledgers` 的汇总统计，同时落一条 `coverage_ledger_events`。

验证结论（已在真实环境端到端验证通过）：

- 场景1：方法改动清零，未改方法覆盖保留
- 场景2：删除方法，分母下降、覆盖率上升
- 场景3：新增方法，分母上升、覆盖率下降（实测TodoService.java从73/100=73%降到73/101=72.28%）

## 4. 采集流程

两种采集模式，由 `build_service.py` 和 `runtime_service.py` 分别处理：

**单测模式**：git clone/checkout目标commit → maven/gradle构建时注入jacocoagent.jar（offline模式）→ 执行单测生成exec文件 → jacococli生成XML报告 → xml_parser解析。

**运行时模式**：目标服务已以tcpserver模式挂载jacocoagent运行 → `runtime_service.py` 用jacococli的dump命令远程拉取exec快照 → 后续报告生成流程与单测模式一致。

`report_service.py` 统一负责jacococli报告生成命令调用、mismatch类解析、报告文件上传MinIO。

## 5. 异步任务与实时进度

采集任务用arq（非Celery）调度，独立队列 `qa.coverage_java`，独立worker进程（`workers/settings.py` 中的 `CoverageJavaWorkerSettings`）。`workers/coverage_java_tasks.py` 定义任务入口，执行过程中通过 `core/ws_manager.py` 的Redis pub/sub跨进程桥接，把进度推送给前端WebSocket连接（`api/v1/ws_coverage.py`），实现采集过程的实时状态展示。

## 6. API接口清单

- 任务CRUD：`coverage_tasks` 的增删改查
- 触发/取消采集：触发一次run，或取消进行中的run
- Run/Report查询：按任务查历史run列表、按run查report详情
- 累积账本接口：查询当前账本汇总、按文件查逐行覆盖、查合并历史事件列表

（具体路径定义见 `backend/app/api/v1/coverage_java.py`）

## 7. 前端交互设计

`views/coverage/` 下三个主页面：

- `CoverageListView.vue`：任务列表、触发采集弹窗（`TriggerCollectDialog.vue`）
- `CoverageDetailView.vue`：任务详情，含账本面板（`LedgerPanel.vue`，展示累积覆盖率、需回归方法列表、合并历史）、采集进度条（`ServiceProgressRow.vue`）、历史run条带（`RunHistoryStrip.vue`）
- `CoverageCodeView.vue`：代码浏览页，按行覆盖状态着色，区分"本次实测覆盖"和"继承搬运覆盖"两种视觉标记

实时进度通过 `utils/progress-ws.ts` 封装WebSocket连接，状态存入 `stores/coverage.ts`（Pinia）。

## 8. 依赖与配置

- 后端新增依赖：`javalang==0.13.0`（Java AST解析）
- 关键环境变量（`.env.example`）：`JACOCO_AGENT_JAR_PATH`、`JACOCO_CLI_JAR_PATH`、`MAVEN_HOME`、`COVERAGE_WORKSPACE_DIR`、`COVERAGE_JAVA_MAX_CONCURRENCY`、`COVERAGE_JAVA_DEFAULT_TIMEOUT`
- 基础设施：MySQL（持久化存储）、Redis（arq队列 + WebSocket pub/sub）

## 9. 数据库迁移演进

六次迁移按时间顺序体现了功能演进路径：基础三表（任务/run/report）→ 双模式支持（单测/运行时）→ 源码快照 → 代码源管理 → commit/来源/告警支持 → 账本累积体系（`20261022_1600_f8a9b0c1d2e3_add_coverage_ledgers.py`，新增三张账本表）。
