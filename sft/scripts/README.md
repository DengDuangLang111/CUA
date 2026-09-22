# SFT scripts

| Folder | Responsibility |
|---|---|
| [data/](data/) | Build/verify/export orchestration, judge-sidecar streaming and dataset transfer |
| [train/](train/) | Non-archived Slurm training recipes, checkpoint selection and serial training driver |
| [train/archive/](train/archive/) | Historical serve, resume, smoke and training recipes |
| [eval/](eval/) | Parameterized evaluation chain, arm table and older evaluation drivers |
| [monitor/](monitor/) | SFT dashboard data generation and daemon mirror |
| [cluster/](cluster/) | GPU availability helpers |
| [archive/](archive/) | Superseded per-arm and per-campaign evaluation drivers |

These are versioned source files. Existing scripts may refer to the deployed flat WSL control directory or cluster paths; those remote locations have not moved. [Runtime mirror mapping](../../docs/RUNTIME_MIRRORS.md) separates repository ownership from deployment layout. Do not bulk-copy the new tree over a live runtime.

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
