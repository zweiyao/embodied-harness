# Eliminated or narrowed claims
1. "All failures are network delay": false as universal explanation; 40 failures have budget_exhausted and median219.55s, many far below1500s.
2. "Back-projection systematically computes wrong XYZ": no supporting discrepancy across615 successful recorded calls; all match their world maps. Full camera calibration and semantic pixel correctness are not thereby proven.
3. "Tool schema errors alone explain poor success": false;21 failed episodes have zero tool-return errors; errors also occur in two successful episodes.
4. "The controller cannot reach requested positions only for Flash": unsupported; both models show residuals, and most Flash moves end within3cm. Contact/planning/target choice cannot be separated from these aggregate residuals alone.
5. "Pick tool success=false proves no object held": invalid diagnostic shortcut; this is a heuristic, not the benchmark predicate. Astra also has many such reports. Do not classify grasp ground truth from it alone.
6. "Task8 selected the wrong named pot from image left/right": not established. BDDL goal uses named moka_pot_1 while language uses relational left; camera/benchmark naming differs. Do not infer object identity from image position alone.
