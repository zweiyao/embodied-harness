# holmes_RUA

[English](README.md) · [简体中文](README.zh-CN.md)

`holmes_RUA` is an embodied-agent research project built on [RPent](https://github.com/RLinf/RPent). It studies how repeated failures in multimodal interaction can become reusable experience and executable perception and decision tools, and evaluates their effects on task success, elapsed time, and token use.

The repository starts from a curated snapshot of upstream RPent `ef70215` and includes simulator and Flexiv integrations, a research workbench, and experiment analysis. Executable tools and individual successful runs do not establish effectiveness; improvements require controlled evaluation.

## Measured RPent results

**These are this project's evaluations using the RPent harness, not results from the RPent paper or demonstrated improvements from holmes_RUA.** Success follows the environment's official signal, rather than the model's completion claim. Batches with different suites, budgets, and network conditions are reported separately and do not establish a causal benefit from an optimization.

### GPT / Astra: LIBERO-Pro `libero_10_task`

Model `gpt-6-astra`, Codex planner, `reasoning_effort=low`; tasks 0–9, five runs each, 50 runs total. Each run allows 30 completed model responses and 600 seconds, with 17 native RPent tools and frozen experience `language-c592f23a3a324c08`. Infrastructure incidents are archived, excluded, and replaced with the corresponding rerun; timeouts and budget exhaustion count as failures.

| Task | Successes / valid runs | Success rate | Mean interactions | Mean elapsed (s) | Mean tokens | Total tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 5/5 | 100.0% | 14.0 | 163.4 | 565,809 | 2,829,046 |
| 1 | 5/5 | 100.0% | 17.4 | 207.8 | 808,469 | 4,042,344 |
| 2 | 4/5 | 80.0% | 22.2 | 216.5 | 1,296,358 | 6,481,792 |
| 3 | 2/5 | 40.0% | 23.8 | 334.8 | 1,386,704 | 6,933,519 |
| 4 | 1/5 | 20.0% | 29.4 | 274.9 | 1,841,347 | 9,206,737 |
| 5 | 5/5 | 100.0% | 11.4 | 107.1 | 418,977 | 2,094,886 |
| 6 | 4/5 | 80.0% | 22.4 | 217.8 | 1,158,476 | 5,792,379 |
| 7 | 5/5 | 100.0% | 17.2 | 154.2 | 766,096 | 3,830,481 |
| 8 | 4/5 | 80.0% | 17.6 | 181.4 | 817,257 | 4,086,287 |
| 9 | 0/5 | 0.0% | 30.0 | 282.3 | 2,060,328 | 10,301,639 |
| **Overall** | 35/50 | 70.0% | 20.5 | 214.0 | 1,111,982 | 55,599,110 |

### Qwen Flash: LIBERO-Pro `libero_10_task`

Model `qwen3.8-flash`, API planner, thinking disabled; tasks 0–9, five runs each, 50 runs total, with 30 model requests and the same native tools and frozen experience. **This batch mixes time budgets: 2/8 successes at 3000 seconds and 1/42 at 1500 seconds.** Earlier 600-second attempts are excluded. The combined result is a historical description, not a uniform-budget benchmark.

| Task | Successes / valid runs | Success rate | Mean interactions | Mean elapsed (s) | Mean tokens | Total tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 2/5 | 40.0% | 27.6 | 2333.1 | 833,850 | 4,169,248 |
| 1 | 0/5 | 0.0% | 27.8 | 2180.5 | 1,051,854 | 5,259,268 |
| 2 | 0/5 | 0.0% | 30.0 | 282.8 | 1,357,440 | 6,787,199 |
| 3 | 0/5 | 0.0% | 30.0 | 235.7 | 1,228,947 | 6,144,737 |
| 4 | 0/5 | 0.0% | 30.0 | 194.7 | 1,113,165 | 5,565,823 |
| 5 | 1/5 | 20.0% | 28.2 | 199.7 | 1,049,023 | 5,245,115 |
| 6 | 0/5 | 0.0% | 27.2 | 480.3 | 1,035,975 | 5,179,877 |
| 7 | 0/5 | 0.0% | 24.4 | 466.9 | 803,826 | 4,019,129 |
| 8 | 0/5 | 0.0% | 30.0 | 167.2 | 924,672 | 4,623,361 |
| 9 | 0/5 | 0.0% | 30.0 | 168.2 | 1,026,412 | 5,132,061 |
| **Overall** | 3/50 | 6.0% | 28.5 | 670.9 | 1,042,516 | 52,125,818 |

### Qwen Flash: interim Object-T results

LIBERO-Pro `libero_object_task`, model `qwen3.8-flash`, thinking disabled, original RPent prompts, frozen experience, and 17 native tools. Each run allows **50 model requests with no episode deadline**; model HTTP and environment / VLA / SAM3 RPC timeouts are disabled. The native simulator action budget remains enabled. Networking uses remote IPv4 direct access.

The **2026-11-13 data audit** includes **44/50** settled, unique task / seed cells, with 39 successes. All five pre-switch samples are excluded; four have IPv4 replacements. Tasks 1, 8, and 9 remain incomplete, and pending runs are not failures. **88.6% is an interim rate among completed runs, not the final 50-run score.**

| Task | Successes / valid runs | Success rate | Mean interactions | Mean elapsed (s) | Mean tokens | Total tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 5/5 | 100.0% | 18.2 | 603.9 | 452,810 | 2,264,051 |
| 1 | 4/4 | 100.0% | 20.0 | 1107.7 | 550,527 | 2,202,109 |
| 2 | 5/5 | 100.0% | 12.6 | 80.7 | 297,266 | 1,486,328 |
| 3 | 5/5 | 100.0% | 15.4 | 97.1 | 404,372 | 2,021,861 |
| 4 | 3/5 | 60.0% | 39.4 | 371.7 | 1,557,204 | 7,786,020 |
| 5 | 5/5 | 100.0% | 25.8 | 196.7 | 830,491 | 4,152,455 |
| 6 | 2/5 | 40.0% | 43.8 | 433.7 | 1,840,018 | 9,200,092 |
| 7 | 5/5 | 100.0% | 19.0 | 141.6 | 584,392 | 2,921,961 |
| 8 | 3/3 | 100.0% | 14.0 | 82.8 | 314,116 | 942,347 |
| 9 | 2/2 | 100.0% | 27.5 | 212.6 | 917,606 | 1,835,211 |
| **Overall** | 39/44 | 88.6% | 23.8 | 334.8 | 791,192 | 34,812,435 |

Interactions follow each adapter’s archived counter: completed model responses for Codex/Astra, and model requests for the Qwen API planner, including valid failed runs. These counters have different definitions and are not physical action counts. Mean elapsed time includes successes and valid failures. Tokens are API-reported input plus output; cached input is already included in input and is not added again. See the [result snapshot](validation/holmes-rua-homepage-20261113/results.json) for conditions, compact per-run records, source hashes, and the exact `checked_at` timestamp.

## Use and development

| Entry | Contents |
| --- | --- |
| [Quick start](docs/source-en/rst_source/get_started/quickstart.rst) | Environment setup, assets, checkpoints, and a first task |
| [Research workbench](docs/manual-workbench/README.md) | Model configuration, tool selection, experiment history, and playback |
| [LIBERO guide](docs/source-en/rst_source/simulators/libero.rst) | Installation, simulator assets, tasks, and evaluation |
| [UniVTAC](robots/univtac/README.md) / [Flexiv](robots/flexiv/README.md) | Deployment requirements and limits for each environment |
| [RoboDojo](docs/source-en/rst_source/simulators/robodojo.rst) / [RoboCasa](docs/source-en/rst_source/simulators/robocasa.rst) / [RoboTwin](docs/source-en/rst_source/simulators/robotwin.rst) | Simulator integration guides; consult each guide for its support status |
| [Contributing](CONTRIBUTING.md) / [Tests](tests/README.md) | Development conventions, interfaces, and validation |

The project display name is `holmes_RUA`. The Python package, CLI command, and compatible configuration names remain `rpent`; the GitHub repository remains `zweiyao/embodied-harness`. External hardware collectors, credentials, videos, raw observations, calibration data, and model weights are not distributed with the source.

## Upstream and license

This project builds on [RLinf/RPent](https://github.com/RLinf/RPent) under the [Apache-2.0 license](LICENSE), retaining upstream attribution. Cite RPent and its Harness VLA work as follows:

```bibtex
@article{zhang2026harnessvla,
  title={Harness VLA: Steering Frozen VLAs into Reliable Manipulation Primitives via Memory-Guided Agents},
  author={Zhang, Yixian and Zhang, Huanming and Gao, Feng and Li, Xiao and Liu, Zhihao and Zhu, Chunyang and Qiu, Jiaxing and Yan, Yuchen and Liu, Jiyuan and Tang, Wenhao and Fang, Zhengru and Nie, Yi and Wei, Changxu and Wang, Yu and Ding, Wenbo and Yu, Chao},
  journal={arXiv preprint arXiv:2607.08448},
  year={2026},
  url={https://arxiv.org/abs/2607.08448}
}
```
