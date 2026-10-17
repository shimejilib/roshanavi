// Conversion of computed statistics into roshanavi_msgs (NaN / -1 encode null).
#include <limits>
#include <map>
#include <vector>

#include "builtin_interfaces/msg/time.hpp"
#include "roshanavi_probe/probe_node.hpp"

namespace roshanavi_probe
{
namespace
{

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr int64_t kNsPerSec = 1000000000;

builtin_interfaces::msg::Time to_time(int64_t ns)
{
  builtin_interfaces::msg::Time t;
  if (ns > 0) {
    t.sec = static_cast<int32_t>(ns / kNsPerSec);
    t.nanosec = static_cast<uint32_t>(ns % kNsPerSec);
  }
  return t;
}

const char * note_name(RateNote note)
{
  switch (note) {
    case RateNote::kExtended:
      return "extended";
    case RateNote::kTooFew:
      return "too_few";
    case RateNote::kNone:
    default:
      return "";
  }
}

roshanavi_msgs::msg::EndpointStats endpoint_msg(
  const EndpointResult & ep, const PublisherDirectory::Names & names)
{
  roshanavi_msgs::msg::EndpointStats out;
  out.publisher_gid = ep.gid;
  const auto it = names.find(ep.gid);
  out.resolved = it != names.end();
  if (out.resolved) {
    out.node_name = it->second.node_name;
    out.node_namespace = it->second.node_namespace;
  }
  const Rates & r = ep.result.rates;
  out.count = r.count;
  out.bytes = r.bytes;
  out.hz = r.hz;
  out.bps = r.bytes_per_sec;
  out.dropped = r.dropped.value_or(-1);
  out.rate_note = note_name(ep.result.note);
  out.stale = ep.result.stale;
  out.first_source_stamp = to_time(r.first_src_ns);
  out.last_source_stamp = to_time(r.last_src_ns);
  return out;
}

}  // namespace

void fill_topic_stats(
  const WindowResult & topic, const std::vector<EndpointResult> & endpoints,
  const PublisherDirectory::Names & names, roshanavi_msgs::msg::TopicStats & out)
{
  const Rates & r = topic.rates;
  out.window_sec = topic.window_sec;
  out.rate_window_sec = topic.rate_window_sec;
  out.rate_note = note_name(topic.note);
  out.stale = topic.stale;
  out.hz_basis = r.source_basis ? "source" : "receive";
  out.hz = r.hz;
  out.hz_recv = r.hz_recv;
  out.hz_source = r.hz_source.value_or(kNaN);
  out.bytes_per_sec = r.bytes_per_sec;
  out.avg_size = r.avg_size;
  out.jitter_ms = r.jitter_ms;
  out.jitter_recv_ms = r.jitter_recv_ms;
  out.dropped = r.dropped.value_or(-1);
  out.drop_ratio = r.drop_ratio.value_or(kNaN);
  out.latency_ms = r.latency_ms.value_or(kNaN);
  out.recent_count = topic.recent_count;
  out.endpoints.clear();
  out.endpoints.reserve(endpoints.size());
  for (const EndpointResult & ep : endpoints) {
    out.endpoints.push_back(endpoint_msg(ep, names));
  }
}

}  // namespace roshanavi_probe
