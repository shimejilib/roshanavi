// ProbeNode: config handling, raw subscriptions and the 1 s statistics timer.
#include "roshanavi_probe/probe_node.hpp"

#include <sys/resource.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <exception>
#include <fstream>
#include <iterator>
#include <limits>
#include <set>
#include <utility>

#include "rmw/rmw.h"
#include "rmw/types.h"

namespace roshanavi_probe
{
namespace
{

constexpr double kDefaultPeriodSec = 1.0;
constexpr std::size_t kSubscriptionDepth = 10;  // as the Python monitor (docs/design/map-and-traffic.md)
constexpr std::size_t kConfigDepth = 4;          // one latched sample per roshanavi instance
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

double steady_seconds()
{
  using std::chrono::duration;
  return duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

int64_t wall_ns()
{
  using std::chrono::duration_cast;
  using std::chrono::nanoseconds;
  return duration_cast<nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
}

double cpu_seconds()
{
  rusage usage{};
  if (getrusage(RUSAGE_SELF, &usage) != 0) {
    return 0.0;
  }
  const auto tv = [](const timeval & t) {return t.tv_sec + t.tv_usec / 1e6;};
  return tv(usage.ru_utime) + tv(usage.ru_stime);
}

uint64_t rss_bytes()
{
  std::ifstream statm("/proc/self/statm");
  uint64_t size_pages = 0;
  uint64_t resident_pages = 0;
  if (!(statm >> size_pages >> resident_pages)) {
    return 0;
  }
  return resident_pages * static_cast<uint64_t>(sysconf(_SC_PAGESIZE));
}

/// Statistics of a topic that is not subscribed (unsupported / error): rates are null.
void fill_unmeasured(roshanavi_msgs::msg::TopicStats & ts, double window)
{
  ts.window_sec = window;
  ts.rate_window_sec = window;
  ts.hz_basis = "receive";
  ts.hz_source = kNaN;
  ts.dropped = -1;
  ts.drop_ratio = kNaN;
  ts.latency_ms = kNaN;
}

void record(TopicState & state, const rclcpp::SerializedMessage & msg, const rclcpp::MessageInfo & info)
{
  const rmw_message_info_t & mi = info.get_rmw_message_info();
  Sample s;
  s.t = steady_seconds();
  s.size = msg.size();
  s.src_ns = mi.source_timestamp;
  s.recv_ns = mi.received_timestamp;
  s.seq = mi.publication_sequence_number == RMW_MESSAGE_INFO_SEQUENCE_NUMBER_UNSUPPORTED ?
    0 : mi.publication_sequence_number;
  std::copy(mi.publisher_gid.data, mi.publisher_gid.data + kGidSize, s.gid.begin());
  state.samples.record(s);
  state.last_seen_ns = wall_ns();
}

}  // namespace

ProbeNode::ProbeNode(const rclcpp::NodeOptions & options)
: rclcpp::Node("roshanavi_probe", options)
{
  instance_ = declare_parameter<std::string>("instance", "");
  exit_with_parent_ = declare_parameter<bool>("exit_with_parent", true);
  const double period = declare_parameter<double>("period_sec", kDefaultPeriodSec);
  parent_pid_ = static_cast<int>(getppid());
  last_cpu_sec_ = cpu_seconds();
  last_cpu_wall_ = steady_seconds();

  // No QoS event callbacks anywhere: they are not needed and only add wake-ups.
  rclcpp::SubscriptionOptions sub_options;
  sub_options.use_default_callbacks = false;
  config_sub_ = create_subscription<roshanavi_msgs::msg::ProbeConfig>(
    kConfigTopic, rclcpp::QoS(kConfigDepth).reliable().transient_local(),
    [this](const roshanavi_msgs::msg::ProbeConfig & msg) {on_config(msg);}, sub_options);
  rclcpp::PublisherOptions pub_options;
  pub_options.use_default_callbacks = false;
  stats_pub_ = create_publisher<roshanavi_msgs::msg::ProbeStats>(
    kStatsTopic, rclcpp::QoS(2).reliable().durability_volatile(), pub_options);
  // Created before the first tick, so a change made between ticks is never missed.
  graph_event_ = get_graph_event();
  timer_ = create_wall_timer(
    std::chrono::duration<double>(period > 0.0 ? period : kDefaultPeriodSec),
    [this]() {on_timer();});
  RCLCPP_INFO(
    get_logger(), "probe ready (instance '%s', rmw %s)", instance_.c_str(),
    rmw_get_implementation_identifier());
}

void ProbeNode::on_config(const roshanavi_msgs::msg::ProbeConfig & config)
{
  if (config.instance != instance_) {
    return;  // another roshanavi server on the same domain
  }
  std::vector<double> windows;
  std::copy_if(
    config.windows_sec.begin(), config.windows_sec.end(), std::back_inserter(windows),
    [](double w) {return w > 0.0;});
  if (!windows.empty()) {
    windows_sec_ = windows;
  }
  const double retain = *std::max_element(windows_sec_.begin(), windows_sec_.end());
  std::set<std::string> wanted;
  for (const auto & spec : config.topics) {
    wanted.insert(spec.topic);
    auto it = topics_.find(spec.topic);
    if (it != topics_.end() && it->second.type == spec.type &&
      it->second.best_effort == spec.best_effort)
    {
      continue;
    }
    MonitoredTopic entry;
    entry.type = spec.type;
    entry.best_effort = spec.best_effort;
    entry.state = std::make_shared<TopicState>(TopicState{SampleBuffer(retain), 0});
    if (it != topics_.end()) {
      topics_.erase(it);  // destroys the old subscription first
    }
    subscribe(spec.topic, entry);
    topics_.emplace(spec.topic, std::move(entry));
  }
  for (auto it = topics_.begin(); it != topics_.end(); ) {
    it = wanted.count(it->first) ? std::next(it) : topics_.erase(it);
  }
  for (auto & item : topics_) {
    item.second.state->samples.set_retain(retain);
  }
  RCLCPP_INFO(get_logger(), "monitoring %zu topics", topics_.size());
}

void ProbeNode::subscribe(const std::string & topic, MonitoredTopic & entry)
{
  rclcpp::QoS qos(kSubscriptionDepth);
  qos.durability_volatile();
  if (entry.best_effort) {
    qos.best_effort();
  } else {
    qos.reliable();
  }
  rclcpp::SubscriptionOptions options;
  options.use_default_callbacks = false;
  std::shared_ptr<TopicState> state = entry.state;  // no cycle: the state does not own the sub
  try {
    entry.subscription = create_generic_subscription(
      topic, entry.type, qos,
      [state](std::shared_ptr<const rclcpp::SerializedMessage> msg, const rclcpp::MessageInfo & info) {
        record(*state, *msg, info);
      },
      options);
  } catch (const std::exception & exc) {
    // Typically the type support library of the type is not installed / sourced.
    entry.status = "unsupported";
    entry.error = exc.what();
    RCLCPP_WARN(get_logger(), "cannot subscribe %s (%s): %s", topic.c_str(),
      entry.type.c_str(), exc.what());
  }
}

void ProbeNode::refresh_publishers(
  const std::string & topic, MonitoredTopic & entry, const std::vector<EndpointResult> & seen)
{
  std::vector<Gid> gids;
  gids.reserve(seen.size());
  for (const EndpointResult & ep : seen) {
    gids.push_back(ep.gid);
  }
  const double now = steady_seconds();
  if (!entry.publishers.needs_refresh(now, gids)) {
    return;
  }
  PublisherDirectory::Names names;
  try {
    for (const auto & info : get_publishers_info_by_topic(topic)) {
      Gid gid{};
      const auto & raw = info.endpoint_gid();
      std::copy(raw.begin(), raw.begin() + kGidSize, gid.begin());
      names[gid] = EndpointName{info.node_name(), info.node_namespace()};
    }
  } catch (const std::exception & exc) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000, "graph query for %s failed: %s",
      topic.c_str(), exc.what());
    return;  // keep the previous mapping; asked again on the next tick
  }
  entry.publishers.update(std::move(names), gids, now);
}

