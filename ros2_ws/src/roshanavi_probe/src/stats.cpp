// Sliding-window statistics; see stats.hpp and roshanavi/stats.py.
//
// The arithmetic (summation order, interval order, sorting) is the one of the original
// copy-per-window implementation, so every number is bit-identical to it; the unit tests
// compare against that reference on random streams.
#include "roshanavi_probe/stats.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace roshanavi_probe
{
namespace
{

constexpr double kNsPerSec = 1e9;
constexpr double kNsPerMs = 1e6;
constexpr double kMsPerSec = 1000.0;
constexpr std::size_t kCompactMin = 1024;  // SampleBuffer: smallest dead prefix worth erasing

struct GidHash
{
  std::size_t operator()(const Gid & gid) const
  {
    uint64_t a = 0;
    uint64_t b = 0;
    std::memcpy(&a, gid.data(), sizeof(a));
    std::memcpy(&b, gid.data() + sizeof(a), sizeof(b));
    constexpr uint64_t kMix = 0x9E3779B97F4A7C15ULL;
    return static_cast<std::size_t>((a * kMix) ^ ((b + (a >> 29)) * kMix));
  }
};

/// Population standard deviation of ``intervals`` in ms.
double std_ms(const std::vector<double> & intervals)
{
  if (intervals.empty()) {
    return 0.0;
  }
  double mean = 0.0;
  for (double x : intervals) {
    mean += x;
  }
  mean /= static_cast<double>(intervals.size());
  double var = 0.0;
  for (double x : intervals) {
    var += (x - mean) * (x - mean);
  }
  return std::sqrt(var / static_cast<double>(intervals.size())) * kMsPerSec;
}

bool seq_monotonic(SampleSeq s)
{
  for (std::size_t i = 0; i < s.size(); ++i) {
    if (s[i].seq == 0 || (i > 0 && s[i].seq <= s[i - 1].seq)) {
      return false;
    }
  }
  return true;
}

/// Publication sequence numbers published in the span, nullopt when they are unusable.
std::optional<int64_t> published_count(SampleSeq s)
{
  if (s.empty() || !seq_monotonic(s)) {
    return std::nullopt;
  }
  return static_cast<int64_t>(s.back().seq - s.front().seq + 1);
}

void zero_rates(Rates & rates)
{
  rates.hz = 0.0;
  rates.hz_recv = 0.0;
  if (rates.hz_source) {
    rates.hz_source = 0.0;
  }
  rates.bytes_per_sec = 0.0;
}

/// Samples of one topic by publisher: indices into the run, groups in first-seen order.
class Grouping
{
public:
  struct Group
  {
    Gid gid{};
    std::vector<uint32_t> idx;  // ascending
  };

  /// One pass over ``all``; buffers are recycled between calls.
  void build(SampleSeq all)
  {
    for (std::size_t g = 0; g < used_; ++g) {
      groups_[g].idx.clear();
    }
    used_ = 0;
    index_.clear();
    std::size_t last = 0;
    for (std::size_t i = 0; i < all.size(); ++i) {
      const Gid & gid = all[i].gid;
      if (used_ == 0 || groups_[last].gid != gid) {
        last = find_or_add(gid);
      }
      groups_[last].idx.push_back(static_cast<uint32_t>(i));
    }
  }

  std::size_t size() const {return used_;}
  const Group & operator[](std::size_t g) const {return groups_[g];}

private:
  std::size_t find_or_add(const Gid & gid)
  {
    const auto it = index_.find(gid);
    if (it != index_.end()) {
      return it->second;
    }
    const std::size_t g = used_++;
    if (g == groups_.size()) {
      groups_.emplace_back();
    }
    groups_[g].gid = gid;
    index_.emplace(gid, g);
    return g;
  }

  std::vector<Group> groups_;
  std::size_t used_ = 0;
  std::unordered_map<Gid, std::size_t, GidHash> index_;
};

}  // namespace

std::size_t SampleSeq::first_at_or_after(double cutoff) const
{
  std::size_t lo = 0;
  std::size_t hi = n_;
  while (lo < hi) {
    const std::size_t mid = lo + (hi - lo) / 2;
    if ((*this)[mid].t < cutoff) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo;
}

struct TopicCalculator::Impl
{
  Grouping grouping;
  // Scratch buffers, reused by every window.
  std::vector<double> recv_intervals;
  std::vector<double> src_intervals;
  std::vector<double> src_times;
  std::vector<SampleSeq> groups;

  /// Publisher groups restricted to ``all[start..]``, ordered by their first sample there
  /// (the order group_by_gid gives on that slice). Samples are sorted by time.
  void groups_from(SampleSeq all, std::size_t start)
  {
    groups.clear();
    for (std::size_t g = 0; g < grouping.size(); ++g) {
      const std::vector<uint32_t> & idx = grouping[g].idx;
      const auto from = std::lower_bound(idx.begin(), idx.end(), static_cast<uint32_t>(start));
      if (from != idx.end()) {
        groups.emplace_back(
          all.data(), idx.data() + (from - idx.begin()), static_cast<std::size_t>(idx.end() - from));
      }
    }
    std::sort(
      groups.begin(), groups.end(),
      [](const SampleSeq & a, const SampleSeq & b) {return &a.front() < &b.front();});
  }

  /// Publish-side rate of one publisher's samples; its intervals are appended to src_intervals.
  double source_rate_of(SampleSeq group)
  {
    src_times.clear();
    for (std::size_t i = 0; i < group.size(); ++i) {
      src_times.push_back(static_cast<double>(group[i].src_ns) / kNsPerSec);
    }
    if (!std::is_sorted(src_times.begin(), src_times.end())) {
      std::sort(src_times.begin(), src_times.end());
    }
    if (src_times.size() < 2) {
      return 0.0;
    }
    const double span = src_times.back() - src_times.front();
    const std::optional<int64_t> count = published_count(group);
    const double published =
      count ? static_cast<double>(*count) : static_cast<double>(src_times.size());
    for (std::size_t i = 1; i < src_times.size(); ++i) {
      src_intervals.push_back(src_times[i] - src_times[i - 1]);
    }
    return span > 0.0 ? (published - 1.0) / span : 0.0;
  }

  /// Sequence gaps per publisher; leaves ``out`` untouched when any publisher's numbers are
  /// unusable (unsupported, restarted publisher or interleaved publishers).
  static void drops(const std::vector<SampleSeq> & by_gid, Rates & out)
  {
    int64_t dropped = 0;
    int64_t expected = 0;
    for (const SampleSeq & group : by_gid) {
      const std::optional<int64_t> span = published_count(group);
      if (!span) {
        return;
      }
      dropped += *span - static_cast<int64_t>(group.size());
      expected += *span;
    }
    if (expected > 0) {
      out.dropped = dropped;
      out.drop_ratio = static_cast<double>(dropped) / static_cast<double>(expected);
    }
  }

  /// Rates over ``samples``; ``by_gid`` = its samples split by publisher (used when n >= 2).
  Rates stats(SampleSeq samples, const std::vector<SampleSeq> & by_gid)
  {
    Rates out;
    const std::size_t n = samples.size();
    out.count = n;
    bool all_src = true;
    double latency_sum = 0.0;
    std::size_t latency_n = 0;
    for (std::size_t i = 0; i < n; ++i) {
      const Sample & s = samples[i];
      out.bytes += s.size;
      all_src = all_src && s.src_ns > 0;
      if (s.src_ns > 0) {
        out.first_src_ns = out.first_src_ns == 0 ? s.src_ns : std::min(out.first_src_ns, s.src_ns);
        out.last_src_ns = std::max(out.last_src_ns, s.src_ns);
      }
      if (s.src_ns > 0 && s.recv_ns > 0) {
        latency_sum += static_cast<double>(s.recv_ns - s.src_ns);
        ++latency_n;
      }
    }
    out.avg_size = n ? static_cast<double>(out.bytes) / static_cast<double>(n) : 0.0;
    recv_intervals.clear();
    if (n >= 2) {
      const double span = samples.back().t - samples.front().t;
      out.hz_recv = span > 0.0 ? (static_cast<double>(n) - 1.0) / span : 0.0;
      for (std::size_t i = 1; i < n; ++i) {
        recv_intervals.push_back(samples[i].t - samples[i - 1].t);
      }
    }
    out.jitter_recv_ms = std_ms(recv_intervals);
    out.source_basis = n >= 2 && all_src;
    if (out.source_basis) {
      double rate = 0.0;
      src_intervals.clear();
      for (const SampleSeq & group : by_gid) {
        rate += source_rate_of(group);
      }
      out.hz_source = rate;
      out.hz = rate;
      out.jitter_ms = std_ms(src_intervals);
    } else {
      out.hz = out.hz_recv;
      out.jitter_ms = out.jitter_recv_ms;
    }
    if (n >= 2) {
      drops(by_gid, out);
    }
    if (latency_n > 0) {
      out.latency_ms = latency_sum / static_cast<double>(latency_n) / kNsPerMs;
    }
    out.bytes_per_sec = out.hz * out.avg_size;
    return out;
  }

  /// One window of ``retained``. ``topic_level``: split by publisher through ``grouping``
  /// (``retained`` is then the run the grouping was built from); else ``retained`` is one
  /// publisher's samples and is its own single group.
  WindowResult window(
    SampleSeq retained, double now, double window_sec, double max_window, bool topic_level)
  {
    WindowResult out;
    out.window_sec = window_sec;
    out.rate_window_sec = window_sec;
    std::size_t start = retained.first_at_or_after(now - window_sec);
    SampleSeq samples = retained.tail(start);
    const std::size_t recent_from = first_after(retained, now - kRecentSec);
    out.recent_count = static_cast<uint32_t>(retained.size() - std::max(start, recent_from));
    out.stale = is_silent(retained, now);
    if (!out.stale && samples.size() < 2 && !retained.empty()) {
      const std::size_t longer_start = retained.first_at_or_after(now - max_window);
      if (max_window > window_sec && retained.size() - longer_start >= 2) {
        start = longer_start;
        samples = retained.tail(start);
        out.rate_window_sec = max_window;
        out.note = RateNote::kExtended;
      } else {
        out.note = RateNote::kTooFew;
      }
    }
    if (samples.size() < 2) {
      groups.clear();
    } else if (topic_level) {
      groups_from(retained, start);
    } else {
      groups.assign(1, samples);
    }
    out.rates = stats(samples, groups);
    if (out.stale) {
      zero_rates(out.rates);
    }
    return out;
  }

  /// Index of the first sample with ``t > cutoff``.
  static std::size_t first_after(SampleSeq s, double cutoff)
  {
    std::size_t lo = 0;
    std::size_t hi = s.size();
    while (lo < hi) {
      const std::size_t mid = lo + (hi - lo) / 2;
      if (s[mid].t <= cutoff) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo;
  }
};

TopicCalculator::TopicCalculator()
: impl_(std::make_unique<Impl>())
{
}

TopicCalculator::~TopicCalculator() = default;

std::vector<WindowStats> TopicCalculator::compute(
  SampleSeq retained, double now, const std::vector<double> & windows, double max_window)
{
  if (!retained.contiguous()) {
    throw std::invalid_argument("TopicCalculator::compute needs contiguous samples");
  }
  Impl & m = *impl_;
  m.grouping.build(retained);
  std::vector<WindowStats> out;
  out.reserve(windows.size());
  for (double window : windows) {
    WindowStats ws;
    ws.topic = m.window(retained, now, window, max_window, true);
    ws.endpoints.reserve(m.grouping.size());
    for (std::size_t g = 0; g < m.grouping.size(); ++g) {
      const Grouping::Group & group = m.grouping[g];
      const SampleSeq own(retained.data(), group.idx.data(), group.idx.size());
      ws.endpoints.push_back(
        EndpointResult{group.gid, m.window(own, now, window, max_window, false)});
    }
    out.push_back(std::move(ws));
  }
  return out;
}

Rates compute_stats(SampleSeq samples)
{
  TopicCalculator::Impl m;
  m.grouping.build(samples);
  m.groups_from(samples, 0);
  return m.stats(samples, m.groups);
}

bool is_silent(SampleSeq retained, double now)
{
  if (retained.empty()) {
    return false;
  }
  double limit = kStaleMinSec;
  if (retained.size() >= 2) {
    const double span = retained.back().t - retained.front().t;
    if (span > 0.0) {
      const double period = span / static_cast<double>(retained.size() - 1);
      limit = std::max(kStalePeriods * period, kStaleMinSec);
    }
  }
  return now - retained.back().t > limit;
}

WindowResult compute_window(SampleSeq retained, double now, double window, double max_window)
{
  TopicCalculator calc;
  return calc.compute(retained, now, {window}, max_window).front().topic;
}

std::vector<EndpointResult> compute_endpoints(
  SampleSeq retained, double now, double window, double max_window)
{
  TopicCalculator calc;
  return std::move(calc.compute(retained, now, {window}, max_window).front().endpoints);
}

SampleBuffer::SampleBuffer(double retain_sec, std::size_t max_samples)
: retain_sec_(retain_sec), max_samples_(max_samples)
{
}

void SampleBuffer::record(const Sample & sample)
{
  if (max_samples_ > 0 && samples_.size() - head_ >= max_samples_) {
    ++head_;
  }
  if (head_ >= kCompactMin && head_ >= samples_.size() - head_) {
    samples_.erase(samples_.begin(), samples_.begin() + static_cast<std::ptrdiff_t>(head_));
    head_ = 0;
  }
  samples_.push_back(sample);
  ++total_;
}

SampleSeq SampleBuffer::retained(double now)
{
  const double cutoff = now - retain_sec_;
  while (head_ < samples_.size() && samples_[head_].t < cutoff) {
    ++head_;
  }
  return SampleSeq(samples_.data() + head_, samples_.size() - head_);
}

}  // namespace roshanavi_probe
