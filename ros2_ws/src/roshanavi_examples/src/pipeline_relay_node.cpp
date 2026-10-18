// Relay: a pipeline stage that receives messages, "works" for a while and forwards them.
// Part of the relay pipeline sample (source -> relay -> ... -> sink), docs/design/nodes.md.
//
// Topics (relative names, remap them): inputs  in, in_1, in_2, ...   (num_inputs of them)
//                                      outputs out, out_1, out_2, ... (num_outputs of them)
// Type: roshanavi_examples_msgs/msg/Payload (header + uint8[] data)
//
// Parameters (all but the first two can be changed while running)
//   num_inputs (int, 1)        how many input topics (a "fan-in" stage has several)
//   num_outputs (int, 1)       how many output topics (a "fan-out" stage has several)
//   process_ms (number, 0)     time spent on every accepted message
//   process_mode (string, "busy")  "busy": burn CPU for process_ms; "sleep": sleep for it
//   payload_bytes (int, -1)    size of the output; -1 = pass the input bytes through, otherwise
//                              the output is exactly this many bytes (cut or zero-padded)
//   rate_limit_hz (number, 0)  publish at most this often; messages arriving sooner are dropped.
//                              0 = publish for every input
//   keep_stamp (bool, true)    true: copy header.stamp of the input (the sink then measures the
//                              latency from the source); false: stamp with the current time
//   drop_ratio (number, 0)     probability (0..1) of dropping an input at random
//   fanout (string, "all")     with several outputs: "all" = every output gets every message,
//                              "round_robin" = one output per message in turn (splits the load)
//   seed (int, 0)              seed of the random drops; 0 = derived from the node name
//   queue_depth (int, 10)      QoS history depth of all subscriptions and publishers
//   log_period_s (number, 0)   log the counters this often (0 = never)
//
// header.frame_id (the name of the source node) and seq are always carried over from the
// input, so the sink can tell the paths apart and count what was lost.
//
// Runs as a composable node (plugin roshanavi_examples::PipelineRelay) in a container and as
// the executable `pipeline_relay`.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
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

class PipelineRelay : public rclcpp::Node
{
public:
  explicit PipelineRelay(const rclcpp::NodeOptions & options)
  : Node("pipeline_relay", options), gate_(1)
  {
    const auto num_inputs = declare_count("num_inputs", 1, "number of input topics (in, in_1, ...); fixed while running");
    const auto num_outputs = declare_count("num_outputs", 1, "number of output topics (out, out_1, ...); fixed while running");
    process_ms_ = pl::declare_number(*this, "process_ms", 0.0, "time spent on every accepted message");
    drop_ratio_ = pl::declare_number(*this, "drop_ratio", 0.0, "probability (0..1) of dropping an input");
    rate_limit_hz_ = pl::declare_number(
      *this, "rate_limit_hz", 0.0, "publish at most this often (0 = every input)");
    payload_bytes_ = static_cast<int64_t>(pl::declare_number(
      *this, "payload_bytes", -1.0, "output size in bytes (-1 = pass the input through)"));
    keep_stamp_ = declare_parameter<bool>("keep_stamp", true, pl::describe("copy header.stamp of the input"));
    busy_ = declare_parameter<std::string>(
      "process_mode", "busy", pl::describe("busy (burn CPU) or sleep")) == "busy";
    const auto fanout = declare_parameter<std::string>(
      "fanout", "all", pl::describe("all or round_robin; fixed while running", true));
    const auto seed = static_cast<int64_t>(pl::declare_number(*this, "seed", 0.0, "0 = from the node name (read at start)"));
    const auto depth = declare_count("queue_depth", 10, "QoS history depth; fixed while running");
    const auto log_period = pl::declare_number(*this, "log_period_s", 0.0, "log the counters this often");

    const auto mode = pl::parse_fanout(fanout);
    if (!mode) {
      throw std::invalid_argument("fanout must be 'all' or 'round_robin', not '" + fanout + "'");
    }
    fanout_ = *mode;
    gate_ = pl::RelayGate(seed != 0 ? static_cast<uint64_t>(seed) : pl::seed_from_name(get_fully_qualified_name()));

    const rclcpp::QoS qos(static_cast<size_t>(depth));
    for (int i = 0; i < num_outputs; ++i) {
      pubs_.push_back(create_publisher<Payload>(pl::endpoint_name("out", i), qos));
    }
    for (int i = 0; i < num_inputs; ++i) {
      subs_.push_back(create_subscription<Payload>(
        pl::endpoint_name("in", i), qos,
        [this](Payload::ConstSharedPtr msg) {on_message(*msg);}));
    }
    param_cb_ = add_on_set_parameters_callback(
      [this](const std::vector<rclcpp::Parameter> & params) {return on_parameters(params);});
    if (log_period > 0.0) {
      log_timer_ = create_wall_timer(
        std::chrono::duration<double>(log_period), [this]() {log_counters();});
    }
    RCLCPP_INFO(get_logger(), "relay ready: %d input(s), %d output(s)", num_inputs, num_outputs);
  }

private:
  int declare_count(const std::string & name, int default_value, const std::string & doc)
  {
    const int value = declare_parameter<int>(name, default_value, pl::describe(doc, true));
    if (value < 1) {
      throw std::invalid_argument(name + " must be at least 1");
    }
    return value;
  }

