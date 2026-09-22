# Reusable evaluation commands

This is the operational guide for [`run_eval.py`](../scripts/eval/run_eval.py).
It supports the registered **OSWorld Verified** and **OSWorld2** native runners.
The implementation uses Python's standard library, SSH, Docker, and the existing
[capture and trajectory pipeline](TRAJECTORY_PIPELINE.md). It does not use an LLM
to choose models, assign tasks, summarize results, or recover errors.

## 从 SFT 到评测：复用入口

更新：2026-09-16。本文是部署和评测的统一操作说明。**本地新增的准备脚本已通过
12 项离线测试（含2026-09-17的独立副本和就绪检查修复）；测试本身不代表真实评测已完成。**
实时运行状态看实际产物和 [实验账本](../../docs/EXPERIMENTS.md)；不要自动恢复用户暂停的任务。

```text
Tillicum：指定最终 checkpoint → prepare_model.py plan → prepare
    → 直接 rsync 到 Klone → 校验 → 发布模型目录 → 提交一个 Slurm 服务
    → prepare_model.py status：拿到 ready / node / port / eval_model
Mac：登记该模型 + 核对两台 WSL 的隧道/配额 → run_eval.py plan → doctor → run
Windows/WSL：每题 rollout → 原始记录 → evaluator 分数 → 自动后处理 → 统一轨迹 Index
```

### 一次配好的内容，与每个模型要改的内容

| 配置频率 | 内容 |
|---|---|
| 首次接入／代码更新时 | Tillicum 的 `prepare_model.py`；Klone 的容器、CUA 采集模块和私有 key 文件；两台 WSL 的 eval/export 工具、benchmark、viewer、Mac registry。修改 Mac 文件不等于这些副本已更新，部署后核对文件 hash |
| 每个新 checkpoint | 唯一 `model_id`、规范 `arm`、准确 checkpoint 路径、`expected_step`、显式 tokenizer/processor 备用目录 |
| 每次新 serving 作业 | GPU/TP/时限/并发等配置；确认可用端口；用实际返回的节点与端口连接 WSL。Slurm 节点不是永久固定值 |
| 每次 eval | 模型 ID、benchmark、任务清单/数量、协议、机器配额、`collection` 和 `raw_retention` |

### TMAX step306 → Verified100 示例

下面是**准备完成后的执行示例，不是已运行记录**。按顺序操作；路径占位符必须替换。

