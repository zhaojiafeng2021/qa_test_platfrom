# 覆盖率累积账本设计（单测 + 运行时合并 · 方法级保留）

## 1. 背景与目标

现状（见 `backend/app/modules/coverage_java/`）：

- 每次采集独立产出一份 `JavaCoverageReport.line_coverage_json`，只反映本次 `.exec`
- 增量覆盖率 `DiffCoverageService` 每次重算 `merge-base(base)..HEAD` 的变更行，范围正确，但覆盖数据不跨采集累积
- 单测（unittest）与运行时（runtime）结果互不相通

目标：

1. **合并来源**：同一任务下单测、运行时的覆盖结果合并为一份"累积覆盖"
2. **跨版本保留**：开发修复代码产生新 commit 后，未改动的方法保留之前的覆盖；改动的方法清零，需重新覆盖
3. **增量正确**：增量覆盖率基于最新 commit 的变更行 + 累积覆盖计算；删除的代码不再计入，新增代码计为未覆盖
4. **可解释**：界面区分"本次实测覆盖"和"继承自历史版本的覆盖"，并列出"因代码变更需回归的方法"

非目标：

- 不尝试让 JaCoCo 识别字节码已变化的类的旧 exec 数据（class ID 不同无法对应），这部分只由方法迁移处理
- 不支持 Kotlin / Groovy 源码（方法解析只针对 Java）
- 不处理部署流水线的自动 dump（可作为后续运维建议）

## 2. 为什么不能直接用 JaCoCo merge

| 问题 | 说明 |
|---|---|
| class ID 绑定字节码 | JaCoCo 用 class 字节码 CRC64 匹配 exec 数据；类中任一行变化，整个类的历史数据在新报告中被丢弃 |
| 运行时计数随 JVM 重启清零 | 修复后重新部署，agent 内存计数归零 |
| 单测与运行时 class 不一定一致 | 平台编译与部署包编译的 JDK/参数不同，可能导致 `Execution data for class X does not match` |

结论：两层合并，各管一段。

- **exec 层（精确）**：用 `jacococli merge` 合并本轮所有 `.exec`，再用目标 commit 的 class 生成报告。class ID 没变的类（字节码完全一致）数据精确保留，行和分支计数都准确。
- **方法层（迁移）**：class ID 变了的类，JaCoCo 会丢掉它的旧数据。由平台按"commit + 文件 + 方法 + 行"把未改动方法的覆盖迁移过来，作为补充。

## 3. 核心概念

| 概念 | 含义 |
|---|---|
| 采集结果（Report） | 现有 `JavaCoverageReport`：一次采集、一个服务、一个 commit、一个来源（unittest / runtime）的原始行级覆盖 |
| 账本（Ledger） | 一个任务下一个服务在一个"轮次"内的累积状态，始终对齐到某个 `head_commit` |
| 轮次（Round） | 账本的生命周期。默认持续累积，用户可手动"开始新一轮"清空（例如进入新的提测周期） |
| 方法索引（Method Index） | 某 commit 下每个 Java 文件的方法列表：签名、起止行、指纹 |
| 方法指纹（Fingerprint） | 方法源码文本（按行保留结构）的哈希，用于判断方法跨版本是否未改动 |
| 继承覆盖（Inherited） | 从旧 commit 迁移过来的覆盖（方法未改动，按行偏移映射） |

## 4. 方法级保留规则

### 4.1 方法单元的划分

JaCoCo XML 的 `<method line=...>` 只给出首条可执行行，没有结束行，因此方法边界由平台解析 Java 源码得到。

| 源码结构 | 归属单元 |
|---|---|
| 普通方法、构造器 | 自身为一个单元 |
| lambda、方法内的代码块 | 归入外层方法 |
| 匿名类 / 局部类中的方法 | 归入最外层的具名方法（匿名类改动即视为外层方法改动） |
| 字段初始化、实例初始化块 | 每个类一个伪单元 `<init-fields>` |
| 静态初始化块、静态字段初始化 | 每个类一个伪单元 `<clinit>` |
| 内部类（具名）中的方法 | 按内部类 FQN 单独成单元 |

方法键（key）：`类 FQN + "#" + 方法名 + "(" + 参数类型列表 + ")"`，参数类型取源码中的写法（去泛型参数、去空白）。重载靠参数类型区分。

### 4.2 方法指纹

指纹 = 方法声明起止范围内的源码，逐行 `strip()` 后用 `\n` 拼接，再取 SHA-1。