  rcl_interfaces::msg::SetParametersResult on_parameters(const std::vector<rclcpp::Parameter> & params)
  {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = true;
    for (const auto & p : params) {
      const auto & n = p.get_name();
      const bool numeric = n == "process_ms" || n == "drop_ratio" || n == "rate_limit_hz" ||
        n == "payload_bytes";
      if (numeric && !pl::is_number(p)) {
        return reject(n + " must be a number");
      }
      if (n == "process_ms" && pl::number_of(p) < 0.0) {
        return reject("process_ms must be 0 or more");
      }
      if (n == "drop_ratio" && (pl::number_of(p) < 0.0 || pl::number_of(p) > 1.0)) {
        return reject("drop_ratio must be between 0 and 1");
      }
      if (n == "rate_limit_hz" && pl::number_of(p) < 0.0) {
        return reject("rate_limit_hz must be 0 or more");
      }
      if (n == "process_mode" && p.as_string() != "busy" && p.as_string() != "sleep") {
        return reject("process_mode must be busy or sleep");
      }
    }
    for (const auto & p : params) {
      const auto & n = p.get_name();
      if (n == "process_ms") {process_ms_ = pl::number_of(p);}
      if (n == "drop_ratio") {drop_ratio_ = pl::number_of(p);}
      if (n == "rate_limit_hz") {rate_limit_hz_ = pl::number_of(p);}
      if (n == "payload_bytes") {payload_bytes_ = static_cast<int64_t>(pl::number_of(p));}
      if (n == "keep_stamp") {keep_stamp_ = p.as_bool();}
      if (n == "process_mode") {busy_ = p.as_string() == "busy";}
    }
    return result;
  }

  static rcl_interfaces::msg::SetParametersResult reject(const std::string & reason)
  {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = false;
    result.reason = reason;
    return result;
  }

  void on_message(const Payload & in)
  {
    ++received_;
    switch (gate_.decide(pl::steady_sec(), drop_ratio_.load(), rate_limit_hz_.load())) {
      case pl::Verdict::kDropRandom:
        ++dropped_random_;
        return;
      case pl::Verdict::kDropRate:
        ++dropped_rate_;
        return;
      case pl::Verdict::kAccept:
        break;
    }
    work();
    const auto stamp = keep_stamp_.load() ? rclcpp::Time(in.header.stamp) : now();
    for (const auto index : selector_.next(fanout_, pubs_.size())) {
      auto out = std::make_unique<Payload>();
      out->header.stamp = stamp;
      out->header.frame_id = in.header.frame_id;
      out->seq = in.seq;
      out->data = pl::make_payload(in.data, payload_bytes_.load());
      pubs_[index]->publish(std::move(out));
      ++published_;
    }
  }

  void work() const
  {
    const double ms = process_ms_.load();
    if (ms <= 0.0) {
      return;
    }
    if (busy_.load()) {
      pl::spin_for_ms(ms);
    } else {
      std::this_thread::sleep_for(std::chrono::duration<double, std::milli>(ms));
    }
  }

  void log_counters()
  {
    RCLCPP_INFO(get_logger(), "received %lu, published %lu, dropped %lu (random) + %lu (rate limit)",
      received_.load(), published_.load(), dropped_random_.load(), dropped_rate_.load());
  }

  pl::RelayGate gate_;
  pl::FanoutSelector selector_;
  pl::FanoutMode fanout_ = pl::FanoutMode::kAll;
  std::vector<rclcpp::Publisher<Payload>::SharedPtr> pubs_;
  std::vector<rclcpp::Subscription<Payload>::SharedPtr> subs_;
  OnSetParametersCallbackHandle::SharedPtr param_cb_;
  rclcpp::TimerBase::SharedPtr log_timer_;
  std::atomic<double> process_ms_{0.0};
  std::atomic<double> drop_ratio_{0.0};
  std::atomic<double> rate_limit_hz_{0.0};
  std::atomic<int64_t> payload_bytes_{-1};
  std::atomic<bool> keep_stamp_{true};
  std::atomic<bool> busy_{true};
  std::atomic<uint64_t> received_{0};
  std::atomic<uint64_t> published_{0};
  std::atomic<uint64_t> dropped_random_{0};
  std::atomic<uint64_t> dropped_rate_{0};
};

}  // namespace roshanavi_examples

RCLCPP_COMPONENTS_REGISTER_NODE(roshanavi_examples::PipelineRelay)
