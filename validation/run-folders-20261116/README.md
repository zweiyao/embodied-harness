# Experiment record folders

The shared `/runs` page groups records into expandable environment and task
folders with counts. Task cards load on first expansion and keep their existing
detail URLs, instructions, metrics and video links. Records are newest first
within each task. LIBERO suites remain separate; missing task metadata is kept
in its own folder. Named task numbers follow the current startup catalog and
are displayed alongside stored task names. Each service still lists its own
configured run roots. No files are moved or reclassified on disk.

Remote validation (Python 3.11, existing cached Node.js added to the test PATH):

- Dashboard unit tests: 130 passed.
- Full unit suite: 2162 passed / 11 skipped in 74.96 seconds.
- All-files pre-commit: passed.
- EN/ZH Sphinx builds: `-W --keep-going`, both passed.
- Headless Chrome checks on ports 8094/8083/8092/8093: folder counts match
  APIs (81/12/255/59 records), expand/reopen does not duplicate cards, existing
  details and the return link work, and no page errors occur. Sample RoboDojo
  and LIBERO videos return HTTP 206 for range requests; the sampled Flexiv and
  UniVTAC records have no video. This is not a claim about every historical video.
- Desktop and 390px layouts checked; the expanded mobile RoboDojo task has no
  horizontal overflow. Rendered EN/ZH guide paragraphs retain the `/runs` code
  span without literal RST backticks. Mac access to the RoboDojo page returns 200.

The four frontend files were applied to the three live source roots after
checking original hashes and dry-running the patch. Independent legacy video
rendering is preserved. All six workbench PIDs are unchanged, with no restarts,
experiment launches, robot commands, networking changes or data migrations.

Detailed scripts, screenshots, original backups, deployment hashes and logs
remain outside Git in
`/home/zwy/work/embodied_harness/validation/run-folders-20261116/`.
The desktop browser integration was unavailable; live UI checks used an
isolated remote headless Chrome instance. Screenshots and raw run data are not
committed. This UI validation does not establish task success.