- 保留行结构（空行也保留），保证"指纹相同 ⇒ 行数相同 ⇒ 可以按固定偏移映射行号"
- 只改缩进或行尾空格不会改变指纹
- 修改方法内注释会改变指纹 → 该方法清零（已确认，见第 16 节决策 1）

### 4.3 迁移判定

旧版本账本迁移到新版本时，逐个方法对比：

| 判定 | 条件 | 处理 |
|---|---|---|
| 未改动 | 新旧都存在同一 key，且指纹相同 | 整个方法的行覆盖按 `offset = new_start - old_start` 平移，标记 `origin=inherited` |
| 已改动 | 同一 key，指纹不同 | 方法内所有行清零，进入"需回归方法"列表 |
| 已删除 | 旧有新无 | 丢弃 |
| 新增 | 旧无新有 | 全部未覆盖 |

不在任何方法单元中的行（理论上只有 import、类声明等不可执行行）不迁移。

迁移只依赖两个 commit 的方法索引，不依赖 `git diff`，所以 rebase、force push、cherry-pick 后同样适用。代价是方法重命名、移动到其他类、文件改包名都会被视为"删除 + 新增"。

### 4.4 示例

```text
v1                                   v2（修复后）
10  public int add(a, b) {           10  // 新增一行注释（方法外）
11      return a + b;                11  public int add(a, b) {
12  }                                12      return a + b;
13                                   13  }
14  public int div(a, b) {           14
15      return a / b;                15  public int div(a, b) {
16  }                                16      if (b == 0) throw ...;   ← 修复
                                     17      return a / b;
                                     18  }
```

- `add`：指纹相同，行 11→12（offset +1），覆盖继承
- `div`：指纹不同，整个方法清零，列入"需回归方法"
- 若 `div` 属于增量范围，增量覆盖率随之下降，直到重新测试覆盖

## 5. 合并规则

### 5.1 exec 层：jacococli merge 精确合并（已确认，第 16 节决策 4）

账本保存本轮累积的合并 exec（`merged_exec_path`）。每次新结果到达：

```text
jacococli merge  ledger.merged.exec  report.exec  --destfile new.merged.exec
jacococli report new.merged.exec --classfiles <目标 commit 的 class> --sourcefiles <目标 commit 源码> --xml ...
```

- exec 按 class ID 存储探针数据，merge 是对同一 class ID 的探针做按位或，**行和分支计数都是精确的**，单测与运行时同 commit 下的分支并集也能正确算出
- 旧 commit 的 class 数据同样保留在 merged exec 中。目标 commit 下字节码没变的类（class ID 相同）会自动命中，不需要任何迁移；字节码一致意味着行号表一致，行号无需偏移
- 字节码变了的类，JaCoCo 生成报告时会忽略其旧数据，这部分交给 5.2 的方法迁移补齐
- 每份结果的 `.exec` 本身仍按现有逻辑存 MinIO；merged exec 只是累积产物，可随时由本轮所有 exec 重新 merge 得到

### 5.2 方法层：只补"字节码变化的类"

对 5.1 报告中的每一行：

| 情况 | 结果 |
|---|---|
| exec 报告中该行 `covered` / `partial` | 采用 exec 结果（精确），`sources` 记录实测来源 |
| exec 报告中该行 `missed`，但所在方法从旧账本迁移且旧状态为已覆盖 | 采用迁移结果，`sources=[inherited]` |
| 两者都有覆盖 | 逐字段取 `max`，`sources` 取并集 |

说明：

- 只有"字节码变了、但方法源码没变"的方法才会走迁移，例如同一个类里另一个方法被修复。这部分分支计数沿用旧账本的值，是唯一的近似来源，界面以"继承"标注
- 由于 class ID 相同的类已被 exec 精确命中，迁移只需处理 class ID 发生变化的类。实现上仍对全量方法做迁移判定，结果与 exec 报告取并集，二者一致时无副作用
- 合并是幂等的（exec 按位或、行级取 max），运行时 dump 是否 reset 不影响正确性

### 5.3 class 不一致检测

单测由平台编译，运行时 exec 来自部署包，两者 JDK 或编译参数不同时，同一源码也可能得到不同的 class ID。jacococli report 会对这类情况输出 `Execution data for class ... does not match`。

注意：merged exec 里本来就带着旧 commit 的数据，对它生成报告时，被代码变更改动过的类也会出这条警告，属于预期情况。所以检测必须针对**单次结果**：用本次 `report.exec` 对本次 commit 编译出的 class 生成报告（即现有的单次报告），只在这一步收集警告。