void ProbeNode::update_cpu(roshanavi_msgs::msg::ProbeStats & msg)
{
  const double cpu = cpu_seconds();
  const double wall = steady_seconds();
  const double elapsed = wall - last_cpu_wall_;
  msg.cpu_percent = elapsed > 0.0 ? (cpu - last_cpu_sec_) / elapsed * 100.0 : 0.0;
  last_cpu_sec_ = cpu;
  last_cpu_wall_ = wall;
  msg.rss_bytes = rss_bytes();
}

void ProbeNode::on_timer()
{
  if (exit_with_parent_ && static_cast<int>(getppid()) != parent_pid_) {
    RCLCPP_WARN(get_logger(), "parent process exited; shutting down");
    rclcpp::shutdown();
    return;
  }
  const double now = steady_seconds();
  const double max_window = *std::max_element(windows_sec_.begin(), windows_sec_.end());
  const bool graph_changed = graph_event_->check_and_clear();
  roshanavi_msgs::msg::ProbeStats msg;
  msg.header.stamp = get_clock()->now();
  msg.instance = instance_;
  msg.rmw_implementation = rmw_get_implementation_identifier();
  update_cpu(msg);
  for (auto & [topic, entry] : topics_) {
    std::vector<WindowStats> computed;
    if (entry.status == "ok") {
      // One pass over the samples serves every window.
      computed = calculator_.compute(
        entry.state->samples.retained(now), now, windows_sec_, max_window);
      if (graph_changed) {
        entry.publishers.mark_dirty();
      }
      refresh_publishers(topic, entry, computed.front().endpoints);
    }
    for (std::size_t w = 0; w < windows_sec_.size(); ++w) {
      roshanavi_msgs::msg::TopicStats ts;
      ts.topic = topic;
      ts.type = entry.type;
      ts.status = entry.status;
      ts.error = entry.error;
      ts.total_count = entry.state->samples.total();
      ts.last_seen.sec = static_cast<int32_t>(entry.state->last_seen_ns / 1000000000);
      ts.last_seen.nanosec = static_cast<uint32_t>(entry.state->last_seen_ns % 1000000000);
      if (entry.status == "ok") {
        fill_topic_stats(
          computed[w].topic, computed[w].endpoints, entry.publishers.names(), ts);
      } else {
        fill_unmeasured(ts, windows_sec_[w]);
      }
      msg.topics.push_back(std::move(ts));
    }
  }
  stats_pub_->publish(msg);
}

}  // namespace roshanavi_probe
