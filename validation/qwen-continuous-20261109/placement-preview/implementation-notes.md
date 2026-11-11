# Implementation review amendments

Before the first model screen, root approved displaying the computed region target as a C marker in the existing O/P/R preview. This uses the same geometry and image calibration; it changes no target or action. Its purpose is to let the model review the actual computed destination. The numeric result records the projected full-image pixel.

The first remote unit run passed 37 and failed 11. The failing synthetic fixture used a 1 cm pixel pitch, so a correct 3x3 planar patch exceeded the frozen 2 cm local spread check. The fixture is corrected to a finer image at the same field of view; production thresholds are unchanged. These are test-development failures, not task episodes.
