# Statistics of one topic over one window (same semantics as roshanavi/stats.py).
# Floats that may be undefined use NaN (= null), integers use -1.
string topic
string type
string status             # ok | unsupported | error
string error
float64 window_sec
float64 rate_window_sec   # span actually used (10 for rate_note extended)
string rate_note          # '' | extended | too_few
bool stale                # silent for max(3 x expected period, 1 s): rates are 0
string hz_basis           # source | receive
float64 hz
float64 hz_recv
float64 hz_source         # NaN = no source timestamps
float64 bytes_per_sec
float64 avg_size
float64 jitter_ms
float64 jitter_recv_ms
int64 dropped             # -1 = unknown
float64 drop_ratio        # NaN = unknown
float64 latency_ms        # NaN = unknown
uint64 total_count        # since the subscription was created
uint32 recent_count       # received in the last second
builtin_interfaces/Time last_seen   # wall clock of the last receive; 0 = never
EndpointStats[] endpoints
