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
#include <memory>
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

/// Read-only view of samples ordered by receive time (non-decreasing ``t``): either a
/// contiguous run (``idx == nullptr``) or the samples ``base[idx[i]]`` (one publisher's
/// share of a run). Never copies a Sample; a view dies with the storage it points into.
class SampleSeq
{
public:
  SampleSeq() = default;
  SampleSeq(const std::vector<Sample> & v)  // NOLINT: a vector is a contiguous view
  : base_(v.data()), n_(v.size()) {}
  SampleSeq(const Sample * base, std::size_t n)
  : base_(base), n_(n) {}
  SampleSeq(const Sample * base, const uint32_t * idx, std::size_t n)
  : base_(base), idx_(idx), n_(n) {}

  std::size_t size() const {return n_;}
  /// True for a run of consecutive Samples (data() is then usable).
  bool contiguous() const {return idx_ == nullptr;}
  const Sample * data() const {return base_;}
  bool empty() const {return n_ == 0;}
  const Sample & operator[](std::size_t i) const {return idx_ ? base_[idx_[i]] : base_[i];}
  const Sample & front() const {return (*this)[0];}
  const Sample & back() const {return (*this)[n_ - 1];}
  /// The view without its first ``from`` samples.
  SampleSeq tail(std::size_t from) const
  {
    return idx_ ? SampleSeq(base_, idx_ + from, n_ - from) : SampleSeq(base_ + from, n_ - from);
  }
  /// Index of the first sample with ``t >= cutoff`` (size() when none).
  std::size_t first_at_or_after(double cutoff) const;

private:
  const Sample * base_ = nullptr;
  const uint32_t * idx_ = nullptr;
  std::size_t n_ = 0;
};

/// Everything reported for one window of one topic: the topic-level rates and one entry per
/// publisher (first-seen order).
struct WindowStats
{
  WindowResult topic;
  std::vector<EndpointResult> endpoints;
};

/// Computes the statistics of a topic for all its windows from one pass over the samples:
/// the samples are grouped by publisher gid once (hash map, indices only) and every window
/// reuses that grouping. Keep one instance per probe: it recycles its buffers across ticks.
class TopicCalculator
{
public:
  TopicCalculator();
  ~TopicCalculator();
  struct Impl;  // defined in stats.cpp

  TopicCalculator(const TopicCalculator &) = delete;
  TopicCalculator & operator=(const TopicCalculator &) = delete;

  /// ``retained``: contiguous samples in the longest window, oldest first (throws
  /// std::invalid_argument otherwise). One entry per element of ``windows``, in order.
  std::vector<WindowStats> compute(
    SampleSeq retained, double now, const std::vector<double> & windows,
    double max_window = kMaxWindowSec);

private:
  std::unique_ptr<Impl> impl_;
};

/// Rates over a set of samples (grouped by publisher internally).
Rates compute_stats(SampleSeq samples);

/// True when nothing arrived for max(3 x mean receive interval, 1 s).
bool is_silent(SampleSeq retained, double now);

/// Topic-level rates over ``window`` (falls back to ``max_window`` for slow topics).
WindowResult compute_window(
  SampleSeq retained, double now, double window, double max_window = kMaxWindowSec);

/// Per-publisher rates: compute_window on each gid's own samples (first-seen order).
std::vector<EndpointResult> compute_endpoints(
  SampleSeq retained, double now, double window, double max_window = kMaxWindowSec);

/// Ring buffer of the samples of one topic (the longest window, at most ``max_samples``).
class SampleBuffer
{
public:
  explicit SampleBuffer(double retain_sec = kMaxWindowSec, std::size_t max_samples = kMaxSamples);

  void record(const Sample & sample);
  /// Drops samples older than the retention; returns a view of what is left (oldest first).
  /// The view is valid until the next record() / retained().
  SampleSeq retained(double now);
  uint64_t total() const {return total_;}
  void set_retain(double retain_sec) {retain_sec_ = retain_sec;}

private:
  double retain_sec_;
  std::size_t max_samples_;
  std::vector<Sample> samples_;  // live samples are samples_[head_..]
  std::size_t head_ = 0;
  uint64_t total_ = 0;
};

}  // namespace roshanavi_probe

#endif  // ROSHANAVI_PROBE__STATS_HPP_
