// Fixture: publishes std_msgs/String (size bytes) or sensor_msgs/Image (width x height rgb8)
// on `topic` at `rate_hz`, `burst` messages per tick (a large burst overflows tiny trace
// buffers on purpose). Used by the tracing tests and benchmarks (C++ so that the
// rclcpp tracepoints exist on the publisher side too).
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/string.hpp"

class RateTalker : public rclcpp::Node {
public:
  RateTalker() : Node("rate_talker") {
    const auto topic = declare_parameter<std::string>("topic", "chatter");
    const double rate = declare_parameter<double>("rate_hz", 10.0);
    const auto kind = declare_parameter<std::string>("type", "string");
    const auto size = declare_parameter<int>("size", 64);
    const auto width = declare_parameter<int>("width", 1280);
    const auto height = declare_parameter<int>("height", 720);
    burst_ = std::max<int64_t>(1, declare_parameter<int>("burst", 1));
    const auto period = std::chrono::duration<double>(1.0 / (rate > 0.0 ? rate : 1.0));
    if (kind == "image") {
      image_.width = static_cast<uint32_t>(width);
      image_.height = static_cast<uint32_t>(height);
      image_.encoding = "rgb8";
      image_.step = image_.width * 3;
      image_.data.assign(static_cast<size_t>(image_.step) * image_.height, 128);
      image_pub_ = create_publisher<sensor_msgs::msg::Image>(topic, 10);
    } else {
      text_.data.assign(static_cast<size_t>(size > 0 ? size : 1), 'x');
      text_pub_ = create_publisher<std_msgs::msg::String>(topic, 10);
    }
    timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(period), [this]() { tick(); });
  }

private:
  void tick() {
    for (int64_t i = 0; i < burst_; ++i) {
      if (image_pub_) {
        image_.header.stamp = now();
        image_pub_->publish(image_);
      } else {
        text_pub_->publish(text_);
      }
    }
  }

  int64_t burst_{1};
  std_msgs::msg::String text_;
  sensor_msgs::msg::Image image_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr text_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<RateTalker>());
  rclcpp::shutdown();
  return 0;
}
