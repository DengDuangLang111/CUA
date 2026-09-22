# CUA agent entry point

Read [CLAUDE.root.md](CLAUDE.root.md) once if it is not already in context; it contains the shared repository instructions and runtime/source boundaries. Do not maintain a second copy here.

Use [README.md](README.md) to find the document for the current task. Read relevant sections of large ledgers rather than loading every Markdown file.

For new model evaluations, use the named [evaluation commands](sft/docs/EVAL_AUTOMATION.md): `run_eval.py plan`, `doctor`, `run`, `status`, and `resume`. Select registered model/benchmark/panel IDs; do not invent another per-experiment launcher. Preserve existing live campaigns until a safe transition.

For a new completed SFT checkpoint, use the same guide's `prepare_model.py` source-host workflow for verified Tillicum → Klone transfer and a single recorded Slurm serving submission. Pin an exact checkpoint/step and an existing SSH master. The checked-in profile is an example, not current authentication/resource state. Register its ready service in the existing eval registry; do not create another model-specific transfer/serve script. For a user-provided held allocation, reuse `prepare_model.py serve-held` from the same guide; keep per-service GPU identity, port and capacity receipts.

Before launching or resuming any CUA evaluation, follow the [default evaluation workflow](sft/docs/TRAINING.md#default-evaluation-workflow): per-task trajectory-page generation is part of the requested eval by default. Use the [pipeline guide](sft/docs/TRAJECTORY_PIPELINE.md) and its fixed catalog. Reuse registered output roots; classify real eval (including small formal pilots) as `eval`, and new-feature debugging as `test`. Check/install the real hook and worker environment; documentation or a local helper alone does not enable it.

Prefer the smallest working change and existing utilities. Update an existing authoritative document before adding another overview or status file. Dated plans, reports and archived instructions are historical evidence, not live state or authorization to run their commands.

User preference: keep orchestration simple. Keep fixed per-service VM slots and a bounded host-local task queue; idle slots may claim unstarted tasks, without a dynamic load-balancing service or per-step load polling. Preserve configuration switches. New eval plans default to rendered trajectory results with verified post-export raw cleanup; explicit `keep` remains supported, and old plans are not retroactively changed.
