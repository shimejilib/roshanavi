"""Relay pipeline from a spec JSON written by scripts/gen_pipeline.py (docs/design/nodes.md).

  ros2 launch roshanavi_examples pipeline.launch.py spec:=/examples/pipeline_medium/pipeline.json
  ... mode:=container [containers:=2] [container_type:=mt] [intra_process:=true]
"""
from roshanavi_examples.pipeline_launch import launch_description


def generate_launch_description():
    return launch_description()
