// Sink: the end of a pipeline. Measures how long messages took from their stamp to here and how
// many arrived, per path (= per source node). Part of the relay pipeline sample, docs/design/nodes.md.
//
// Topics (relative names, remap them): inputs in, in_1, ... (num_inputs of them)
//                                      output ~/stats (roshanavi_examples_msgs/msg/SinkStats)
// Latency = receive time - header.stamp. With keep_stamp=true on every relay it is the end to
// end latency from the source; a relay with keep_stamp=false restarts the clock there.
//
// Parameters
//   num_inputs (int, 1)       how many input topics (read at start)
//   window_s (number, 5)      the rate and the latency statistics cover this many seconds
//   stats_period_s (number, 1) publish ~/stats this often (0 = do not publish)
//   log_period_s (number, 5)  log one line per path this often (0 = never)
//   max_samples (int, 50000)  most latency samples kept per path (bounds the memory)
//   queue_depth (int, 10)     QoS history depth (read at start)
//
// Runs as a composable node (plugin roshanavi_examples::PipelineSink) in a container and as
// the executable `pipeline_sink`.
#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
#include "roshanavi_examples_msgs/msg/payload.hpp"
#include "roshanavi_examples_msgs/msg/sink_stats.hpp"

#include "pipeline_common.hpp"
#include "roshanavi_examples/pipeline_logic.hpp"

namespace roshanavi_examples
{

using Payload = roshanavi_examples_msgs::msg::Payload;
using SinkStats = roshanavi_examples_msgs::msg::SinkStats;
using PathStats = roshanavi_examples_msgs::msg::PathStats;
namespace pl = roshanavi_examples::pipeline;

class PipelineSink : public rclcpp::Node
{
public:
  explicit PipelineSink(const rclcpp::NodeOptions & options)
  : Node("pipeline_sink", options)
  {
    const auto num_inputs = declare_parameter<int>("num_inputs", 1, pl::describe("number of input topics", true));
    window_sec_ = pl::declare_number(*this, "window_s", 5.0, "seconds the statistics cover");
    const auto stats_period = pl::declare_number(*this, "stats_period_s", 1.0, "publish ~/stats this often");
    const auto log_period = pl::declare_number(*this, "log_period_s", 5.0, "log this often (0 = never)");
    max_samples_ = static_cast<size_t>(pl::declare_number(*this, "max_samples", 50000.0, "latency samples kept per path"));
    const auto depth = declare_parameter<int>("queue_depth", 10, pl::describe("QoS history depth", true));
    if (num_inputs < 1 || depth < 1 || window_sec_ <= 0.0 || max_samples_ < 1) {
      throw std::invalid_argument("num_inputs, queue_depth, window_s and max_samples must be positive");
    }
    const rclcpp::QoS qos(static_cast<size_t>(depth));
    for (int i = 0; i < num_inputs; ++i) {
      subs_.push_back(create_subscription<Payload>(
        pl::endpoint_name("in", i), qos,
        [this](Payload::ConstSharedPtr msg) {on_message(*msg);}));
    }
    if (stats_period > 0.0) {
      stats_pub_ = create_publisher<SinkStats>("~/stats", rclcpp::QoS(10));
      stats_timer_ = create_wall_timer(
        std::chrono::duration<double>(stats_period), [this]() {publish_stats();});
    }
    if (log_period > 0.0) {
      log_timer_ = create_wall_timer(std::chrono::duration<double>(log_period), [this]() {log_stats();});
    }
    RCLCPP_INFO(get_logger(), "sink ready: %d input(s), window %.1f s", num_inputs, window_sec_);
  }

private:
  struct Path
  {
    explicit Path(double window, size_t max_samples)
    : latency(window, max_samples) {}
    pl::SeqTracker seq;
    pl::LatencyWindow latency;
  };

  void on_message(const Payload & msg)
  {
    const double latency_ms = (now() - rclcpp::Time(msg.header.stamp)).seconds() * 1000.0;
    auto it = paths_.find(msg.header.frame_id);
    if (it == paths_.end()) {
      it = paths_.emplace(msg.header.frame_id, Path(window_sec_, max_samples_)).first;
    }
    it->second.seq.add(msg.seq);
    it->second.latency.add(pl::steady_sec(), latency_ms);
  }

  SinkStats build_stats()
  {
    SinkStats out;
    out.header.stamp = now();
    out.sink = get_name();
    out.window_sec = window_sec_;
    const double t = pl::steady_sec();
    for (auto & [name, path] : paths_) {
      const auto s = path.latency.summarize(t);
      PathStats row;
      row.path = name;
      row.received = path.seq.received();
      row.lost = path.seq.lost();
      row.rate_hz = path.latency.rate_hz(t);
      row.latency_ms_mean = static_cast<float>(s.mean_ms);
      row.latency_ms_p50 = static_cast<float>(s.p50_ms);
      row.latency_ms_p95 = static_cast<float>(s.p95_ms);
      row.latency_ms_max = static_cast<float>(s.max_ms);
      out.paths.push_back(row);
    }
    return out;
  }

  void publish_stats() {stats_pub_->publish(build_stats());}

  void log_stats()
  {
    for (const auto & row : build_stats().paths) {
      RCLCPP_INFO(get_logger(),
        "path %s: %.1f Hz, latency p50 %.1f ms p95 %.1f ms max %.1f ms, received %lu, lost %lu",
        row.path.c_str(), row.rate_hz, row.latency_ms_p50, row.latency_ms_p95,
        row.latency_ms_max, static_cast<unsigned long>(row.received),  // NOLINT
        static_cast<unsigned long>(row.lost));  // NOLINT
    }
  }

  double window_sec_ = 5.0;
  size_t max_samples_ = 50000;
  std::map<std::string, Path> paths_;
  std::vector<rclcpp::Subscription<Payload>::SharedPtr> subs_;
  rclcpp::Publisher<SinkStats>::SharedPtr stats_pub_;
  rclcpp::TimerBase::SharedPtr stats_timer_;
  rclcpp::TimerBase::SharedPtr log_timer_;
};

}  // namespace roshanavi_examples

RCLCPP_COMPONENTS_REGISTER_NODE(roshanavi_examples::PipelineSink)
