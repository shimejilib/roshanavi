# probe -> roshanavi on /roshanavi/_probe/stats, once per second.
std_msgs/Header header
string instance           # copied from the accepted ProbeConfig
string rmw_implementation
float64 cpu_percent       # CPU of the probe process over the last period (100 = one core)
uint64 rss_bytes          # resident memory of the probe process
TopicStats[] topics       # one entry per (topic, window)
