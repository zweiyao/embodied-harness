# RoboDojo checkpoint and catalog preparation

The pinned, unmodified RLinf converter produced a new BF16 PyTorch checkpoint from the released JAX step 59999, using pi05_aloha (32 model action channels, horizon 50). Conversion ran on CPU. Original release parameters remain unchanged. The output is 7,233,650,408 bytes, with 812 BF16 tensors; conversion.json records the SHA-256 and projection shapes.

The release normalization file was copied byte-for-byte into the new output's assets/arx_x5_sim/norm_stats.json. The upstream converter looks beside the step directory for assets, while this release stores them inside step 59999, so the copy was performed separately without changing upstream code.

The actual pinned RLinf loader successfully loaded 3,353,433,872 model parameters on CPU using the existing RPent RoboDojo model preset. The load took 15.67 seconds. An explicit normalization path selected the release's 14-channel state/action statistics; the preset's default asset location differs from the release layout. The official PaliGemma tokenizer was fetched over the inherited direct network into an independent OpenPI cache and its SHA-256 recorded. No forward pass, GPU inference, planner request or task action was run.

Static task inventory found 54 task IDs and saved layouts for every task in each of the three release groups. Counts vary by task (30–75); this is resource inventory, not executed task coverage. Runtime language still comes from the initialized official description manager.

Weights, tokenizer, raw observations and videos remain outside Git. Dependency metadata conflicts recorded in stage-01 remain; this preparation does not establish complete Isaac/runtime compatibility or benchmark success. The default service launcher and unified workbench have not been deployed.
