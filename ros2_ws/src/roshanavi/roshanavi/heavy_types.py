"""Message types that are costly to (de)serialize: images and point clouds.

Traffic monitoring subscribes to them only on explicit opt-in (DESIGN §4.3);
transform nodes only relay / delay / throttle / drop them (no field expressions).
"""

HEAVY_TYPES = (
    'sensor_msgs/msg/Image',
    'sensor_msgs/msg/CompressedImage',
    'sensor_msgs/msg/PointCloud2',
    'sensor_msgs/msg/PointCloud',
)


def full_type_name(type_name: str) -> str:
    """``pkg/Name`` -> ``pkg/msg/Name`` (``pkg/msg/Name`` is returned unchanged)."""
    parts = type_name.split('/')
    return f'{parts[0]}/msg/{parts[-1]}' if len(parts) == 2 else type_name


def is_heavy(type_name: str) -> bool:
    return full_type_name(type_name) in HEAVY_TYPES
