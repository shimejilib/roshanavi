# Statistics of one publisher (publisher_gid) of a topic over one window.
uint8[16] publisher_gid   # rmw_gid_t data (RMW_GID_STORAGE_SIZE is 16 in Jazzy and Lyrical)
bool resolved             # publisher_gid matched an endpoint_gid of get_publishers_info_by_topic
string node_name          # empty when not resolved
string node_namespace
uint64 count              # messages received in the rate window
uint64 bytes              # serialized bytes received in the rate window
float64 hz                # publish-side rate (source timestamps; receive times if unsupported)
float64 bps               # hz x mean serialized size
int64 dropped             # sequence-number gaps in the rate window; -1 = unknown
string rate_note          # '' | extended | too_few (as TopicStats)
bool stale                # this publisher went silent (rates are 0)
builtin_interfaces/Time first_source_stamp
builtin_interfaces/Time last_source_stamp
