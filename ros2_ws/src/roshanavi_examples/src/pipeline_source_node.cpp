// Source: the start of a pipeline. Publishes stamped messages at a fixed rate.
// Part of the relay pipeline sample (source -> relay -> ... -> sink), docs/design/nodes.md.
//
// Topics (relative names, remap them): outputs out, out_1, ... (num_outputs of them)
// Type: roshanavi_examples_msgs/msg/Payload. Every message gets header.stamp = now,
// header.frame_id = the node name (the "path" the sink reports) and a counting seq.
//
// Parameters
//   rate_hz (number, 10)      messages per second (changeable while running)
//   payload_bytes (int, 64)   size of data (changeable while running)
//   enabled (bool, true)      false pauses publishing (changeable while running)
//   count (int, 0)            stop after this many messages (0 = never; read at start)
//   num_outputs (int, 1)      how many output topics (read at start)
//   fanout (string, "all")    with several outputs: "all" or "round_robin" (read at start)
//   queue_depth (int, 10)     QoS history depth (read at start)
//
// Runs as a composable node (plugin roshanavi_examples::PipelineSource) in a container and as
// the executable `pipeline_source`.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
#include "roshanavi_examples_msgs/msg/payload.hpp"

#include "pipeline_common.hpp"
#include "roshanavi_examples/pipeline_logic.hpp"

namespace roshanavi_examples
{

using Payload = roshanavi_examples_msgs::msg::Payload;
namespace pl = roshanavi_examples::pipeline;

class PipelineSource : public rclcpp::Node
{
public:
  explicit PipelineSource(const rclcpp::NodeOptions & options)
  : Node("pipeline_source", options)
  {
    rate_hz_ = pl::declare_number(*this, "rate_hz", 10.0, "messages per second");
    payload_bytes_ = static_cast<int64_t>(pl::declare_number(*this, "payload_bytes", 64.0, "size of data in bytes"));
    enabled_ = declare_parameter<bool>("enabled", true, pl::describe("false pauses publishing"));
    max_count_ = static_cast<uint64_t>(pl::declare_number(*this, "count", 0.0, "stop after this many (0 = never)"));
    const auto num_outputs = declare_parameter<int>("num_outputs", 1, pl::describe("number of output topics", true));
    const auto fanout = declare_parameter<std::string>(
      "fanout", "all", pl::describe("all or round_robin", true));
    const auto depth = declare_parameter<int>("queue_depth", 10, pl::describe("QoS history depth", true));
    const auto mode = pl::parse_fanout(fanout);
    if (!mode) {
      throw std::invalid_argument("fanout must be 'all' or 'round_robin', not '" + fanout + "'");
    }
    if (num_outputs < 1 || depth < 1 || rate_hz_.load() <= 0.0) {
      throw std::invalid_argument("num_outputs, queue_depth and rate_hz must be positive");
    }
    fanout_ = *mode;
    const rclcpp::QoS qos(static_cast<size_t>(depth));
    for (int i = 0; i < num_outputs; ++i) {
      pubs_.push_back(create_publisher<Payload>(pl::endpoint_name("out", i), qos));
    }
    param_cb_ = add_on_set_parameters_callback(
      [this](const std::vector<rclcpp::Parameter> & params) {return on_parameters(params);});
    start_timer();
    RCLCPP_INFO(get_logger(), "source ready: %.1f Hz, %ld bytes, %d output(s)",
      rate_hz_.load(), static_cast<long>(payload_bytes_.load()), num_outputs);  // NOLINT
  }

private:
  rcl_interfaces::msg::SetParametersResult on_parameters(const std::vector<rclcpp::Parameter> & params)
  {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = true;
    for (const auto & p : params) {
      const auto & n = p.get_name();
      if ((n == "rate_hz" || n == "payload_bytes") && !pl::is_number(p)) {
        result.successful = false;
        result.reason = n + " must be a number";
      } else if (n == "rate_hz" && pl::number_of(p) <= 0.0) {
        result.successful = false;
        result.reason = "rate_hz must be positive (use enabled:=false to pause)";
      } else if (n == "payload_bytes" && pl::number_of(p) < 0.0) {
        result.successful = false;
        result.reason = "payload_bytes must be 0 or more";
      }
    }
    if (!result.successful) {
      return result;
    }
    for (const auto & p : params) {
      const auto & n = p.get_name();
      if (n == "rate_hz") {rate_hz_ = pl::number_of(p);}
      if (n == "payload_bytes") {payload_bytes_ = static_cast<int64_t>(pl::number_of(p));}
      if (n == "enabled") {enabled_ = p.as_bool();}
    }
    return result;
  }

  void start_timer()
  {
    timer_rate_hz_ = rate_hz_.load();
    timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / timer_rate_hz_), [this]() {tick();});
  }

  void tick()
  {
    if (rate_hz_.load() != timer_rate_hz_) {
      start_timer();  // the rate was changed: continue with the new period
      return;
    }
    if (!enabled_.load() || (max_count_ > 0 && seq_ >= max_count_)) {
      return;
    }
    const auto stamp = now();
    for (const auto index : selector_.next(fanout_, pubs_.size())) {
      auto msg = std::make_unique<Payload>();
      msg->header.stamp = stamp;
      msg->header.frame_id = get_name();
      msg->seq = static_cast<uint32_t>(seq_);
      msg->data.assign(static_cast<size_t>(payload_bytes_.load()), 0);
      pubs_[index]->publish(std::move(msg));
    }
    ++seq_;
  }

  pl::FanoutSelector selector_;
  pl::FanoutMode fanout_ = pl::FanoutMode::kAll;
  std::vector<rclcpp::Publisher<Payload>::SharedPtr> pubs_;
  rclcpp::TimerBase::SharedPtr timer_;
  OnSetParametersCallbackHandle::SharedPtr param_cb_;
  std::atomic<double> rate_hz_{10.0};
  std::atomic<int64_t> payload_bytes_{64};
  std::atomic<bool> enabled_{true};
  double timer_rate_hz_ = 0.0;
  uint64_t max_count_ = 0;
  uint64_t seq_ = 0;
};

}  // namespace roshanavi_examples

RCLCPP_COMPONENTS_REGISTER_NODE(roshanavi_examples::PipelineSource)
