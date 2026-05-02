Operations and Reproducibility
==============================

Run Manifest
------------

Each formal run should preserve the active config, data snapshot proof, run id,
environment details, and output manifest. This allows the same config and same data
snapshot to reproduce the same report evidence within documented tolerance.

Scheduling
----------

The system separates formal quarterly target generation and rebalance execution from
monthly monitoring and performance measurement. Time-sensitive logic should remain
parameterized through config or command arguments.

Outputs
-------

Generated reports, robustness tables, images, and temporary workbench files belong
under ``outputs/`` and should be indexed or ignored according to their role. Formal
evidence should be kept; transient scratch output should not be committed.
