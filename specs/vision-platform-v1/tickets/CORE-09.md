# CORE-09 ? ADB typed process results

Priority: P0

Status: TODO

Dependencies: None

## Scope
adb.py; adb_command.py; adb_key_code.py; adb_platform.py; tests

## Deliverables
Typed argv, exit code, timeout and explicit serial; raw exec compatibility.

## Acceptance
Nonzero without error text; warning on success; timeout; literal arguments; serial; start_app regression.

## Evidence
Record commit, executed commands, test counts, real/mock distinction and blockers. Follow ../SPEC.md; do not expand scope.
