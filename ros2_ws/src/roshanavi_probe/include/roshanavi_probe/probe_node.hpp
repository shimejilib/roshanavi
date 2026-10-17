// The roshanavi measurement probe: raw (serialized) subscriptions to the topics
// roshanavi asks for, per-publisher statistics published once per second.
#ifndef ROSHANAVI_PROBE__PROBE_NODE_HPP_
#define ROSHANAVI_PROBE__PROBE_NODE_HPP_

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "roshanavi_msgs/msg/probe_config.hpp"
#include "roshanavi_msgs/msg/probe_stats.hpp"
#include "roshanavi_probe/publisher_directory.hpp"
#include "roshanavi_probe/stats.hpp"

namespace roshanavi_probe
{

constexpr char kConfigTopic[] = "/roshanavi/_probe/config";
constexpr char kStatsTopic[] = "/roshanavi/_probe/stats";

/// What the subscription callback writes (shared between the callback and the timer;
/// both run on the single-threaded executor, so no lock is needed).
struct TopicState
{
  SampleBuffer samples;
  int64_t last_seen_ns = 0;  // wall clock of the last receive
};

/// One monitored topic.
struct MonitoredTopic
{
  std::string type;
  bool best_effort = false;
  std::string status = "ok";  // ok | unsupported | error
  std::string error;
  std::shared_ptr<TopicState> state;
  rclcpp::GenericSubscription::SharedPtr subscription;
  PublisherDirectory publishers;  // gid -> node, refreshed when the graph changes
};

class ProbeNode : public rclcpp::Node
{
public:
  explicit ProbeNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());

private:
  void on_config(const roshanavi_msgs::msg::ProbeConfig & config);
  void on_timer();
  void subscribe(const std::string & topic, MonitoredTopic & entry);
  /// Asks the graph who publishes ``topic`` if the directory says its table is out of date.
  void refresh_publishers(
    const std::string & topic, MonitoredTopic & entry, const std::vector<EndpointResult> & seen);
  void update_cpu(roshanavi_msgs::msg::ProbeStats & msg);

  std::string instance_;
  std::vector<double> windows_sec_{1.0, 5.0, 10.0};
  std::map<std::string, MonitoredTopic> topics_;
  rclcpp::Subscription<roshanavi_msgs::msg::ProbeConfig>::SharedPtr config_sub_;
  rclcpp::Publisher<roshanavi_msgs::msg::ProbeStats>::SharedPtr stats_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::Event::SharedPtr graph_event_;  // set whenever the ROS graph changes
  TopicCalculator calculator_;            // groups a topic's samples once per tick
  int parent_pid_ = 0;
  bool exit_with_parent_ = true;
  double last_cpu_sec_ = 0.0;
  double last_cpu_wall_ = 0.0;
};

/// Fills a TopicStats message from one window of computed statistics.
void fill_topic_stats(
  const WindowResult & topic, const std::vector<EndpointResult> & endpoints,
  const PublisherDirectory::Names & names, roshanavi_msgs::msg::TopicStats & out);

}  // namespace roshanavi_probe

#endif  // ROSHANAVI_PROBE__PROBE_NODE_HPP_
