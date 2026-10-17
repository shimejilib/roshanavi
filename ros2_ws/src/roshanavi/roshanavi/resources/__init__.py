"""Resource monitoring Lv1 (same host): CPU / memory / disk / network / GPU per process and
for the whole PC, node <-> process attribution, leak detection (docs/design/resources.md).

Read-only: nothing here signals, ptraces or captures packets. Only the current user's
processes are inspected unless the server runs as root (e.g. inside a container).
"""
