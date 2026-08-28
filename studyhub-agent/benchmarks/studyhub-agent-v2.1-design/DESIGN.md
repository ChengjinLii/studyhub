# StudyHub AgentBench v2.1 Expanded

This directory defines an independent successor to frozen AgentBench v2.0. It does not modify, read, or regenerate v2.0 Sealed assets.

The target is 360 Development tasks, two separately hidden 120-task Sealed splits, and 60 Calibration tasks. Development shifts weight toward Web, Memory, Recovery, routing, state transitions, cross-tool composition, long horizon, source conflict, and stop/cost behavior. Source-group and generator-lineage isolation are mandatory; template slot substitution is not accepted as independent coverage.

Only Development and Calibration candidates may pass through the tracked public builder. Sealed generation remains `NOT_RUN` and must occur in a separate hidden workspace after data, recipe, checkpoint, and promotion rules are frozen.

Current status: `DESIGN_READY_DATA_NOT_BUILT`. This is a pipeline contract, not a completed benchmark or model result.
