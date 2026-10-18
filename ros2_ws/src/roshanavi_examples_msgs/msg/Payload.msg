# One message of the roshanavi relay pipeline (source -> relay -> ... -> sink).
# Public, documented in docs/design/nodes.md ("中継パイプライン"). Any node may use it.
#
# header.stamp     When the source created the message. A relay with keep_stamp=true copies it
#                  from its input, so the sink's (now - stamp) is the end-to-end latency.
# header.frame_id  Name of the source node that created the message (the "path"). Relays keep it,
#                  so the sink can count per source.
std_msgs/Header header
# Counter of the source (0, 1, 2, ...). A gap seen by the sink means messages were lost.
uint32 seq
# Dummy bytes; only the size matters (parameter payload_bytes of source / relay).
uint8[] data
