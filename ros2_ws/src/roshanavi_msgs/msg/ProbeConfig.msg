# roshanavi -> probe on /roshanavi/_probe/config (reliable, transient local, depth 1).
# Each message replaces the whole set; topics missing from it are unsubscribed.
string instance       # the probe only accepts the config of its own roshanavi instance
float64[] windows_sec # averaging windows to report (e.g. 1, 5, 10)
ProbeTopic[] topics
