# Published by the pipeline sink (~/stats) every stats_period_s: one row per path (source).
std_msgs/Header header
string sink               # node name of the sink
float64 window_sec        # length of the window the rate / latency values cover
PathStats[] paths