1. **确认最终模型。** 查本次续训真实输出目录，确认 `trainer_state.json` 的
   `global_step=306`、权重完整且保存已结束。不要用最大目录名推断完成状态。
   本轮训练配方和公平对照要求见 [TMAX 计划](../plans/PLAN-20260915-tmax9b-r5-cua-sft.md#6-最小实验矩阵与评测)。
2. **在 Tillicum 配置和准备服务。** 从 [配置示例](../scripts/serve/prepare_model.example.json)
   复制一份私有配置，填写实际路径；执行下文的 `prepare_model.py plan / prepare / status`。
   必须在拥有有效 Klone SSH master 的源主机执行。首次需把脚本复制到该主机。
3. **连接新服务。** 等 `status` 返回 `ready: true`，将它的 `eval_model` 登记到
   Mac registry 的 `models[model_id]`，按真实 `node:port` 设置每台 WSL 的 endpoint/隧道。
   本次评测的端点必须服务 **TMAX SFT 9B**，不能复用指向 27B teacher 的 URL。
4. **匹配并发和协议。** 示例服务 `max_num_seqs=2`，对应模型项
   `max_parallel_requests=2`。两机同时参与时，示例设置各 `slots=1`；**不能原样沿用
   2+6 配额**，当前脚本会拒绝所选主机槽位之和超出模型容量的计划。新建一份私有
   registry 配置副本设置这些值，保留旧计划及原来的机器配置。
   VM 槽位只控制并发数，不会自动增加 VM RAM。
5. **在 Mac 生成计划并启动。** 下面假设新 registry 副本已经完成以上配置。
   `prepare_model.py` 的单服务输出不带 `teachers` 列表，可以走普通 endpoint 路径；
   此时不调用只支持服务池登记的 `run_eval.py teachers`。

```bash
EVAL_SCRIPT=/Users/knight/uw/computeragent/CUA/sft/scripts/eval/run_eval.py
EVAL_REGISTRY=/Users/knight/uw/computeragent/cua-eval/registry.tmax9b-s306.json
MODEL_ID=tmax9b-full-r5-ml65k--train20260915--s306

# 此 registry 副本已配置新 9B endpoint，windows/workstation 各 1 个槽位。
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model "$MODEL_ID" --bench verified --tasks 100 \
  --hosts windows workstation --collection eval \
  --raw-retention delete-after-export

# 替换为 plan 命令返回的真实路径；不要手动改其中的模型、协议或配额。
EVAL_PLAN=/absolute/path/returned/by/plan/plan.json
python3 "$EVAL_SCRIPT" doctor --plan "$EVAL_PLAN"
# 所有检查 ready 后执行；doctor 是预检，不是一次真实截图评测。
python3 "$EVAL_SCRIPT" run --plan "$EVAL_PLAN"
python3 "$EVAL_SCRIPT" status --plan "$EVAL_PLAN"
```

6. **核对首题和最终结果。** 首题应有真实截图/动作、服务实际记录的输出和信号、
   evaluator 最终分数、导出验证报告，且进入已有正式 Index。
   元数据 ready 或 HTML 存在都不能代替这一检查。最后核对选题数、完成题数、缺失/异常题；
   0 分属于已完成结果，不自动重跑。正式入口沿用
   [统一轨迹 Index](http://127.0.0.1:8793/index.html?collection=eval)，并检查相应 viewer/转发在线。

比较旧 r5 时，两组冻结同一 Verified100 清单、harness、图像历史、thinking 开关和解码参数。
旧 `@20f10` 分数不能直接作为新 `@10f1` 的配对对照。训练的 `preserve_thinking` 不能替代
实际推理请求/模板验证。OSWorld2 是另一套任务和评测协议，单独创建计划、单独统计。

### 中断后从哪里继续

| 看到的状态 | 下一步 |
|---|---|
| SSH master 不存在／认证失效 | 在对应机器完成一次正常认证，核对 socket，再重试原命令；不要用脚本循环登录 |
| 传输未完成 | 用相同配置重跑 `prepare`，rsync 续传；校验失败前不会提交服务 |
| `PENDING` | 查已记录的 Slurm 作业和排队原因；不要重复 `sbatch` |
| `RUNNING`，但 `ready:false` | 查返回的错误和 `serve-<job_id>.log`；不启动 eval |
| `submission_started` 但没有 job ID | 按唯一 job name 核对 Slurm，确认是否提交成功再修正回执；不盲删 `job.json` |
| 服务作业失败／到时限 | `prepare` 不会自动续费式重提；核对原因，明确下一次部署配置和身份 |
| eval 中断 | 恢复依赖后对原 `plan.json` 执行 `run_eval.py resume --plan ...`；已有最终分数的题会跳过 |
| 分数已有，但页面处理失败 | 从保存的记录重做后处理，见 [轨迹管道](TRAJECTORY_PIPELINE.md)；不为修网页重新 rollout |

`delete-after-export` 仅在分数和导出验证通过后清理可替代的 **WSL 任务原始数据**；
图片、已渲染热力图、精确图片级统计和轨迹保留。`keep` 开关继续支持。
Klone 的清理需另行显式启用 `producer_cleanup`，只删已验证的 `.attn`；生产端 JSONL 元数据与 checkpoint 保留。配置和恢复见[生产端清理](TRAJECTORY_PIPELINE.md#producer-cleanup)。

## 1. What a name identifies

Keep three identities separate:

| Identity | Example | Meaning |
|---|---|---|
| Canonical arm | `tmax9b-full-r5-ml65k` | The model/data/training recipe, defined by `armname.py` |
| Registered model ID | `27b-base` | One fixed checkpoint, resolved through the registry |
| Unique evaluation run ID | `27b-base--osworld2--official108-n100--20260916T223112Z-a1b2c3d4e5f6` | One selected panel, protocol, host allocation, and execution history |

The run ID is generated automatically: model ID, benchmark, panel label, selected
task count, UTC timestamp, and a random suffix. Directory creation is exclusive;
an existing run is never overwritten. The program reads the frozen `plan.json`
rather than trying to reverse-engineer paths from a filename.

Model IDs are bound to a checkpoint path/revision in `state_dir/model-bindings/`.
Reusing the same ID for different weights is rejected. Checkpoint directories
must be immutable. The script checks the **server-reported checkpoint path**;
it does not independently hash all model weights over the network.

If two training runs have the same canonical arm, give their checkpoint bindings
different model IDs, for example `tmax9b-full-r5-ml65k--train20260915--s306`, and
set that entry's `arm` to `tmax9b-full-r5-ml65k`. The arm remains compatible with
the existing naming convention; the model ID makes the weight selection unique.

## 2. Current Mac setup

### Before evaluation: prepare a new SFT checkpoint on Klone

Use [`prepare_model.py`](../scripts/serve/prepare_model.py) for the source-host
part of the workflow. It replaces copying a serving script for every model.
It runs on **Tillicum**, where the checkpoint files exist, and transfers directly
to Klone using an **already authenticated SSH master**. Mac can invoke this
command through its existing Tillicum session; weights do not pass through Mac.
There are no login/reconnect loops and no automatic evaluation launch.

Start with [`prepare_model.example.json`](../scripts/serve/prepare_model.example.json).
Copy the standalone Python file and a private copy of this JSON to Tillicum once.
Replace `REPLACE_WITH_ACTUAL_RUN` with the saved final run directory, and verify
the source host's Klone socket, target container/tool/key paths and resource
profile. Historical `klone.sock` existed on **tillicum-login02**; its continued
availability is not assumed. Missing authentication stops preparation once.

The example targets TMAX r5 **step 306**, BF16, two L40S GPUs, TP2, eight hours,
two concurrent sequences and full output-token capture on head 0. These are
**editable example resources, not a measured 9B capacity guarantee or a live
reservation**. The port is an example too; reserve an unused role port before
submission. Capture omits `layers`, so the existing collector resolves the model's
last full-attention layer rather than copying the 27B layer number.

```bash
# Run on the source Tillicum host; paths below are your deployed copies.
PREP=/absolute/path/prepare_model.py
MODEL_CONFIG=/absolute/path/tmax9b-s306.json

# Validate the local checkpoint; print file hashes and the exact sbatch script.
# This hashes the weights, but makes no network calls or Slurm submissions.
python3 "$PREP" plan --config "$MODEL_CONFIG"

# Transfer, validate on Klone, publish the model directory, submit one service.
python3 "$PREP" prepare --config "$MODEL_CONFIG"

# One bounded query: pending/running, node, model identity and collector route.
# No generated model tokens, polling daemon or automatic resubmission.
python3 "$PREP" status --config "$MODEL_CONFIG"
```

Configuration responsibilities:

| Fields | Meaning |
|---|---|
| `model_id`, `arm` | Unique checkpoint/deployment binding and canonical training recipe |
| `checkpoint`, `expected_step` | Exact complete checkpoint; never choose the largest directory name automatically |
| `assets` | Explicit fallback for missing tokenizer/processor/template files; model weights and `config.json` must come from the checkpoint |
| `ssh_host`, `ssh_socket` | Source-host route using an existing authenticated Klone connection |
| `destination_root`, `container`, `tool_root`, `key_file`, `bind_root` | Klone deployment locations; key **contents** never enter the configuration |
| `slurm`, `serving` | Resources, duration, port, TP, context, concurrency, image limit and generation settings |
| `capture` | Existing collector options, or `false` for ordinary serving |

For the user's **three GPUs, three VMs per GPU** layout, set
`serving.replicas=3`, `serving.tensor_parallel=1`, `serving.max_num_seqs=3`, and
`slurm.gres="gpu:l40s:1"`. Resources in `slurm` are **per replica**. Preparation
submits three independent one-GPU Slurm jobs using the same verified model
directory; it does not copy the checkpoint three times or use TP=3. Ports are
`serving.port`, `port+1`, `port+2`. Each job has its own receipt and failure state.
Omitting `replicas` keeps the original single-service behavior.

Register those three ready endpoints as three entries in the existing `teachers`
service pool, each with `capacity=3`, all bound to this same 9B checkpoint.
Set model `max_parallel_requests=9`, workstation `slots=6`, Windows `slots=3`.
The static allocator gives each GPU two workstation tasks and one Windows task
in flight: three tasks per GPU, nine overall. Both hosts must pass preflight;
do not register the old 27B services as replicas of the new 9B model.

Preparation checks the recorded step, safetensors index/header/file completeness,
visual-weight presence, tokenizer and processor. It transfers only inference
weights/assets and available provenance JSON, **not optimizer/RNG/DeepSpeed
training states or the entire training output**. `rsync --partial --checksum`
can resume interrupted transfers. Every selected file is SHA-256 checked on
Klone; only then is the staging directory renamed to `model/` and submitted.
The source is checked again before publication to detect in-progress writes.
These checks do not certify training success or numerical/model quality.

Serving compilation caches are pinned to the job's node-local directory.
`XDG_CACHE_HOME` alone is insufficient: FlashInfer 0.6.13 defaults to HOME and may
follow a symlink into a busy/full GPFS cache. The generated script explicitly sets
`FLASHINFER_WORKSPACE_BASE` and `TRITON_CACHE_DIR`, including their `APPTAINERENV_`
overrides. On 2026-09-17 the first TMAX startup loaded its weights but blocked in
filesystem I/O while profiling; its FlashInfer log was on the shared Krishna
cache. That startup was cancelled and its receipt archived before retrying with
this fix. Existing shared caches and unrelated model services were not modified.

Artifacts live under `<destination_root>/<model_id>/`:

```text
deployment.json       Frozen configuration + per-file hashes and source paths
model/                Verified inference checkpoint/assets
serve.sbatch          Generated serving command; shared SIF used directly
capture.json          Collector settings, when enabled
capture-code.json     Hashes of the existing Klone collector modules
job.json              Submission receipt and job ID
serve-<job_id>.log     Slurm/vLLM log
capture-spool/        Server-side capture data, when enabled
```

For multiple replicas, `job.json` aggregates `services`; each replica also has
`job-r1.json` / `serve-r1.sbatch` (and r2/r3). `status` reports each job's node,
port and readiness, and overall `ready` requires all selected replicas to pass.

The same configuration reuses the recorded job instead of submitting again.
A changed binding is rejected; use a new ID for a changed deployment. Failed or
expired jobs are not automatically resubmitted. If SSH dies around `sbatch`,
`job.json` may say `submission_started` without an ID: inspect Slurm by the unique
job name and reconcile the receipt before retrying. Do not delete that receipt
and submit blindly. There is no `scancel`, process kill or cleanup of other runs.

`status` returns `ready: true` only after `/v1/models` matches the exact model ID,
checkpoint path and context, plus the collector route when capture is enabled.
This is **service metadata readiness**, not a successful real screenshot rollout.
On a fresh server the existing collector creates its artifact route on first
chat entry. If needed, status sends one request naming an explicitly unregistered
model, verifies its 404 rejection, then checks the route again. No real model is
used for this initialization and no GPU output tokens are generated. A missing
collector still fails readiness after that check.
It also returns `node`, `port`, `checkpoint`, and an `eval_model` registry fragment.
Register that fragment under `models[model_id]` in the existing Mac registry and
configure the selected Windows endpoints/tunnels to this reported node/port.
The helper deliberately does not guess host-specific Windows SSH paths or edit
the Mac registry from Tillicum. Then use the normal `plan → doctor → run` below.
Existing `run_eval.py` captured evaluations require a collector; `capture:false`
is for ordinary serving and does not automatically disable eval-side collection.

Local validation: `python3 -m unittest sft.tests.test_prepare_model -v` from the
CUA root. Twelve offline checks cover selected assets, truncated weights, checksums,
immutable bindings, repeated/uncertain submission, resumable transfer orchestration,
SSH-stdin execution, missing-master fail-fast, serving syntax, lazy-route readiness
and independent single-GPU replicas. Real deployment progress is recorded separately
in the experiment ledger; these offline checks do not run a full eval.

### Start evaluation from Mac

```bash
CUA_REPO=/Users/knight/uw/computeragent/CUA
EVAL_REGISTRY=/Users/knight/uw/computeragent/cua-eval/registry.json
EVAL_SCRIPT="$CUA_REPO/sft/scripts/eval/run_eval.py"
```

The registry is private deployment configuration. The checked-in
[`eval_registry.example.json`](../scripts/eval/eval_registry.example.json)
shows its schema and the verified deployment layout. Replace host paths and
connection details when using it on another machine. **Never put API keys or
passwords in this JSON**; `key_file` points to a private file on each WSL host.

The tool must be deployed to the `remote_command` path on each host, along with
the existing capture/export modules. Mac source edits do not update WSL copies.

## Teacher listing and simple task assignment

List the registered services without generating any model output:

```bash
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" teachers \
  --model 27b-base --hosts windows workstation
```

The script reads `/models` and `/metrics`, and checks the capture route with `OPTIONS`: checkpoint, context,
capture endpoint, running/queued requests and configured capacity. It does not
start a teacher, send a completion probe, run a balancing daemon, or continuously
poll load. The ordinary service on g3104 is listed but is not assigned captured
evals until its required collector is installed by the serving workflow.

New `plan` commands assign each task to one ready teacher and freeze that choice.
The two Windows hosts have fixed shares of each teacher's capacity, so neither
host can independently take all of its slots. With 2 + 6 VM slots and two teachers
limited to four requests each, Windows gets **1 + 1**, workstation **3 + 3**.
100 runnable tasks split approximately **50 + 50** between equal-capacity teachers.
If only one teacher is ready, fewer task workers run; it is not overfilled to use
all VM slots. Single-host plans retain that host's share rather than borrowing
the other host's slots. This also keeps separately created host plans bounded.

Each teacher has its own small task queue. A task stays on its assigned endpoint;
when it finishes, the next task in that queue starts. There is no in-task switching
or inference-time scheduling overhead. The existing pre-task identity check remains.
A failed teacher group pauses its queued tasks while the other group can continue.
If a teacher becomes unavailable after planning, doctor refuses that assignment;
create a new plan to redistribute, rather than silently changing the recorded run.
`teacher_slots`, `task_teachers` and `teacher_snapshot` are saved in the plan;
`execution.json` saves the teacher ID and URL for each attempt.

These bounds apply to evaluations launched through the same registry. Unrelated
clients can change server load after the startup snapshot; the serving process
still owns the GPU-level concurrency limit. Old frozen single-endpoint plans keep
their old routing until explicitly replaced. No running campaign is auto-migrated.

## 3. Normal commands

### Queued follow-up for this TMAX comparison (2026-09-17)

The user authorized **finishing the current 10/1 eval100, then evaluating the
same checkpoint and 100 tasks at 20/10**. The queue receipt is
`/Users/knight/uw/computeragent/cua-eval/queued-tmax-20f10.json`; it points to the
predecessor's immutable plan and `registry.tmax9b-s306-6gpu-20f10.json`.
The thread automation `tmax-9b-20f10` checks every ten minutes. It launches only
after both predecessor shards have every final score (including zero), both
controllers have exited and both run states are completed. It then uses the
same `plan`, `doctor`, `run` commands with 6+3 VMs and six verified 9B services, **after
the recorded serving readiness gate below passes**. Evaluation settings change only
image_max/fold_size; the lossless collector implementation upgrade is separately
recorded in provenance. A distinct run keeps the two protocols separate.

The receipt's `next_plan` and launch record prevent duplicate launches; a matching
existing plan is recovered if a previous check was interrupted. A stopped or
failed predecessor is reported rather than silently treated as complete. This
is a **Codex/Mac follow-up check**, not a Slurm dependency or a new remote queue
daemon: the check needs the host/app available to initiate the second run.
Once launched, remote eval controllers continue independently as usual. The
automation pauses itself after a confirmed launch. Do not restore the earlier
cancelled request to replace 10/1; the current authorization is a later, separate
20/10 comparison.

User override on 2026-09-17: the stalled Writer task `8472fece-c7dd-4241-8d65-9b3cd1a0b568` was explicitly stopped. Retain its trajectory with no fabricated score and do not retry it. The queue receipt records `predecessor_user_stop`: accept 99 scored tasks plus this one user-interrupted task after controller exit and safe artifact cleanup. This exception does not remove the task from the next 100-task 20/10 panel.

20/10 follow-up launched on 2026-09-17 at approximately 14:20 PT. The queue is `launched`; `next_plan` and `launch_receipt` identify the frozen 100-task run. Verified 6 active native tasks on Workstation and 3 on Windows. Do not recreate or re-dispatch this panel. See the dated entry in `docs/EXPERIMENTS.md` for the exact run ID.

### Current six-GPU serving and queued 20/10 (2026-09-17)

The user superseded the earlier next-round-only upgrade: **the current 10/fold1
run now uses the optimized image-key collector on six services**. The original
frozen plan, task assignments, checkpoint, protocol, results and VM states were
preserved. Operational routing is recorded separately in each run's
`service-routes.json`, `execution.json` and `maintenance-calls.json`.

| Consumer | Services | Per-service capacity |
|---|---|---:|
| Workstation, 6 VMs | 3 independent L40S replicas | 2 |
| Windows, 3 VMs | 3 independent A40 replicas in an existing held allocation | 1 |

Current registry: `cua-eval/registry.tmax9b-s306-6gpu.json`.
Next-round registry: `cua-eval/registry.tmax9b-s306-6gpu-20f10.json`.
Use `cua-eval/six-gpu-transition.json` and the serving base's `job.json` for exact
job IDs/nodes/ports; always recheck them. Old three-GPU registries are historical.
The next-run heartbeat remains ACTIVE, waits for all100 scores and postprocessing
completion, then reuses these six verified services for the same100 at20/fold10.
**Do not repeat the obsolete three-service upgrade or submit duplicate replicas.**

The current run keeps its original logical service-slot IDs so its frozen plan does
not change. `execution.json.service_id`, the routing revision, and recorded port
aliases identify the physical service. New plans use six distinct service IDs.
The next run starts only after both controllers exit completed; maintenance waits
are not an evaluation completion or a reason to restart tasks.

### Shared pending-task queue, fixed GPU slots (2026-09-17)

A service must not sit idle merely because its original task list finished first.
The controller now keeps one shared FIFO of unstarted tasks **within each host**.
The per-service worker count stays fixed: each L40S owns2 slots and each A40 owns1.
A free slot claims the next task; there is no per-step load polling or extra
scheduler daemon. Active tasks stay with their recorded service when a controller
is replaced, and scored tasks are skipped without rewriting scores. Host67/33
assignments, task IDs and eval/model settings stay unchanged.

The original frozen plan's `task_teachers` describes the historical planned
mapping; use task-state/execution.json for actual task-to-service assignment.
`dispatch.json` records `shared_host_queue` and the fixed slot limits. This fixed
an observed case where one A40 had finished11 tasks while13 tasks were still
waiting behind the other two. The same imbalance also left two L40S slots idle.
The updated controllers adopted existing native processes and filled those
slots; no active task was moved or started twice. Shared-queue/routing checks:
14/14 passed locally and on both WSL hosts.

### Reuse a held allocation and preserve active tasks

For an already verified/published checkpoint, run on Klone:

```bash
python3 /path/to/CUA/sft/scripts/serve/prepare_model.py serve-held \
  --config /path/to/held-allocation-profile.json
```

The full existing serving profile additionally sets `allocation_job`; its
`serving.replicas`, port and max_num_seqs set the requested services. This command
validates ownership, running state and resources, uses one Slurm step inside the
held allocation, and binds each replica to a distinct allocated GPU UUID. It
never submits another hold job, never cancels that allocation, and never repeats
an uncertain launch. The launcher records per-replica PID/GPU/port/step. Do not
assume Slurm's inherited CUDA_VISIBLE_DEVICES selects all allocated GPUs: this
cluster's task prolog initially selected one despite a three-GPU allocation.
Existing/new sbatch replicas retain the normal submit-once receipts. Service
records support explicit ports and per-replica max_num_seqs; capacities sum to9,
not six times the old default3.

For an active run, `service-routes.json` may override only known endpoints and
pause new dispatch for specified logical teachers; it must match plan_sha256.
It cannot change tasks, checkpoint or eval protocol. A replacement controller
can adopt exact recorded PID/boot/start-time identities and their descendants;
unrelated native processes still fail preflight. It does not launch a second
copy of an active task. Completed scores are reused and checked unchanged.

When replacing a live inference service, first prevent new dispatch to it. Use
the shared helper on the eval host, with the original plan and explicit teacher IDs:

```bash
python3 /path/to/CUA/sft/scripts/eval/maintenance.py pause \
  --plan /absolute/path/plan.json --host workstation --teachers <teacher-id>
# Single bounded check: pending means the model reply has not been saved yet.
# Do not restart the service until every old caller is safely paused or finished.
# After service/tunnel readiness and real capture verification:
python3 /path/to/CUA/sft/scripts/eval/maintenance.py resume \
  --plan /absolute/path/plan.json --host workstation --teachers <teacher-id>
```

The pause uses SIGSTOP only after a completed, saved model reply, then rechecks
the boundary to reject races. An old synchronous client may already have saved
the checksum-verified HTTP reply while still downloading attention. SIGCONT
continues the same process and VM; it is not restart-from-screenshot recovery.
Keep the durable pause receipt, verify readiness before resume, remove the
teacher's dispatch gate, and verify no PID is left stopped. Never pause inside
unfinished generation just to make a restart faster. Scored files and native
trajectories are preserved. This is a maintenance pause, not zero downtime.

During a switch, already captured artifacts remain on the shared Klone spool.
An available verified service can serve those identical bytes while a GPU
replica loads; persist every temporary port mapping and restore the intended
model endpoint before resuming its callers. Do not delete spool files during
handoff. Native processes loaded before the client optimization keep their
original sync download code until that task finishes; new tasks use background
downloads, and both read the new image-only storage format.

Evidence, tests and actual browser verification:
[SIX_GPU_IMAGE_CAPTURE_20260917.validation.json](../../reports/SIX_GPU_IMAGE_CAPTURE_20260917.validation.json).

### Create a plan; this does not start an eval

OSWorld2, first 100 IDs in the pinned official panel, using both machines:

```bash
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model 27b-base --bench osworld2 --tasks 100 \
  --hosts windows workstation
```

Verified, the fixed 100-task panel:

```bash
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model 27b-base --bench verified --tasks 100 \
  --hosts windows workstation
```

Use `--tasks all` for the complete registered panel. OSWorld2 currently contains
108 IDs; 036/037 are explicitly blocked pending proxy credentials. A selected
panel of 108 remains **108 selected, 106 runnable, 2 blocked**. The program does
not silently replace blocked IDs with other tasks or assign them zero scores.

For feature development, add `--collection test`. Small genuine evaluations
remain in the default `eval` collection. Task count does not determine the category.

The JSON response contains a full `plan` path. Use that exact path:

```bash
EVAL_PLAN=/absolute/path/from/the/plan/response/plan.json
python3 "$EVAL_SCRIPT" doctor --plan "$EVAL_PLAN"
python3 "$EVAL_SCRIPT" run --plan "$EVAL_PLAN"
python3 "$EVAL_SCRIPT" status --plan "$EVAL_PLAN"
```

`run` returns after launching remote controllers. Closing the Mac terminal does
not terminate their detached WSL processes. `status` reads their saved state;
it does not launch tasks. A controller PID alone is not proof of successful eval:
check task statuses, final scores, and the capture validation reports.

### Resume an interrupted run

```bash
python3 "$EVAL_SCRIPT" resume --plan "$EVAL_PLAN"
```

Use the same plan. Completed tasks, including **score 0**, are skipped. Interrupted
attempts remain intact and a fresh attempt gets a new directory. There are at
most **two attempts per task** in a plan. Exhausted failures remain visible in
`status`; they are not retried forever. If further attempts are explicitly needed,
create a new plan containing those task IDs and retain the old run as evidence.

Do not edit an existing plan to change model, tasks, protocol, hosts, or category.
Its SHA-256 is checked. Create a new plan instead. `run` and `resume` do not start a
second controller when the original controller is still alive.

### Use a specific task subset

```json
{"tasks": ["020", "024", "028"]}
```

Save that as `panel.json`, then:

```bash
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model 27b-base --bench osworld2 --hosts windows \
  --panel panel.json --panel-name recovery --tasks all
```

For Verified, use actual domains and UUIDs from its frozen panel. Every requested
ID must belong to the selected benchmark. Duplicate IDs and oversized counts are
rejected. Selection uses manifest order; there is no unrecorded random sampling.

### Choose raw-data retention when creating the plan

New plans default to `delete-after-export`; `--raw-retention keep` remains available.
The existing evaluation command owns this setting; no separate per-model export
script is needed. It is frozen in `plan.json`, copied to `inspection.json`, and
applied automatically by the normal task-completion worker.

```bash
# Permanent raw capture when explicitly needed.
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model 27b-base --bench osworld2 --tasks 108 \
  --hosts windows workstation --raw-retention keep

# Keep every token's rendered heatmaps + exact summary statistics and text;
# remove replaceable local raw files only after successful export validation.
python3 "$EVAL_SCRIPT" --registry "$EVAL_REGISTRY" plan \
  --model 27b-base --bench osworld2 --tasks 108 \
  --hosts windows workstation --raw-retention delete-after-export
```

Then use the same `doctor`, `run`, `status`, and `resume` commands as usual.
Existing frozen plans without this field mean `keep`. This option does not alter
model requests, benchmark scoring, task allocation, or the selected capture scope.

`delete-after-export` retains **all recorded token heatmaps**, both linear and log
scales, as 8-bit PNG intensity images packed per decision. It preserves exact
image-level mass/share/entropy, token diagnostics, mean-heatmap numbers, original
screenshots, actions, scores, and a compressed canonical request/response archive.
The viewer explicitly labels rendered-only data. Exact individual patch weights
and text-token attention cannot be recovered after deletion. Opacity, grid,
image selection, token selection, and both stored color scales remain available.

Cleanup requires a valid final score and a passed export check. Changed inputs,
missing/corrupt output files, or unconverted attention rows prevent deletion.
A durable receipt under `retention/` records hashes and narrowly scoped files;
interrupted cleanup can resume. `keep` does not continue a pending cleanup.
Cleanup also removes a duplicate wire-response file only when every original field is preserved in the canonical API response, and removes an unreferenced `recording.mp4`. Original screenshots, evaluator evidence and unrelated runs stay intact.
See [the pipeline retention contract](TRAJECTORY_PIPELINE.md#raw-retention).

This flag covers raw files in the task's evaluation directory on Windows/WSL.
The teacher server's separate capture spool is **not** deleted by this flag.
Raw data still needs temporary space until the task has finished and its export
has passed validation. Existing experiments are not automatically opted in.

## 4. Two Windows hosts and VM allocation

The current registered limits are **old Windows: 2 VM slots** and
**workstation: 6 VM slots**. The planner computes fixed quotas proportional to
those slots, using largest remainders for integer rounding. Ties follow the host
order in the command. Examples without excluded tasks:

| Selected tasks | Old Windows | Workstation |
|---:|---:|---:|
| 8 | 2 | 6 |
| 100 | 25 | 75 |

Each host processes its assigned IDs with at most its slot count in flight.
There are no overlapping shards. Exclusions are applied before allocating the
runnable tasks. The full selected set and excluded IDs remain in the plan.

This is a fixed split, not a distributed work-stealing system. If one host goes
offline, the other keeps its own tasks. The script does not move possibly still
running tasks to another host. Resume the original plan after recovery, or create
an explicit new subset after confirming which tasks are unfinished.

The model registration also limits total requested parallelism. The historical
27B registry allows eight total requested slots; this is not a capacity setting
to copy to a new 9B service. Set the selected host slots and service limits together.
A host-wide file lock,
native-runner process checks and Docker checks prevent overlapping campaigns.
Existing unlabelled OSWorld containers require an ownership check; the script
does not delete arbitrary containers to make room.

Disk checks cover both the WSL filesystem and configured `backing_drives`, such
as `/mnt/c`. This matters because a sparse WSL disk can report free space while
the underlying Windows drive is nearly full. Free space is checked again before
each task; low space blocks new work rather than deleting old evidence.

## 5. Teacher connections

The following is the recorded 27B route from 2026-09-16, not a permanent node
assignment or the route for a new TMAX service:

```text
Mac → SSH control commands to each Windows/WSL host

Workstation WSL 127.0.0.1:8102
  → existing authenticated Klone SSH master
  → teacher node g3122:8049

Old Windows WSL 127.0.0.1:8102
  → verified Tailscale SSH connection to workstation WSL
  → workstation 127.0.0.1:8102 → same teacher
```

Both hosts use the same registered checkpoint and service. Their model requests
do not pass through the Mac. The old Windows model route depends on the
workstation; the Mac's browser forwarding is separate from this inference route.

`doctor` reports benchmark, native CLI, Docker, disk, model identity and host-busy
checks. `run` can perform the registered `prepare_once` and `connect_once`
commands once when a connection is absent. These are argv lists, not shell
snippets. SSH is noninteractive, bounded, and uses trusted host keys. There is
no recursive login, repeated authentication loop, or automatic Duo approval.

The native `--help` check has a 120-second limit; doctor/start RPCs allow 180
seconds. The Windows venv on NTFS exceeded the former 30-second import limit
even when it was healthy. Other command/RPC limits remain unchanged. This only
changes startup validation timeouts, not model inference deadlines or retry counts.
On Windows, use the existing scheduled Docker Desktop task when starting it
remotely; a Desktop process relaunched directly by an SSH child can disappear
when that remote session ends. Verify Docker from WSL after the session returns.

The large `/openapi.json` response is read in addition to `/models`, because a
tiny health response previously passed while larger transfers stalled. The old
Windows profile includes the previously verified peer-specific MSS900 route.
Its gateway/interface must be rechecked if the network changes. The trusted
workstation host key now lives in `~/.ssh/cua_workstation_known_hosts`, not `/tmp`.

Model **serving** is prepared separately by `prepare_model.py`, as described above,
or an existing verified service. `run_eval.py` itself does not allocate GPUs,
replace an occupied model server, or change its attention implementation. Register a ready instrumented endpoint
once, then use the model ID for evaluations. A wrong checkpoint or insufficient
context causes a preflight failure before VMs are launched.

## 6. What to put in the registry

The registry has three required tables and an optional service-pool table:

- `models`: unique model ID → immutable checkpoint, canonical `arm`, endpoint
  name, context requirement and maximum concurrent requests.
- `benchmarks`: benchmark ID → native protocol, named panel, explicit exclusions,
  environment flags and bounded task timeout.
- `hosts`: SSH transport, deployed script location, VM slots, output roots,
  endpoint/key-file mappings, and pinned benchmark paths/commits/file hashes.
- `teachers`: optional named replicas and capacities, referenced by a model's
  `teachers` list. All replicas selected for that model must serve its bound
  checkpoint; the historical name does not mean a student eval uses teacher weights.

Example model entry for a completed SFT checkpoint (replace the placeholder):

```json
"tmax9b-full-r5-ml65k--train20260915--s306": {
  "arm": "tmax9b-full-r5-ml65k",
  "checkpoint": "/gscratch/cse/jy050706/sft/serving/tmax9b-full-r5-ml65k--train20260915--s306/model",
  "endpoint": "tmax9b-full-r5-ml65k--train20260915--s306",
  "precision": "BF16",
  "train_recipe": "r5; full SFT; 3 epochs; global batch 64; max_length 65536",
  "min_context": 262144,
  "max_parallel_requests": 2
}
```

This example matches the preparation profile's two-sequence limit. Set each
selected host to one slot if both participate. Each host then needs the matching
endpoint name (the local port below is an example, not an established tunnel):

```json
"tmax9b-full-r5-ml65k--train20260915--s306": {
  "url": "http://127.0.0.1:8104/v1",
  "key_file": "/home/your-user/.config/cua-v2/teacher_api_key"
}
```

That port must really serve the declared checkpoint. Add a verified one-shot
forward command only if needed; do not copy another model's node/port. API keys
are read at runtime and passed through the process environment, not saved in
`command.json`. Do not register an unfinished checkpoint as a completed model.

For a benchmark update, record the new checkout commit, the actual runner/agent
file hashes, and the exact panel file SHA-256 on each host. The planner rejects
hosts with different benchmark code or panel hashes. Preserve old plans for
reproducibility; updating the registry affects only new plans.

## 7. Failure isolation and output pipeline

```text
registry → frozen plan + unique run ID → preflight both selected hosts
  → one detached controller per host, bounded by VM slots
    → one native benchmark process per task attempt, num_envs=1
      → original model requests / responses / screenshots / actions / evaluator
      → ready record → graph/screenshots/scored Index preview
        → independent signal processing → validated heatmaps and raw details
```

A task exception kills only that task's native process tree. Other task processes
continue. A failed task without a score gets at most one new attempt. A valid final
score, including zero, ends retries. Shared Docker/model/disk failures stop new
dispatch on that host and leave actionable status; they do not start login loops.

**Attention transport (2026-09-17):** new standard runs use background downloads.
The model server persists full capture and returns the action plus artifact metadata.
The native task saves a durable download receipt and can execute the action immediately;
it does not wait for attention file transfer. Threads inside the existing page worker
use bounded download slots per host queue (default 1; currently 2), resumes partial downloads and verifies size/SHA.
Final visual-signal export waits for complete files; scored graph/screenshot previews remain
available while transfer is pending. This changes neither token coverage nor eval settings.
The server-side capture/compression cost still precedes the reply.

Use `capture.attention_download: "sync"` for synchronous compatibility. Keep the download
queue configured when switching back so previously queued files still drain. Preserve
`raw_retention: "keep"` / `"delete-after-export"` independently. Existing native tasks
keep their imported code/config; deployment takes effect at the next task boundary, without
restarting controllers, VMs, or model servers. See the pipeline guide's
[background download workflow and examples](TRAJECTORY_PIPELINE.md#attention-后台下载与正在运行的任务衔接2026-09-17)
for paths, per-teacher credentials, retry commands, live migration and rollback.

Page rendering runs in a **separate child process**, supervised by the controller.
On Linux that worker has a **4 GiB virtual-address-space limit** (`RLIMIT_AS`);
this limit applies to each export process, not the sum of all processes or VM/model memory. The worker indexes JSONL
by byte offset, processes one decision's signals at a time, and writes JSON
incrementally. Per-step signal files are loaded by the viewer on demand. Raw
requests, screenshots and every captured output token are preserved during processing; final raw-file removal follows the independently selected retention policy.

If rendering exceeds its limit, the ready record is marked `failed` with
`MemoryError`, or the controller records the worker exit in `export-error.json`.
The eval controller and native task processes continue; no model task is retried
because a page failed. See `export.log` and retry the saved raw task with
`after_task.py process-pending --config ... --retry-failed` after fixing the cause.
A crashed native task is reported as `interrupted` even if its last saved state
said `running`. This containment does not prevent unrelated host-wide OOMs or
application OOMs inside a VM.

The page worker first publishes a lightweight trajectory preview with explicit
`processing` status. Its preview thread also checks newly completed tasks while
heavy signal processing runs. Enrichment failures keep the graph/screenshots and
show a failure reason; they do not change the saved score. Per-step signals have
separate on-demand raw-detail files, and the browser retains at most two loaded
step records. The full publication contract is documented in
[TRAJECTORY_PIPELINE.md](TRAJECTORY_PIPELINE.md#页面与-visual-signal-的分阶段发布2026-09-16).

The startup hook adds `org.cua.run` and `org.cua.attempt` Docker labels. Cleanup
targets only the corresponding attempt label. The native benchmark's task
logic, action parser, score computation and screenshot retry policy are unchanged.

Each attempt is immutable and lives under its parent evaluation run:

```text
results_root/<unique-run-id>/
  plan.json                 # frozen model / panel / host / protocol contract
  controller.json, status.json, controller.log
  inspection.json, MODEL_BOUNDARY.json, args.json, version.json
  task-state/<task-hash>.json
  attempts/<task-hash>/attempt-01/
    task-panel.json, command.json, execution.json, runner.log
    .../<domain>/<task-id>/  # native results, capture, screenshots, attention
  attempts/<task-hash>/attempt-02/  # only if an unscored attempt failed
```

The inspection profile's `run_dir` groups all these attempts under one source run
in the existing viewer. Earlier failed attempts are retained, but the formal
Index and task navigation include only tasks with final scores. An exported page
does not by itself prove complete capture; inspect its validation report.

## 8. Verification and current deployment

Run the focused checks without launching GPUs or VMs:

```bash
python3 -m unittest sft.tests.test_run_eval -v
```

These exercise unique IDs, the 2 + 6 split, duplicate rejection, frozen-plan
integrity, real subprocess failure isolation, bounded attempts, preserving a
completed zero score on resume, shared-dependency failures, checkpoint mismatch,
and idempotent container labelling. The combined workflow/capture/viewer/catalog check completed **42 tests**. Both
real benchmark checkouts and panels were inspected. Verified CLI checks passed on
workstation; an old-Windows check exceeded its 30-second import timeout while
that host was busy. Doctor correctly refused another launch. No new Verified
rollout was started. The new OSWorld2 controller has been exercised on real VMs,
including actual model replies and matching attention/entropy rows; the full
21-task recovery is still in progress.

The old Windows recovery uses a user-level, one-shot Windows scheduled task named
`CUA-Docker-Recovery-20260916` to launch Docker Desktop in the existing desktop
session. It has no repeating trigger. This avoided tying Docker's lifetime to a
short SSH command. No workstation Docker/VM processes were stopped for that repair.

Live run status, current job IDs, and the exact recovery plan are recorded in
[EXPERIMENTS.md](../../docs/EXPERIMENTS.md), not inferred from this guide.

Current recovery plan: `/Users/knight/uw/computeragent/cua-eval/runs/27b-base--osworld2--remaining-windows-n21--20260916T223649Z-5cd2415b94cb/plan.json`. Use `status` or `resume` with this exact file; do not create a second copy of these tasks while its controller is alive.


## Postprocessing settings for the next evaluation

The existing `plan → doctor → run` workflow automatically starts `after_task.py process-pending`.
Add the following to each registry host; the standard controller copies `host.postprocess` into the
run's inspection configuration. No per-model exporter script is needed.

```json
"postprocess": {
  "export_workers": 2,
  "download_workers": 2,
  "resume_render": true
}
```

Use one export worker on the smaller Windows host. Defaults are one exporter, one downloader,
resume enabled, producer cleanup disabled. Keep `raw_retention: "keep"` or `"delete-after-export"`
as an independent plan choice. Optional `producer_cleanup` is checkpoint-specific; use the exact
SSH/spool example and dry-run procedure in the [pipeline guide](TRAJECTORY_PIPELINE.md#producer-cleanup).
The current TMAX six-GPU registries include the verified routes and settings; a different model must
use its own producer checkpoint/spool configuration.

For an active campaign, `pages/worker-options.json` provides a small postprocessing override without
editing the frozen evaluation plan. Safely transition only the page worker at a task boundary; native
runners, VMs and serving processes continue. The new worker drains in-flight exports on SIGTERM;
interrupted downloads preserve their partial files. Per-task locks, download locks and the existing
index publication lock prevent duplicate work. Do not roll back the deployed modules while the new
worker is using them. See [worker settings, switches and recovery](TRAJECTORY_PIPELINE.md#bounded-postprocessing).