- 记录到 `report.warnings`（类名列表），界面提示"部署包与平台编译产物不一致"
- 不一致的类在 exec 层拿不到数据，**不**用方法迁移去填补（源码相同但字节码不同，说明编译环境不同，不属于代码变更）；迁移时按 `report.warnings` 排除这些类
- 平台编译使用与部署一致的 JDK 版本（服务配置增加 `jdk_version`，P3 处理），从源头减少不一致

## 6. 对齐方向（目标 commit 的选择）

新结果 R（commit = C_r）到达，当前账本 L（head = C_l）：

| 情况 | 处理 |
|---|---|
| `C_r == C_l` | 直接合并 |
| `C_l` 是 `C_r` 的祖先（正常向前） | L 迁移到 C_r，再合并 R，账本 head 前进到 C_r |
| `C_r` 是 `C_l` 的祖先（旧环境晚到的数据） | R 迁移到 C_l 后再合并，账本 head 不变 |
| 互不为祖先（rebase / force push） | 以 commit 时间较新的一方为目标，另一方迁移过去 |

祖先判断用 `git merge-base --is-ancestor`，在采集时的工作区里执行，结果写入事件记录。

`backward` 情况下 head 不变，但 exec 层仍然合并：新的 merged exec 用 head commit 的 class 生成报告，R 中字节码未变的类自动命中；字节码变了的类，把 R 的单次报告按方法迁移到 head 后再并入。

### 6.1 轮次与分支绑定（已确认，第 16 节决策 2）

账本绑定分支：`coverage_ledgers.branch` 记录本轮的分支。

- 采集时任务的 `branch` 与 active 账本的 `branch` 不同 → 自动关闭旧轮次（`is_active=false`，保留只读），以本次结果开启新一轮，记录事件 `direction=new_round, reason=branch_switch`
- 同一分支内的 rebase / force push 不开新轮，按 `diverged` 处理
- 用户仍可手动"开始新一轮"（`reason=manual`）

## 7. 前置条件：commit 必须对得上

账本的正确性依赖"报告里的 commit = 产生 exec 的那份代码"。

| 来源 | 现状 | 需要的调整 |
|---|---|---|
| unittest | 平台自己 clone + 编译 + 测试，commit 天然一致 | 支持指定 commit：clone 后 `checkout` 到所选 commit |
| runtime | 平台按分支 HEAD 编译 class，部署的版本可能更旧 | 触发时必须指定部署的 commit；clone 后 `checkout` 到该 commit 再编译 |

### 7.1 commit 下拉选择（已确认，第 16 节决策 3）

不提供手填输入框。commit 来源只有下拉列表：

- 新接口 `GET /projects/{pid}/code-repos/{rid}/commits?branch=&limit=30`：在已有的 `_repo_cache` bare 仓库上 `fetch` 后执行 `git log <branch> -n 30 --format=%H%x1f%h%x1f%an%x1f%aI%x1f%s`，返回 sha、短 sha、作者、时间、提交说明
- 触发采集弹窗：选择分支对应的 commit 列表，默认选中分支最新一条；列表项显示 `短sha · 时间 · 作者 · 提交说明`，支持按说明 / sha 前缀过滤（Element Plus `filterable`，只在已加载的列表中筛选，不接受列表外的值）
- 后端校验：`commit_sha` 必须是该分支历史上的提交（`git merge-base --is-ancestor <sha> origin/<branch>`），否则 400
- 触发接口 `commit_sha` 为可选，不传时后端解析为分支 HEAD 的 sha 并写入 run，保证每条报告都有确定的 commit
- 流水线等外部调用同样走该接口传 sha，同一套校验

## 8. 数据模型

### 8.1 新增表 `coverage_ledgers`（账本头）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | 雪花 ID |
| task_id | BigInteger, index | 所属任务 |
| service_name | String(100) | 服务名 |
| branch | String(100) | 本轮绑定的分支，切换分支自动开新一轮 |
| round_no | Integer | 轮次，从 1 开始 |
| is_active | Boolean | 当前轮次为 true，同一 task+service 只有一个 active |
| head_commit | String(64) | 账本当前对齐的 commit |
| line_rate / branch_rate | Float | 累积全量覆盖率 |
| lines_covered / lines_total | Integer | |
| branches_covered / branches_total | Integer | |
| merged_exec_path | String(500) | MinIO：本轮累积的 jacococli merge 结果 |
| method_index_path | String(500) | MinIO：head_commit 的方法索引 JSON |
| classfiles_path | String(500) | MinIO：head_commit 编译出的 class 压缩包（backward 合并时复用，避免重新编译） |
| source_snapshot_path | String(500) | MinIO：head_commit 的源码快照（复用现有快照格式） |
| created_at / updated_at | DateTime | |

