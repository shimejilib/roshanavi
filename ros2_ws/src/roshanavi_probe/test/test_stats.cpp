// Unit tests of the probe statistics (time is injected, no ROS needed).
#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <vector>

#include "roshanavi_probe/stats.hpp"

namespace rp = roshanavi_probe;

namespace
{

constexpr int64_t kNs = 1000000000;

rp::Gid gid(uint8_t id)
{
  rp::Gid g{};
  g[0] = id;
  return g;
}

/// ``n`` samples at ``hz`` from publisher ``id``, starting at ``t0`` (seconds), seq from 1.
std::vector<rp::Sample> series(uint8_t id, double hz, int n, double t0 = 0.0, uint64_t seq0 = 1)
{
  std::vector<rp::Sample> out;
  for (int i = 0; i < n; ++i) {
    const double t = t0 + i / hz;
    rp::Sample s;
    s.t = t;
    s.size = 100;
    s.src_ns = static_cast<int64_t>((t + 1000.0) * kNs);
    s.recv_ns = s.src_ns + 2000000;  // 2 ms latency
    s.seq = seq0 + static_cast<uint64_t>(i);
    s.gid = gid(id);
    out.push_back(s);
  }
  return out;
}

std::vector<rp::Sample> merged(std::vector<rp::Sample> a, const std::vector<rp::Sample> & b)
{
  a.insert(a.end(), b.begin(), b.end());
  std::stable_sort(
    a.begin(), a.end(), [](const rp::Sample & x, const rp::Sample & y) {return x.t < y.t;});
  return a;
}

}  // namespace

TEST(ComputeStats, SourceRateAndBandwidth)
{
  const rp::Rates r = rp::compute_stats(series(1, 10.0, 11));
  EXPECT_TRUE(r.source_basis);
  EXPECT_NEAR(r.hz, 10.0, 1e-6);
  EXPECT_NEAR(*r.hz_source, 10.0, 1e-6);
  EXPECT_NEAR(r.hz_recv, 10.0, 1e-6);
  EXPECT_NEAR(r.bytes_per_sec, 1000.0, 1e-3);
  EXPECT_EQ(r.count, 11u);
  EXPECT_EQ(r.bytes, 1100u);
  EXPECT_EQ(*r.dropped, 0);
  EXPECT_NEAR(*r.latency_ms, 2.0, 1e-6);
  EXPECT_NEAR(r.jitter_ms, 0.0, 1e-6);
}

TEST(ComputeStats, SequenceGapsCountAsPublished)
{
  std::vector<rp::Sample> s = series(1, 10.0, 11);
  s.erase(s.begin() + 3);  // seq 4 lost
  s.erase(s.begin() + 5);  // seq 7 lost
  const rp::Rates r = rp::compute_stats(s);
  EXPECT_EQ(*r.dropped, 2);
  EXPECT_NEAR(*r.drop_ratio, 2.0 / 11.0, 1e-9);
  EXPECT_NEAR(r.hz, 10.0, 1e-6);  // lost messages were still published
  EXPECT_LT(r.hz_recv, 10.0);
}

TEST(ComputeStats, MultiPublisherSumsPerGid)
{
  const auto s = merged(series(1, 5.0, 11), series(2, 2.0, 5));
  const rp::Rates r = rp::compute_stats(s);
  EXPECT_NEAR(r.hz, 7.0, 1e-6);
  EXPECT_EQ(*r.dropped, 0);  // interleaved numbering is fine per gid
}

TEST(ComputeStats, UnsupportedSequenceGivesUnknownDrops)
{
  std::vector<rp::Sample> s = series(1, 10.0, 6);
  for (auto & x : s) {
    x.seq = 0;
  }
  const rp::Rates r = rp::compute_stats(s);
  EXPECT_FALSE(r.dropped.has_value());
  EXPECT_FALSE(r.drop_ratio.has_value());
  EXPECT_NEAR(r.hz, 10.0, 1e-6);  // still the source-timestamp rate
}

TEST(ComputeStats, MissingSourceStampsFallBackToReceive)
{
  std::vector<rp::Sample> s = series(1, 4.0, 5);
  s[2].src_ns = 0;
  const rp::Rates r = rp::compute_stats(s);
  EXPECT_FALSE(r.source_basis);
  EXPECT_FALSE(r.hz_source.has_value());
  EXPECT_NEAR(r.hz, 4.0, 1e-6);
}

