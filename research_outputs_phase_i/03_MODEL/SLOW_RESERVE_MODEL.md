# Slow reserve

Slow reserve is an explicit two-area first-order state with registered power and
ramp bounds. It starts from zero, cannot jump at 60 s, and enters the grid power
balance only through its actual state. Bridge remaining time is decremented on
every physical step. `BRIDGE_CLOCK_TRACE.csv` is the executable audit.