唯一约束：`(task_id, service_name, round_no)`。

### 8.2 新增表 `coverage_ledger_files`（行级数据，按文件存）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | |
| ledger_id | BigInteger, index | |
| file_path | String(500) | JaCoCo key，如 `com/example/Foo.java` |
| lines_json | JSON | `{line_no: {ci, mi, cb, mb, status, sources: [...]}}` |
| lines_covered / lines_total | Integer | 文件级汇总 |

按文件拆分，避免单行 JSON 过大，也方便源码页按文件读取。账本更新时整体替换该 ledger 的文件行（事务内 delete + insert）。

### 8.3 新增表 `coverage_ledger_events`（合并记录，便于追溯）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | |
| ledger_id | BigInteger, index | |
| report_id | BigInteger | 合并进来的采集结果 |
| source | String(20) | unittest / runtime |
| from_commit / to_commit | String(64) | 迁移前后 commit |
| direction | String(20) | init / same / forward / backward / diverged / new_round |
| reason | String(20) | new_round 时：branch_switch / manual |
| mismatch_classes_json | JSON | 本次 class 不一致的类（取自 report.warnings） |
| methods_kept / methods_reset / methods_removed / methods_added | Integer | 迁移统计 |
| reset_methods_json | JSON | 被清零方法的 key 列表（"需回归方法"） |
| line_rate_before / line_rate_after | Float | |
| created_at | DateTime | |

### 8.4 现有表调整

- `java_coverage_reports`：新增 `source`（unittest / runtime）、`warnings`（JSON，class 不一致等）、`method_index_path`；`commit_sha` 改为必填（总是来自下拉选择或解析出的分支 HEAD）
- `coverage_runs`：新增 `commit_sha`（触发时确定）、`source`
- `coverage_tasks.collection_mode`：语义不变，表示该任务默认采集方式；合并在账本层完成，同一任务两种来源都可以触发（触发接口新增可选参数 `source`）

### 8.5 方法索引 JSON 格式（MinIO）

```json
{
  "commit": "a1b2c3d",
  "files": {
    "com/example/demo/CalcService.java": [
      {"key": "com.example.demo.CalcService#add(int,int)", "start": 11, "end": 13, "fp": "5f2c..."},
      {"key": "com.example.demo.CalcService#<init-fields>", "lines": [5, 6], "fp": "9a10..."}
    ]
  }
}
```

伪单元（`<init-fields>` / `<clinit>`）的范围不连续，用 `lines` 列出行号，指纹按这些行的文本计算；迁移时按位置一一对应（行数相同才保留）。

## 9. 处理流程

采集流水线在现有 `_run_one_service` 的"写库"之后追加两步：

```text
clone → checkout(run.commit_sha) → 编译 / 测试 / dump → jacococli report（单次）→ 解析 XML
   → 【新】从 report 输出中收集 class 不一致警告 → report.warnings
   → 【新】解析源码生成方法索引（本 commit），上传 MinIO；class 打包上传
   → 写 report（单次原始结果，保持不变）
   → 【新】LedgerService.merge(report)
        1. 取 task+service 的 active ledger
           - 没有，或 ledger.branch != task.branch → 开新一轮（direction=init / new_round）
        2. 按第 6 节确定目标 commit T 与方向
        3. exec 层：jacococli merge(ledger.merged_exec, report.exec) → new.merged.exec
                    jacococli report(new.merged.exec, T 的 class/源码) → exec_lines
        4. 方法层：旧账本行数据（或 backward 时的单次报告）按方法索引迁移到 T，
                    排除 report.warnings 中的类 → migrated_lines + 迁移统计
        5. LineMerger.merge(exec_lines, migrated_lines) → 账本行数据
        6. 重算汇总，写 ledger / ledger_files / event，更新 head_commit、merged_exec_path
   → 广播 service_done（附带累积覆盖率）
```

模块划分（`backend/app/modules/coverage_java/`）：

