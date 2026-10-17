// Pure sliding-window traffic statistics (no ROS dependency, time is passed in).
//
// Mirrors roshanavi/stats.py so the probe and the Python fallback agree:
// rates from source timestamps (per publisher, summed), receive-side rates,
// sequence-number gaps, the "stopped -> 0" rule and the slow-topic window
// extension. On top of that every publisher (gid) gets its own numbers.
#ifndef ROSHANAVI_PROBE__STATS_HPP_
#define ROSHANAVI_PROBE__STATS_HPP_

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <vector>

namespace roshanavi_probe
{

constexpr std::size_t kGidSize = 16;  // RMW_GID_STORAGE_SIZE in Jazzy
using Gid = std::array<uint8_t, kGidSize>;

constexpr double kStalePeriods = 3.0;
constexpr double kStaleMinSec = 1.0;
constexpr double kRecentSec = 1.0;
constexpr double kMaxWindowSec = 10.0;
constexpr std::size_t kMaxSamples = 20000;  // bounds memory for very high-rate topics

/// One received message. ``src_ns`` / ``recv_ns`` / ``seq`` are 0 when unsupported.
struct Sample
{
  double t = 0.0;        // monotonic receive time (s)
  uint64_t size = 0;     // serialized size (bytes)
  int64_t src_ns = 0;    // source timestamp
  int64_t recv_ns = 0;   // received timestamp
  uint64_t seq = 0;      // publication sequence number
  Gid gid{};             // publisher id
};

/// Rates over a set of samples (stats.compute_stats).
struct Rates
{
  double hz = 0.0;
  bool source_basis = false;           // hz from source timestamps (else receive times)
  double hz_recv = 0.0;
  std::optional<double> hz_source;
  double bytes_per_sec = 0.0;
  double avg_size = 0.0;
  double jitter_ms = 0.0;
  double jitter_recv_ms = 0.0;
  std::optional<int64_t> dropped;
  std::optional<double> drop_ratio;
  std::optional<double> latency_ms;
  uint64_t count = 0;
  uint64_t bytes = 0;
  int64_t first_src_ns = 0;
  int64_t last_src_ns = 0;
};

enum class RateNote { kNone, kExtended, kTooFew };

/// Rates for one window plus how they were obtained (stats.TopicStats.snapshot).
struct WindowResult
{
  Rates rates;
  double window_sec = 0.0;
  double rate_window_sec = 0.0;
  RateNote note = RateNote::kNone;
  bool stale = false;
  uint32_t recent_count = 0;
};

struct EndpointResult
{
  Gid gid{};
  WindowResult result;
};

Rates compute_stats(const std::vector<Sample> & samples);

/// True when nothing arrived for max(3 x mean receive interval, 1 s).
bool is_silent(const std::vector<Sample> & retained, double now);

/// Topic-level rates over ``window`` (falls back to ``max_window`` for slow topics).
WindowResult compute_window(
  const std::vector<Sample> & retained, double now, double window,
  double max_window = kMaxWindowSec);

/// Per-publisher rates: compute_window on each gid's own samples (first-seen order).
std::vector<EndpointResult> compute_endpoints(
  const std::vector<Sample> & retained, double now, double window,
  double max_window = kMaxWindowSec);

/// Ring buffer of the samples of one topic (the longest window, at most ``max_samples``).
class SampleBuffer
{
public:
  explicit SampleBuffer(double retain_sec = kMaxWindowSec, std::size_t max_samples = kMaxSamples);

  void record(const Sample & sample);
  /// Drops samples older than the retention; returns what is left (oldest first).
  std::vector<Sample> retained(double now);
  uint64_t total() const {return total_;}
  void set_retain(double retain_sec) {retain_sec_ = retain_sec;}

private:
  double retain_sec_;
  std::size_t max_samples_;
  std::deque<Sample> samples_;
  uint64_t total_ = 0;
};

}  // namespace roshanavi_probe

#endif  // ROSHANAVI_PROBE__STATS_HPP_
