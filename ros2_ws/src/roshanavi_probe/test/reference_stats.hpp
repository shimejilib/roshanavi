// The original (pre-optimisation) statistics implementation, kept verbatim as a test oracle: it copies
// every Sample per window and per publisher. test_stats.cpp checks that the production
// TopicCalculator returns bit-identical results on random streams.
#ifndef ROSHANAVI_PROBE__REFERENCE_STATS_HPP_
#define ROSHANAVI_PROBE__REFERENCE_STATS_HPP_

#include <algorithm>
#include <cmath>
#include <utility>
#include <vector>

#include "roshanavi_probe/stats.hpp"

namespace roshanavi_probe::reference
{


inline constexpr double kNsPerSec = 1e9;
inline constexpr double kNsPerMs = 1e6;
inline constexpr double kMsPerSec = 1000.0;

struct RateAndIntervals
{
  double rate = 0.0;
  std::vector<double> intervals;
};

/// (count-1)/span of sorted ``times``; ``count`` = messages published in the span when known.
inline RateAndIntervals rate_and_intervals(const std::vector<double> & times, std::optional<int64_t> count)
{
  RateAndIntervals out;
  if (times.size() < 2) {
    return out;
  }
  const double span = times.back() - times.front();
  const double published = count ? static_cast<double>(*count) : static_cast<double>(times.size());
  out.rate = span > 0.0 ? (published - 1.0) / span : 0.0;
  out.intervals.reserve(times.size() - 1);
  for (std::size_t i = 1; i < times.size(); ++i) {
    out.intervals.push_back(times[i] - times[i - 1]);
  }
  return out;
}

inline double std_ms(const std::vector<double> & intervals)
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

inline bool seq_monotonic(const std::vector<uint64_t> & seqs)
{
  for (std::size_t i = 0; i < seqs.size(); ++i) {
    if (seqs[i] == 0 || (i > 0 && seqs[i] <= seqs[i - 1])) {
      return false;
    }
  }
  return true;
}

/// Samples grouped by gid, groups in first-seen order (like a Python dict).
inline std::vector<std::pair<Gid, std::vector<Sample>>> group_by_gid(const std::vector<Sample> & samples)
{
  std::vector<std::pair<Gid, std::vector<Sample>>> groups;
  for (const Sample & s : samples) {
    auto it = std::find_if(
      groups.begin(), groups.end(), [&s](const auto & g) {return g.first == s.gid;});
    if (it == groups.end()) {
      groups.emplace_back(s.gid, std::vector<Sample>{s});
    } else {
      it->second.push_back(s);
    }
  }
  return groups;
}

inline std::vector<uint64_t> seqs_of(const std::vector<Sample> & samples)
{
  std::vector<uint64_t> seqs;
  seqs.reserve(samples.size());
  for (const Sample & s : samples) {
    seqs.push_back(s.seq);
  }
  return seqs;
}

/// Publish-side rate summed over publishers; nullopt when a sample lacks a source timestamp.
inline std::optional<RateAndIntervals> source_rate(
  const std::vector<std::pair<Gid, std::vector<Sample>>> & groups, std::size_t n, bool all_src)
{
  if (n < 2 || !all_src) {
    return std::nullopt;
  }
  RateAndIntervals total;
  for (const auto & group : groups) {
    const std::vector<uint64_t> seqs = seqs_of(group.second);
    std::optional<int64_t> count;
    if (seq_monotonic(seqs)) {
      count = static_cast<int64_t>(seqs.back() - seqs.front() + 1);
    }
    std::vector<double> times;
    times.reserve(group.second.size());
    for (const Sample & s : group.second) {
      times.push_back(static_cast<double>(s.src_ns) / kNsPerSec);
    }
    std::sort(times.begin(), times.end());
    RateAndIntervals r = rate_and_intervals(times, count);
    total.rate += r.rate;
    total.intervals.insert(total.intervals.end(), r.intervals.begin(), r.intervals.end());
  }
  return total;
}

/// Sequence gaps per publisher; nullopt when any publisher's numbers are unusable.
inline void drops(const std::vector<std::pair<Gid, std::vector<Sample>>> & groups, Rates & out)
{
  int64_t dropped = 0;
  int64_t expected = 0;
  for (const auto & group : groups) {
    const std::vector<uint64_t> seqs = seqs_of(group.second);
    if (!seq_monotonic(seqs)) {
      return;  // unsupported, restarted publisher or interleaved publishers
    }
    const auto span = static_cast<int64_t>(seqs.back() - seqs.front() + 1);
    dropped += span - static_cast<int64_t>(seqs.size());
    expected += span;
  }
  if (expected > 0) {
    out.dropped = dropped;
    out.drop_ratio = static_cast<double>(dropped) / static_cast<double>(expected);
  }
}

inline std::vector<Sample> since(const std::vector<Sample> & samples, double cutoff)
{
  std::vector<Sample> out;
  for (const Sample & s : samples) {
    if (s.t >= cutoff) {
      out.push_back(s);
    }
  }
  return out;
}

inline void zero_rates(Rates & rates)
{
  rates.hz = 0.0;
  rates.hz_recv = 0.0;
  if (rates.hz_source) {
    rates.hz_source = 0.0;
  }
  rates.bytes_per_sec = 0.0;
}

inline Rates compute_stats(const std::vector<Sample> & samples)
{
  Rates out;
  const std::size_t n = samples.size();
  out.count = n;
  bool all_src = true;
  double latency_sum = 0.0;
  std::size_t latency_n = 0;
  std::vector<double> recv_times;
  recv_times.reserve(n);
  for (const Sample & s : samples) {
    out.bytes += s.size;
    recv_times.push_back(s.t);
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
  const RateAndIntervals recv = rate_and_intervals(recv_times, std::nullopt);
  out.hz_recv = recv.rate;
  out.jitter_recv_ms = std_ms(recv.intervals);
  const auto groups = group_by_gid(samples);
  const std::optional<RateAndIntervals> src = source_rate(groups, n, all_src);
  out.source_basis = src.has_value();
  if (src) {
    out.hz_source = src->rate;
    out.hz = src->rate;
    out.jitter_ms = std_ms(src->intervals);
  } else {
    out.hz = out.hz_recv;
    out.jitter_ms = out.jitter_recv_ms;
  }
  if (n >= 2) {
    drops(groups, out);
  }
  if (latency_n > 0) {
    out.latency_ms = latency_sum / static_cast<double>(latency_n) / kNsPerMs;
  }
  out.bytes_per_sec = out.hz * out.avg_size;
  return out;
}

inline bool is_silent(const std::vector<Sample> & retained, double now)
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

inline WindowResult compute_window(
  const std::vector<Sample> & retained, double now, double window, double max_window)
{
  WindowResult out;
  out.window_sec = window;
  out.rate_window_sec = window;
  std::vector<Sample> samples = since(retained, now - window);
  for (const Sample & s : samples) {
    out.recent_count += s.t > now - kRecentSec ? 1 : 0;
  }
  out.stale = is_silent(retained, now);
  if (!out.stale && samples.size() < 2 && !retained.empty()) {
    std::vector<Sample> longer = since(retained, now - max_window);
    if (max_window > window && longer.size() >= 2) {
      samples = std::move(longer);
      out.rate_window_sec = max_window;
      out.note = RateNote::kExtended;
    } else {
      out.note = RateNote::kTooFew;
    }
  }
  out.rates = compute_stats(samples);
  if (out.stale) {
    zero_rates(out.rates);
  }
  return out;
}

inline std::vector<EndpointResult> compute_endpoints(
  const std::vector<Sample> & retained, double now, double window, double max_window)
{
  std::vector<EndpointResult> out;
  for (const auto & group : group_by_gid(retained)) {
    out.push_back(EndpointResult{group.first, compute_window(group.second, now, window, max_window)});
  }
  return out;
}

}  // namespace roshanavi_probe::reference

#endif  // ROSHANAVI_PROBE__REFERENCE_STATS_HPP_
