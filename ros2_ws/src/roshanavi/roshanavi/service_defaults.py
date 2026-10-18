"""Deadline for calls to other nodes' services (kept free of rclpy so ``--help`` stays light)."""

# One answer deadline for every service client (parameters, lifecycle). A node's first answer after
# it starts, or any answer while the host is busy, can take longer than 2 s. Flag: --service-timeout.
DEFAULT_SERVICE_TIMEOUT_SEC = 5.0