| 文件 | 职责 | 依赖 |
|---|---|---|
| `java_method_parser.py` | 解析 Java 源码，输出方法单元与指纹 | `javalang`（纯 Python，固定版本） |
| `ledger_migrator.py` | 纯函数：方法索引对比 + 行迁移 | 无 IO，便于单测 |
| `ledger_merger.py` | 纯函数：exec 报告行与迁移行合并 + 汇总 | 无 IO |
| `ledger_service.py` | 编排：取账本、判断方向、exec merge、读写库与 MinIO | repository、build_service、report_service |
| `build_service.py`（改） | 新增 `merge_exec()`、`report_with_classes()`、checkout 指定 commit、收集不一致警告 | jacococli |

方法解析选型：`javalang` 能拿到方法声明的起始行，但没有结束行，结束行要靠括号匹配补齐（跳过字符串、字符字面量和注释）。备选方案是 `tree-sitter-java`，它直接给出完整范围，但需要引入原生 wheel。建议先用 `javalang`，再加括号匹配兜底；如果解析失败，该文件降级为"文件级保留"：整个文件的指纹相同才继承。

为什么在 worker 里解析：需要源码工作区，而采集时 worker 已经 clone 好了，不必再拉一次。

## 10. 增量覆盖率计算

现有 `DiffCoverageService.calculate_diff_coverage(changed_lines, line_coverage)` 不变，只把输入的 `line_coverage` 从"单次报告"换成"账本当前数据"：

- `changed_lines` = `merge-base(base, ledger.head_commit)..ledger.head_commit` 的新增 / 修改行
- `line_coverage` = 账本行数据（已经迁移到 head_commit）

结果天然满足需求：

| 场景 | 表现 |
|---|---|
| 开发删除代码 | 删除的行不在 head 的文件中，不进入分母 |
| 开发新增代码 | 新增行在 diff 中，账本里为未覆盖，计入分母 |
| 开发修改某方法 | 该方法清零，方法内的增量行重新变为未覆盖 |
| 未改动的增量方法 | 继承之前的覆盖，增量覆盖率保持 |

增量结果在每个变更行上附带 `sources`，界面可区分实测与继承。

## 11. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/{pid}/coverage-tasks/{tid}/ledger` | 各服务当前账本汇总（含轮次、head_commit、来源占比） |
| GET | `/projects/{pid}/coverage-ledgers/{lid}/files` | 文件列表汇总 |
| GET | `/projects/{pid}/coverage-ledgers/{lid}/file?path=` | 单文件源码 + 行覆盖（含 sources） |
| GET | `/projects/{pid}/coverage-ledgers/{lid}/diff-coverage` | 基于账本的增量覆盖率 |
| GET | `/projects/{pid}/coverage-ledgers/{lid}/events` | 合并历史（含需回归方法） |
| POST | `/projects/{pid}/coverage-tasks/{tid}/ledger/new-round` | 开始新一轮（旧账本 is_active=false 保留只读） |
| GET | `/projects/{pid}/code-repos/{rid}/commits?branch=&limit=30` | 分支最近提交列表，供下拉选择 |
| POST | `/projects/{pid}/coverage-tasks/{tid}/trigger` | 现有接口新增可选 `source`、`commit_sha`（须属于该分支历史，否则 400） |

现有 report 级接口保持不变，作为"单次采集原始结果"继续可用。

## 12. 前端

- 任务详情页顶部从"最近一次报告"改为"累积覆盖"卡片：全量 / 增量覆盖率、head commit、轮次，以及按来源拆分的条形图（单测 / 运行时 / 继承）
- 源码页行着色：实测覆盖（绿）、仅继承覆盖（浅绿 + 角标）、未覆盖（红）、部分（黄）；悬停显示来源与最后命中的采集
- 新增"需回归方法"面板：取最近一次迁移事件的 `reset_methods_json`，并标出其中已被重新覆盖的方法
- 合并历史时间线：每次采集的来源、commit 迁移方向、覆盖率变化
- "开始新一轮"按钮（二次确认）
- 触发采集弹窗：选择来源（单测 / 运行时）+ commit 下拉（默认分支最新提交，可按 sha / 说明筛选，不能手填）
- 轮次切换提示：任务分支与当前账本分支不同时，触发前提示"将开始新一轮，旧数据只读保留"
- 报告有 class 不一致警告时，在累积卡片和单次报告上显示提示和类列表

## 13. 边界情况与风险

