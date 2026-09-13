# Phase 46 Reconciliation Report (2026-09-14)

This document serves as the final report for the Phase 46 reconciliation project. We performed a full diff between the running local code (D:\Trading\Azalyst Bernd Skorupinski) and the GitHub repository (Azalyst-repo). We identified 20 discrepancies and reconciled them against the Master Reference PDF.

## Discrepancies and Resolutions

### Tier 1: Documentation and Comments (Safe)
- --all-strategies: Confirmed as a no-op that just logs a warning. The Master Reference incorrectly claims it runs all 4 strategies. Code comments updated.
- AGENTS.md, CLAUDE.md, and SKILL.md: Appended reconciliation findings and feature flags.

### Tier 2: Verification-only Cleanups (No Behavior Change)
- pply_zone_trailing: Confirmed as dead code (never called). Removed from BP_paper_trader.py.
- **Trend Rule**: Code uses 2x HL only for uptrends, 2x LH only for downtrends (asymmetric). This matches the Master Reference.
- **Stop Placement**: Code correctly implements two modes: distal-only for weekly/monthly, and distal - 33% for LTF/pattern. This resolves the contradiction in the Master Reference.

### Tier 3: Behavior Changes (A/B Measurement Flags)
The following changes were implemented as experimental feature flags (default OFF) to prevent unilateral behavior changes per GEMINI.md rules:

1. **BP_EXPLOSIVE_STRICT**: 
   - Issue: Code used >= 0.70, but Master Reference explicitly states > 0.70.
   - Resolution: Added flag to strictly enforce > 0.70.

2. **BP_COT_0_100**:
   - Issue: Code used 140x-20 formula, but on-screen frames show a 0-100 scale.
   - Resolution: Added flag to switch to 100 * (net - min) / (max - min) formula.

3. **BP_TYPE_LADDERS**:
   - Issue: Code used a flat 0.5R BE / 50% T2 partial for all trades. Master Reference dictates 4 type-specific ladders.
   - Resolution: Added flag to enforce type-specific ladders. Counter-trend trades now close 100% at T2 (2R).

4. **BP_RETAIL_CONTRARIAN**:
   - Issue: Repo code routed Forex and Crude Oil to non-commercials and commercials respectively. The local backup (Phase 43+) correctly uses Retailers (small specs) as a contrarian indicator based on the live corpus.
   - Resolution: Added flag to route Forex and CL=F to small specs with contrarian = True.

## Next Steps
1. Run A/B measurements using the goldtest\ab_paired.py script for each Tier 3 flag individually.
2. Confirm 0 rows differ when all flags are OFF.
3. If A/B tests improve out-of-sample metrics, turn flags ON by default in a future release.