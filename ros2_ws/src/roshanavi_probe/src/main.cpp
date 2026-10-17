// Entry point: ``ros2 run roshanavi_probe probe --ros-args -p instance:=<id>``.
// Normally started (and restarted) by the roshanavi server, not by hand.
//
// SingleThreadedExecutor: all callbacks (receive, config, 1 s timer) run on one
// thread, so the per-topic state needs no lock. The EventsExecutor was measured
// too (DESIGN 4.3.1): slightly less CPU for many small messages, about twice the
// CPU for 30 Hz images, so it is not used.
#include <cstdio>
#include <exception>
#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "roshanavi_probe/probe_node.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  int code = 0;
  try {
    rclcpp::spin(std::make_shared<roshanavi_probe::ProbeNode>());
  } catch (const std::exception & exc) {
    std::fprintf(stderr, "roshanavi_probe: %s\n", exc.what());
    code = 1;
  }
  rclcpp::shutdown();
  return code;
}
