"""
The engine package imports, on its own, with nothing else installed.

WHY THIS EXISTS
    There is no engine code until Phase 4, but the claim the package makes —
    that it stands alone — is testable from the moment it exists. This is
    also what gives CI something to run against engine/ so the suite is wired
    up before it has anything substantial to check.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, whole file
    How:    Nothing. There were no tests.
    Wrong:  Traversal.Create_graph opened a database cursor inside the graph
            builder, so routing could not be exercised without a live SQLite
            file. Writing a test meant first building a database, which is a
            chore, so no test was ever written, so the aliasing bug at line
            532 destroyed the graph on every search for five years.

WHAT CHANGED AND WHY
    This file runs with no database, no server and no fixtures. That is the
    property the whole engine/ folder exists to preserve, and it is worth
    asserting from the first commit rather than from the first algorithm.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related. Phase 6
    adds tests/test_imports.py to enforce that mechanically.
"""

import tube_engine


def test_package_imports_and_reports_a_version() -> None:
    assert tube_engine.__version__ == "0.1.0"
