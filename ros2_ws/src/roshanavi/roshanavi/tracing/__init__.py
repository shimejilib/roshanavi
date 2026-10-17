"""詳細計測モード: per-node receive / process counts and callback times from ROS 2 tracepoints.

Layers (DESIGN §4.3.2): ``config`` (event names, buffer sizing), ``lttng`` (the
``lttng`` CLI and session daemon), ``reader`` (babeltrace2 chunk reader),
``model`` (pure handle mapping + windowed statistics), ``worker`` (child
process: rotation + parsing off the server's GIL), ``service`` (worker
lifecycle in the server) and ``merge`` (pure: trace results into traffic
entries, diagnostics, unsupported nodes).
"""
