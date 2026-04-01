"""
Pipeline optimization package.

Canonical modules:
- ``dual_issue_pipeline``: Dual-issue superscalar pipeline merging (production).
  Use ``DualIssuePipelineMerger`` for all new work.
- ``hazard_resolution``: Hazard detection and resolution for single and dual-issue
  pipelines. ``DetectedHazard`` now supports cross-pipeline hazards via
  ``write_pipeline``/``read_pipeline`` fields.
- ``pipelining_optimization``: Pipeline stage insertion and timing.
"""
