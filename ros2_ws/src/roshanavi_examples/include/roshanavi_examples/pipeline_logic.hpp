// Pure logic of the relay pipeline sample (no ROS): shared by the source / relay / sink nodes
// and the gtest unit tests (test/test_pipeline_logic.cpp). Documented in docs/design/nodes.md.
#ifndef ROSHANAVI_EXAMPLES__PIPELINE_LOGIC_HPP_
#define ROSHANAVI_EXAMPLES__PIPELINE_LOGIC_HPP_

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <optional>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace roshanavi_examples
{
namespace pipeline
{

// ---- relay gate: drop_ratio and rate_limit_hz -----------------------------------------------

enum class Verdict
{
  kAccept,
  kDropRandom,  // lost to drop_ratio
  kDropRate     // arrived sooner than 1 / rate_limit_hz after the last published message
};

// Decides for every incoming message whether the relay processes and forwards it.
// drop_ratio (0..1) is the probability to drop a message at random; rate_limit_hz (0 = off)
// makes the relay publish at most that often: a message arriving earlier than 1 / rate_limit_hz
// after the last accepted one is dropped (not queued).
class RelayGate
{
public:
  explicit RelayGate(uint64_t seed)
  : rng_(seed) {}

  Verdict decide(double now_sec, double drop_ratio, double rate_limit_hz)
  {
    if (drop_ratio > 0.0 && uniform_(rng_) < drop_ratio) {
      return Verdict::kDropRandom;
    }
    if (rate_limit_hz > 0.0 && now_sec - last_accept_sec_ < 1.0 / rate_limit_hz) {
      return Verdict::kDropRate;
    }
    last_accept_sec_ = now_sec;
    return Verdict::kAccept;
  }

private:
  std::mt19937_64 rng_;
  std::uniform_real_distribution<double> uniform_{0.0, 1.0};
  double last_accept_sec_ = -std::numeric_limits<double>::infinity();
};

// ---- topic names ------------------------------------------------------------------------------

// Relative topic names of the pipeline nodes: "in", "in_1", "in_2", ... and "out", "out_1", ...
// (remap them in the launch file or the roshanavi project).
inline std::string endpoint_name(const std::string & base, size_t index)
{
  return index == 0 ? base : base + "_" + std::to_string(index);
}

// ---- payload size ---------------------------------------------------------------------------

// payload_bytes < 0: the output carries the input bytes unchanged; otherwise exactly
// payload_bytes bytes (the input bytes cut short, or padded with zeros).
inline std::vector<uint8_t> make_payload(const std::vector<uint8_t> & input, int64_t payload_bytes)
{
  if (payload_bytes < 0) {
    return input;
  }
  std::vector<uint8_t> out(static_cast<size_t>(payload_bytes), 0);
  std::copy_n(input.begin(), std::min(input.size(), out.size()), out.begin());
  return out;
}

// ---- fan-out --------------------------------------------------------------------------------

enum class FanoutMode
{
  kAll,        // every message goes to every output
  kRoundRobin  // output 0, 1, ..., n-1, 0, ... one per message (splits the load)
};

inline std::optional<FanoutMode> parse_fanout(const std::string & name)
{
  if (name == "all") {
    return FanoutMode::kAll;
  }
  if (name == "round_robin") {
    return FanoutMode::kRoundRobin;
  }
  return std::nullopt;
}

// Which outputs get the next message.
class FanoutSelector
{
public:
  std::vector<size_t> next(FanoutMode mode, size_t num_outputs)
  {
    std::vector<size_t> picked;
    if (num_outputs == 0) {
      return picked;
    }
    if (mode == FanoutMode::kAll) {
      for (size_t i = 0; i < num_outputs; ++i) {
        picked.push_back(i);
      }
      return picked;
    }
    picked.push_back(counter_++ % num_outputs);
    return picked;
  }

private:
  size_t counter_ = 0;
};

// ---- busy / sleep processing time -----------------------------------------------------------

inline void spin_for_ms(double ms)
{
  const auto end = std::chrono::steady_clock::now() +
    std::chrono::duration_cast<std::chrono::steady_clock::duration>(
    std::chrono::duration<double, std::milli>(ms));
  while (std::chrono::steady_clock::now() < end) {
    // burn CPU on purpose: this is what a real, CPU-bound callback does
  }
}

// ---- sink: sequence gaps and latency window -----------------------------------------------

// Counts received messages and the ones missing by sequence gaps of one source. A sequence that
// goes backwards means the source restarted: counting starts over, nothing is counted lost.
class SeqTracker
{
public:
  void add(uint32_t seq)
  {
    ++received_;
    if (last_ && seq > *last_ + 1) {
      lost_ += seq - *last_ - 1;
    }
    last_ = seq;
  }
  uint64_t received() const {return received_;}
  uint64_t lost() const {return lost_;}

private:
  std::optional<uint32_t> last_;
  uint64_t received_ = 0;
  uint64_t lost_ = 0;
};

struct LatencySummary
{
  size_t count = 0;
  double mean_ms = 0.0;
  double p50_ms = 0.0;
  double p95_ms = 0.0;
  double max_ms = 0.0;
};

// Latency samples of the last window_sec seconds (at most max_samples; the oldest go first).
class LatencyWindow
{
public:
  LatencyWindow(double window_sec, size_t max_samples)
  : window_sec_(window_sec), max_samples_(max_samples) {}

  void add(double now_sec, double latency_ms)
  {
    if (!first_sec_) {
      first_sec_ = now_sec;
    }
    samples_.emplace_back(now_sec, latency_ms);
    if (samples_.size() > max_samples_) {
      samples_.pop_front();
    }
  }

  // Samples older than the window are dropped; the summary covers what is left.
  LatencySummary summarize(double now_sec)
  {
    while (!samples_.empty() && now_sec - samples_.front().first > window_sec_) {
      samples_.pop_front();
    }
    LatencySummary out;
    out.count = samples_.size();
    if (samples_.empty()) {
      return out;
    }
    std::vector<double> values;
    values.reserve(samples_.size());
    double sum = 0.0;
    for (const auto & s : samples_) {
      values.push_back(s.second);
      sum += s.second;
    }
    std::sort(values.begin(), values.end());
    out.mean_ms = sum / static_cast<double>(values.size());
    out.p50_ms = percentile(values, 0.50);
    out.p95_ms = percentile(values, 0.95);
    out.max_ms = values.back();
    return out;
  }

  // Samples per second inside the window (the span since the first sample while that is shorter).
  double rate_hz(double now_sec) const
  {
    if (!first_sec_) {
      return 0.0;
    }
    size_t n = 0;
    for (const auto & s : samples_) {
      if (now_sec - s.first <= window_sec_) {
        ++n;
      }
    }
    const double span = std::min(window_sec_, std::max(now_sec - *first_sec_, 1e-3));
    return static_cast<double>(n) / span;
  }

  // Nearest-rank percentile of an ascending vector (p in 0..1).
  static double percentile(const std::vector<double> & sorted, double p)
  {
    if (sorted.empty()) {
      return 0.0;
    }
    const auto rank = static_cast<size_t>(std::ceil(p * static_cast<double>(sorted.size())));
    return sorted[std::min(sorted.size(), std::max<size_t>(rank, 1)) - 1];
  }

private:
  double window_sec_;
  size_t max_samples_;
  std::deque<std::pair<double, double>> samples_;
  std::optional<double> first_sec_;
};

}  // namespace pipeline
}  // namespace roshanavi_examples

#endif  // ROSHANAVI_EXAMPLES__PIPELINE_LOGIC_HPP_
