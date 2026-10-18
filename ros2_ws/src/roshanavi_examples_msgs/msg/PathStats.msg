# What a sink measured for one path (= one source node). Part of SinkStats.
string path               # header.frame_id: name of the source node
uint64 received           # messages received since the sink started
uint64 lost               # messages missing by sequence gaps since the sink started
float64 rate_hz           # received per second over the window
float32 latency_ms_mean   # (now - header.stamp) over the window; end to end when stamps are kept
float32 latency_ms_p50
float32 latency_ms_p95
float32 latency_ms_max
