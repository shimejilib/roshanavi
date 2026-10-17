// Fixture: subscribes to `topic` (String or Image) and sleeps `sleep_ms` in every callback,
// so it processes fewer messages than are sent. Once a second it prints one JSON line
// {"count": n, "latency_us_avg": x} to stdout (latency = receive time - source timestamp,
// same host clock) for the benchmarks.
#include <chrono>
#include <cstdio>
#include <memory>
#include <string>
#include <thread>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/string.hpp"

class SlowListener : public rclcpp::Node {
public:
  SlowListener() : Node("slow_listener") {
    const auto topic = declare_parameter<std::string>("topic", "chatter");
    sleep_ms_ = declare_parameter<int>("sleep_ms", 0);
    const auto kind = declare_parameter<std::string>("type", "string");
    if (kind == "image") {
      image_sub_ = create_subscription<sensor_msgs::msg::Image>(
        topic, 10, [this](const sensor_msgs::msg::Image &, const rclcpp::MessageInfo & info) {
          on_message(info);
        });
    } else {
      text_sub_ = create_subscription<std_msgs::msg::String>(
        topic, 10, [this](const std_msgs::msg::String &, const rclcpp::MessageInfo & info) {
          on_message(info);
        });
    }
    report_ = create_wall_timer(std::chrono::seconds(1), [this]() { report(); });
  }

private:
  void on_message(const rclcpp::MessageInfo & info) {
    const auto & raw = info.get_rmw_message_info();
    const auto now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
    if (raw.source_timestamp > 0) {
      latency_sum_ns_ += static_cast<double>(now_ns - raw.source_timestamp);
      ++latency_n_;
    }
    ++count_;
    if (sleep_ms_ > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms_));
    }
  }

  void report() {
    const double avg_us = latency_n_ > 0 ? latency_sum_ns_ / latency_n_ / 1000.0 : -1.0;
    std::printf("{\"count\": %llu, \"latency_us_avg\": %.1f}\n",
                static_cast<unsigned long long>(count_), avg_us);
    std::fflush(stdout);
    latency_sum_ns_ = 0.0;
    latency_n_ = 0;
  }

  int sleep_ms_{0};
  unsigned long long count_{0};
  double latency_sum_ns_{0.0};
  unsigned long long latency_n_{0};
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr text_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_sub_;
  rclcpp::TimerBase::SharedPtr report_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<SlowListener>());
  rclcpp::shutdown();
  return 0;
}
