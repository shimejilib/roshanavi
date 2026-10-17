// Which node published a gid, per topic, and when that answer must be fetched again.
//
// Asking the graph (get_publishers_info_by_topic) for every topic every second is the
// expensive part of a tick on large systems, so the table is rebuilt only when
//   - the graph changed since the last successful lookup (the node's graph event),
//   - a gid shows up in the samples that the last lookup did not know (and has not already
//     failed to resolve: a publisher that is not in the graph is asked about once, not
//     every second), or
//   - kFallbackSec passed (cheap insurance should an event ever be missed).
// No ROS dependency: time and graph answers are passed in.
#ifndef ROSHANAVI_PROBE__PUBLISHER_DIRECTORY_HPP_
#define ROSHANAVI_PROBE__PUBLISHER_DIRECTORY_HPP_

#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "roshanavi_probe/stats.hpp"

namespace roshanavi_probe
{

constexpr double kDirectoryFallbackSec = 5.0;

/// Who published a gid (from get_publishers_info_by_topic).
struct EndpointName
{
  std::string node_name;
  std::string node_namespace;
};

class PublisherDirectory
{
public:
  using Names = std::map<Gid, EndpointName>;

  /// The graph changed somewhere: the next needs_refresh() is true until update() succeeds.
  void mark_dirty() {dirty_ = true;}

  /// ``seen``: the gids that appear in the retained samples.
  bool needs_refresh(double now, const std::vector<Gid> & seen) const
  {
    if (!valid_ || dirty_ || now - refreshed_at_ >= kDirectoryFallbackSec) {
      return true;
    }
    for (const Gid & gid : seen) {
      if (names_.count(gid) == 0 && unresolved_.count(gid) == 0) {
        return true;
      }
    }
    return false;
  }

  /// A successful graph lookup. A failed one must not call this (the old table is kept and
  /// the lookup is retried on the next tick).
  void update(Names names, const std::vector<Gid> & seen, double now)
  {
    names_ = std::move(names);
    unresolved_.clear();
    for (const Gid & gid : seen) {
      if (names_.count(gid) == 0) {
        unresolved_.insert(gid);
      }
    }
    refreshed_at_ = now;
    valid_ = true;
    dirty_ = false;
  }

  const Names & names() const {return names_;}

private:
  Names names_;
  std::set<Gid> unresolved_;  // seen after the last lookup, but not in the graph
  double refreshed_at_ = 0.0;
  bool valid_ = false;  // a lookup succeeded at least once
  bool dirty_ = false;
};

}  // namespace roshanavi_probe

#endif  // ROSHANAVI_PROBE__PUBLISHER_DIRECTORY_HPP_
