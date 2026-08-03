# Load-parameterized equilibria

For load `d`, H2 solves `pm1 - d1 - ptie = 0` and
`pm2 - d2 + ptie = 0`, with `pb*=0`. The resulting `x*(d)` is stored in
`SUSTAINABILITY_CELLS.parquet`. Terminal errors in later stages must be formed
about this object, not the historical zero-load origin. Every feasible static
power-balance residual is required below `1e-8 pu`; representative Plant-A
state integration and native Plant-B DAE runs are saved separately.
