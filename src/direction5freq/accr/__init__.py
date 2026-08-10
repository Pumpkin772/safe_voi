"""Direction5 ACCR-MPC implementation.

Keep package initialization intentionally empty.  In particular, the resource
guard must be importable without preloading NumPy, CVXPY, controller models, or
the native plant stack before it establishes OS-level limits.
"""

__all__: list[str] = []
