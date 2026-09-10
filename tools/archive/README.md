# tools/archive/ —— 一次性/已取代的驱动脚本(2026-09-09 归档)

这些文件是 WSL `/mnt/d/research/osworld-verified-control/`(`$CTL`)上实际运行过的
脚本的**版本化镜像**;仓库里的副本从不直接运行(见 `control/README.md`)。归档只是
把它们移出主目录,git 历史与内容都完整保留。

| 组 | 文件 | 为什么归档 |
|---|---|---|
| `run_eval50_*.sh`(16) | 每个臂一份的 eval-50 驱动(08-15 ~ 08-31) | 臂全部收官;机制被 `chain_eval_*.sh` 取代 |
| `chain_eval_*.sh`(9) | 每个 campaign 复制一份的 eval 链(rest/w20/w20f/w20g/lr/lr1e6/r5m/btf/cap1p5) | 九份两两只差 6–8 行(头注释 / LOG 路径 / 一行臂表);被参数化的 `tools/chain_eval.sh` + 臂表取代 |
| `tools_pilot_fold*.sh` `tools_pilot_status.sh` `tools_v11_reroll.sh`(8) | v11 时代的 fold 试点/重滚 | 试点结束,无引用(fold3–6/status 全库零引用) |

要重现某个历史 campaign:按当时的 `EXPERIMENTS.md` 现状块找到脚本名,到这里取。