| 场景 | 处理 |
|---|---|
| 方法重命名 / 移动类 / 改包名 | 视为删除 + 新增，覆盖不继承（保守） |
| 只改注释或格式 | 改缩进不影响；改方法内注释会清零该方法（决策 1） |
| 切换任务分支 | 自动开新一轮，旧轮次只读保留（决策 2） |
| merged exec 体积 | exec 按 class ID 存储，同一类每个版本一份探针数组；单轮几十次提交仍在 MB 级。需要时可只保留 head 能命中的类重新 merge |
| 方法签名不变但重载顺序调整 | key 含参数类型，不受顺序影响 |
| 同 key 多次出现（解析异常） | 该文件降级为文件级保留 |
| Lombok 等生成代码 | 源码中不存在对应方法，JaCoCo 已默认过滤生成方法；剩余未归属行不迁移 |
| 选错部署 commit | 单次报告会出现大量 class 不一致警告，界面醒目提示；这些类不迁移，避免错位数据进入账本 |
| 多服务共用同一仓库 | 账本按 task + service 隔离，方法索引按服务源码目录生成 |
| 账本数据量 | 行数据按文件存；单服务 5 万可执行行约 2–4 MB JSON，可接受；后续可改为压缩存储 |
| 并发合并 | 覆盖率队列 `max_jobs` 与单 run 串行已限制；合并时对 ledger 行 `SELECT ... FOR UPDATE` |

主要风险：

1. **Java 解析准确性**：括号匹配遇到文本块（`"""`）、注解里的数组初始化等语法时可能出错。缓解：解析结果做自检，方法范围不能交叉、所有可执行行都应被某个单元覆盖；自检不过的文件降级为文件级保留。
2. **继承覆盖高估**：方法未改，但它依赖的配置或数据变了。这一点方法级规则本身无法感知，界面上明确标注"继承"，由测试人员判断。

## 14. 测试计划

纯函数部分（parser / migrator / merger）用 pytest 表驱动覆盖：

- parser：普通方法、重载、构造器、内部类、匿名类、lambda、静态块、字段初始化、文本块、注解中的花括号
- migrator：第 4.4 节示例；方法上方插入行（偏移）；删除方法；新增方法；修改方法；重命名；文件删除；文件新增
- merger：exec 行优先；exec missed + 迁移 covered；sources 并集；幂等性
- 方向判断：init / same / forward / backward / diverged / 分支切换开新轮
- exec 层（需 jacococli，标记为集成测试）：两份同 commit exec merge 后分支数等于并集；改动一个类后，未改动类仍命中
- 警告解析：从 jacococli 输出中提取不一致的类名

集成验证（demo-webapp）：

1. runtime 采集 v1，操作页面若干功能 → 记录累积覆盖率
2. unittest 采集同一 commit → 覆盖率只增不减，sources 含两种来源，分支覆盖数为两者精确并集
3. 修改一个已覆盖的方法并在其上方插入几行，再 push → 重新部署 → runtime 采集（不操作页面）
4. 预期：被改方法清零并出现在"需回归方法"中；其他已覆盖方法保留且行号正确偏移；增量覆盖率按 v2 的 diff 重新计算
5. 操作被改的功能后再采集 → 该方法重新覆盖，从"需回归"中消除
6. 任务切换到另一分支后采集 → 自动开新一轮，旧轮次可只读查看

## 15. 实施分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 | `java_method_parser` + `ledger_migrator` + `ledger_merger` 纯函数和单测 | 单测通过 |
| P2 | commit 列表接口 + 触发时 checkout 指定 commit + 后端校验；`build_service` 增加 exec merge、按指定 class 出报告、不一致警告收集 | 选定 commit 后编译出的 class 与该 commit 一致；警告可解析 |
| P3 | 数据表与迁移、`LedgerService`、采集流水线接入（含分支切换开新轮） | 采集后自动生成和更新账本 |
| P4 | 账本接口 + 基于账本的增量覆盖率 | 接口返回符合第 10 节预期 |
| P5 | 前端：commit 下拉、累积卡片、来源着色、需回归方法、合并历史、新一轮 | 第 14 节集成验证全部通过 |

## 16. 决策记录

| # | 问题 | 决策 |
|---|---|---|
| 1 | 方法内只改注释是否清零该方法 | 清零。指纹不剥离注释 |
| 2 | 轮次边界 | 账本绑定分支，切换分支自动开新一轮，旧轮次只读保留；另保留手动"开始新一轮" |
| 3 | 运行时部署 commit 如何指定 | 不支持手填，只能从分支提交列表下拉选择；接口调用同样校验 sha 属于该分支 |
| 4 | 分支覆盖精度 | 用 `jacococli merge` 精确合并 exec；只有字节码变化类中的未改动方法走方法迁移（唯一近似，界面标注"继承"） |
