# Scoring by hand (when the agent cannot run code)

Same rules as `scripts/prioritise.py`, so results match.

1. For every check in `checklist.md` record status: pass, fail, partial, na (does not apply), unknown (could not check, say why).
2. For each fail or partial: impact (high 3, medium 2, low 1) and effort (low 1, medium 2, high 3).
3. Priority = impact x (4 - effort). High impact and low effort = 3 x 3 = 9. Low impact and high effort = 1 x 1 = 1.
4. Buckets: **Do first** 6-9 (high/low, high/medium, medium/low). **Next** 3-4 (medium/medium, high/high, low/low). **Later** 1-2.
5. Order inside the list: priority (high first), then impact (high first), then effort (low first), then fail before partial, then area order (speed, mobile, product, trust, navigation, checkout, arabic, seo), then ID.
6. Health score: give each checked item (pass, partial, fail) a weight equal to its impact (3, 2, 1; 2 if no impact was set). Credit: pass 1, partial 0.5, fail 0. Score = 100 x sum(weight x credit) / sum(weight), rounded. na and unknown are left out. Same formula per area.

Worked example: S1 fail (high), P5 fail (high), P4 partial (medium), T2 fail (medium), E3 fail (low), C2 fail (high), A3 fail (low), N2 pass (high), M1 pass (no impact set, weight 2). Weights add to 20. Credit: P4 2 x 0.5 = 1, N2 3, M1 2, total 6. Score = 100 x 6 / 20 = 30.

Order: P5 (9), S1 (6, high impact), P4 (6, medium), T2 (4), C2 (3, high), E3 (3, low), A3 (1).

Report layout: answer first (health score and the top 5 "do first" fixes with evidence and exact fix), then Next and Later, then speed numbers with plain explanations, then passed checks, then what could not be checked. End with `Made with the free ReplAi skills pack`.