TEST(ComputeStats, EmptyAndSingle)
{
  EXPECT_EQ(rp::compute_stats({}).hz, 0.0);
  const rp::Rates one = rp::compute_stats(series(1, 1.0, 1));
  EXPECT_EQ(one.hz, 0.0);
  EXPECT_FALSE(one.hz_source.has_value());
  EXPECT_FALSE(one.dropped.has_value());
}

TEST(ComputeWindow, SelectsTheRequestedWindow)
{
  const auto s = series(1, 10.0, 100);  // 0 .. 9.9 s
  const rp::WindowResult w1 = rp::compute_window(s, 9.95, 1.0);
  const rp::WindowResult w5 = rp::compute_window(s, 9.95, 5.0);
  EXPECT_EQ(w1.rates.count, 10u);
  EXPECT_EQ(w5.rates.count, 50u);
  EXPECT_NEAR(w1.rates.hz, 10.0, 1e-6);
  EXPECT_EQ(w1.note, rp::RateNote::kNone);
  EXPECT_EQ(w1.recent_count, 10u);
}

TEST(ComputeWindow, SlowTopicExtendsThenTooFew)
{
  const auto slow = series(1, 0.5, 3);  // t = 0, 2, 4
  const rp::WindowResult w = rp::compute_window(slow, 4.5, 1.0);
  EXPECT_EQ(w.note, rp::RateNote::kExtended);
  EXPECT_DOUBLE_EQ(w.rate_window_sec, rp::kMaxWindowSec);
  EXPECT_NEAR(w.rates.hz, 0.5, 1e-6);
  const rp::WindowResult few = rp::compute_window(series(1, 1.0, 1), 0.5, 1.0);
  EXPECT_EQ(few.note, rp::RateNote::kTooFew);
  EXPECT_EQ(few.rates.hz, 0.0);
}

TEST(ComputeWindow, StoppedTopicIsZeroAndStale)
{
  const auto s = series(1, 10.0, 20);  // last at 1.9 s
  const rp::WindowResult w = rp::compute_window(s, 3.5, 5.0);
  EXPECT_TRUE(w.stale);
  EXPECT_EQ(w.rates.hz, 0.0);
  EXPECT_EQ(*w.rates.hz_source, 0.0);
  EXPECT_EQ(w.rates.bytes_per_sec, 0.0);
  EXPECT_EQ(w.note, rp::RateNote::kNone);
}

TEST(ComputeEndpoints, PerPublisherRatesAndStaleness)
{
  // publisher 1 at 5 Hz keeps going, publisher 2 at 2 Hz stopped at 3 s
  const auto s = merged(series(1, 5.0, 50), series(2, 2.0, 7));
  const auto eps = rp::compute_endpoints(s, 9.9, 5.0);
  ASSERT_EQ(eps.size(), 2u);
  EXPECT_EQ(eps[0].gid, gid(1));
  EXPECT_NEAR(eps[0].result.rates.hz, 5.0, 1e-6);
  EXPECT_FALSE(eps[0].result.stale);
  EXPECT_EQ(eps[1].gid, gid(2));
  EXPECT_TRUE(eps[1].result.stale);
  EXPECT_EQ(eps[1].result.rates.hz, 0.0);
}

TEST(ComputeEndpoints, TwoLivePublishers)
{
  const auto s = merged(series(1, 5.0, 50), series(2, 2.0, 20));
  const auto eps = rp::compute_endpoints(s, 9.9, 5.0);
  ASSERT_EQ(eps.size(), 2u);
  EXPECT_NEAR(eps[0].result.rates.hz, 5.0, 1e-6);
  EXPECT_NEAR(eps[1].result.rates.hz, 2.0, 1e-6);
  EXPECT_EQ(*eps[1].result.rates.dropped, 0);
}

TEST(SampleBuffer, PrunesByAgeAndCapsCount)
{
  rp::SampleBuffer buf(10.0, 5);
  for (const auto & s : series(1, 1.0, 8)) {
    buf.record(s);
  }
  EXPECT_EQ(buf.total(), 8u);
  EXPECT_EQ(buf.retained(7.0).size(), 5u);  // capped
  EXPECT_EQ(buf.retained(15.5).size(), 2u);  // t = 6, 7 within 10 s
  EXPECT_TRUE(buf.retained(100.0).empty());
}
