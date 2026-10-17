// Unit tests of the probe statistics (time is injected, no ROS needed).
#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iterator>
#include <random>
#include <stdexcept>
#include <vector>

#include "reference_stats.hpp"
#include "roshanavi_probe/publisher_directory.hpp"
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

TEST(SampleBuffer, ViewStaysCorrectAcrossCompaction)
{
  rp::SampleBuffer buf(1e9, 3000);
  const auto all = series(1, 1000.0, 20000);
  for (std::size_t i = 0; i < all.size(); ++i) {
    buf.record(all[i]);
    if (i % 997 == 0) {
      const rp::SampleSeq view = buf.retained(0.0);
      ASSERT_EQ(view.size(), std::min<std::size_t>(i + 1, 3000));
      EXPECT_EQ(view.back().seq, all[i].seq);
      EXPECT_EQ(view.front().seq, all[i].seq + 1 - view.size());
    }
  }
  EXPECT_EQ(buf.total(), 20000u);
}

// --- the grouped single-pass computation against the original copy-per-window one ---

namespace
{

void expect_same(const rp::Rates & a, const rp::Rates & b)
{
  EXPECT_EQ(a.hz, b.hz);
  EXPECT_EQ(a.source_basis, b.source_basis);
  EXPECT_EQ(a.hz_recv, b.hz_recv);
  EXPECT_EQ(a.hz_source, b.hz_source);
  EXPECT_EQ(a.bytes_per_sec, b.bytes_per_sec);
  EXPECT_EQ(a.avg_size, b.avg_size);
  EXPECT_EQ(a.jitter_ms, b.jitter_ms);
  EXPECT_EQ(a.jitter_recv_ms, b.jitter_recv_ms);
  EXPECT_EQ(a.dropped, b.dropped);
  EXPECT_EQ(a.drop_ratio, b.drop_ratio);
  EXPECT_EQ(a.latency_ms, b.latency_ms);
  EXPECT_EQ(a.count, b.count);
  EXPECT_EQ(a.bytes, b.bytes);
  EXPECT_EQ(a.first_src_ns, b.first_src_ns);
  EXPECT_EQ(a.last_src_ns, b.last_src_ns);
}

void expect_same(const rp::WindowResult & a, const rp::WindowResult & b)
{
  expect_same(a.rates, b.rates);
  EXPECT_EQ(a.window_sec, b.window_sec);
  EXPECT_EQ(a.rate_window_sec, b.rate_window_sec);
  EXPECT_EQ(a.note, b.note);
  EXPECT_EQ(a.stale, b.stale);
  EXPECT_EQ(a.recent_count, b.recent_count);
}

/// A random multi-publisher stream: several rates, jittered or quantized receive times,
/// dropped / restarted / unsupported sequence numbers, missing source stamps, publishers
/// that stop or start late. Sorted by receive time like the probe's buffer.
std::vector<rp::Sample> random_stream(std::mt19937 & rng, double * end_time)
{
  std::uniform_real_distribution<double> unit(0.0, 1.0);
  const int publishers = 1 + static_cast<int>(rng() % 4);
  const bool quantized = rng() % 3 == 0;  // equal timestamps and exact window boundaries
  const std::vector<double> rates{0.2, 1.0, 5.0, 20.0, 100.0};
  std::vector<rp::Sample> all;
  double horizon = 0.0;
  for (int p = 0; p < publishers; ++p) {
    const double hz = rates[rng() % rates.size()];
    const double start = unit(rng) * 6.0;
    const double stop = rng() % 3 == 0 ? start + unit(rng) * 8.0 : 1e9;
    const bool no_seq = rng() % 5 == 0;
    const bool partial_src = rng() % 6 == 0;
    const double drop = rng() % 2 ? 0.0 : unit(rng) * 0.3;
    uint64_t seq = 1 + rng() % 50;
    const uint8_t id = static_cast<uint8_t>(1 + p + (rng() % 2 ? 0 : 100));
    for (double t = start; t < std::min(stop, 14.0); t += 1.0 / hz) {
      seq += unit(rng) < drop ? 2 : 1;
      if (rng() % 400 == 0) {
        seq = 1;  // restarted publisher
      }
      rp::Sample s;
      s.t = t + (unit(rng) - 0.5) * 0.2 / hz;
      if (quantized) {
        s.t = std::floor(s.t * 100.0) / 100.0;
      }
      s.size = 8 + rng() % 200;
      s.src_ns = static_cast<int64_t>((s.t + 1000.0 - unit(rng) * 0.003) * kNs);
      s.recv_ns = s.src_ns + static_cast<int64_t>(unit(rng) * 5e6);
      s.seq = no_seq ? 0 : seq;
      if (partial_src && rng() % 7 == 0) {
        s.src_ns = 0;
      }
      s.gid = gid(id);
      all.push_back(s);
      horizon = std::max(horizon, s.t);
    }
  }
  std::stable_sort(
    all.begin(), all.end(), [](const rp::Sample & x, const rp::Sample & y) {return x.t < y.t;});
  *end_time = horizon;
  return all;
}

}  // namespace

TEST(TopicCalculator, MatchesOriginalImplementationOnRandomStreams)
{
  std::mt19937 rng(18);
  rp::TopicCalculator calc;  // reused across streams like the probe does across ticks
  const std::vector<double> windows{1.0, 5.0, 10.0, 0.5, 2.5};
  const std::vector<double> now_offsets{0.0, 0.3, 1.0, 2.5, 12.0};
  int compared = 0;
  for (int iter = 0; iter < 300; ++iter) {
    double end = 0.0;
    const std::vector<rp::Sample> stream = random_stream(rng, &end);
    for (const double offset : now_offsets) {
      const double now = end + offset;
      std::vector<rp::Sample> retained;  // what a 10 s buffer holds
      std::copy_if(
        stream.begin(), stream.end(), std::back_inserter(retained),
        [now](const rp::Sample & s) {return s.t >= now - rp::kMaxWindowSec && s.t <= now;});
      const auto got = calc.compute(retained, now, windows);
      ASSERT_EQ(got.size(), windows.size());
      for (std::size_t w = 0; w < windows.size(); ++w) {
        SCOPED_TRACE(testing::Message() << "iter " << iter << " now " << now << " window "
                                        << windows[w]);
        expect_same(got[w].topic, rp::reference::compute_window(retained, now, windows[w], rp::kMaxWindowSec));
        const auto want = rp::reference::compute_endpoints(retained, now, windows[w], rp::kMaxWindowSec);
        ASSERT_EQ(got[w].endpoints.size(), want.size());
        for (std::size_t e = 0; e < want.size(); ++e) {
          EXPECT_EQ(got[w].endpoints[e].gid, want[e].gid);
          expect_same(got[w].endpoints[e].result, want[e].result);
        }
        // the single-window helpers are views of the same computation
        expect_same(rp::compute_window(retained, now, windows[w]), got[w].topic);
        expect_same(rp::compute_stats(retained), rp::reference::compute_stats(retained));
        ++compared;
      }
    }
  }
  EXPECT_EQ(compared, 300 * 5 * 5);
}

TEST(PublisherDirectory, RefreshesOnlyWhenNeeded)
{
  rp::PublisherDirectory dir;
  const std::vector<rp::Gid> one{gid(1)};
  EXPECT_TRUE(dir.needs_refresh(0.0, {}));  // never looked up
  dir.update({{gid(1), {"talker", "/"}}}, one, 0.0);
  EXPECT_EQ(dir.names().at(gid(1)).node_name, "talker");
  EXPECT_FALSE(dir.needs_refresh(1.0, one));
  EXPECT_FALSE(dir.needs_refresh(4.9, one));
  EXPECT_TRUE(dir.needs_refresh(5.0, one));  // fallback
  dir.mark_dirty();                          // graph changed
  EXPECT_TRUE(dir.needs_refresh(0.5, one));
  dir.update({{gid(1), {"talker", "/"}}}, one, 1.0);
  EXPECT_FALSE(dir.needs_refresh(1.5, one));
}

TEST(PublisherDirectory, UnknownGidIsAskedOnceThenRemembered)
{
  rp::PublisherDirectory dir;
  const std::vector<rp::Gid> both{gid(1), gid(2)};
  dir.update({{gid(1), {"a", "/"}}}, {gid(1)}, 0.0);
  EXPECT_TRUE(dir.needs_refresh(1.0, both));  // gid 2 appeared
  dir.update({{gid(1), {"a", "/"}}}, both, 1.0);  // graph does not know gid 2 (yet)
  EXPECT_EQ(dir.names().count(gid(2)), 0u);
  EXPECT_FALSE(dir.needs_refresh(2.0, both));  // not asked again every tick
  dir.mark_dirty();                             // ... until the graph changes
  EXPECT_TRUE(dir.needs_refresh(2.5, both));
  dir.update({{gid(1), {"a", "/"}}, {gid(2), {"b", "/ns"}}}, both, 2.5);
  EXPECT_EQ(dir.names().at(gid(2)).node_namespace, "/ns");
  EXPECT_FALSE(dir.needs_refresh(3.0, both));
}

TEST(PublisherDirectory, FailedLookupKeepsTableAndStaysDirty)
{
  rp::PublisherDirectory dir;
  const std::vector<rp::Gid> one{gid(1)};
  dir.update({{gid(1), {"a", "/"}}}, one, 0.0);
  dir.mark_dirty();
  // the caller's graph query threw: update() is not called
  EXPECT_TRUE(dir.needs_refresh(1.0, one));
  EXPECT_TRUE(dir.needs_refresh(2.0, one));
  EXPECT_EQ(dir.names().at(gid(1)).node_name, "a");
}

TEST(TopicCalculator, NoSamplesAndRejectsStridedViews)
{
  rp::TopicCalculator calc;
  const auto got = calc.compute(rp::SampleSeq(), 5.0, {1.0, 5.0});
  ASSERT_EQ(got.size(), 2u);
  EXPECT_TRUE(got[0].endpoints.empty());
  EXPECT_EQ(got[0].topic.rates.count, 0u);
  const std::vector<rp::Sample> s = series(1, 10.0, 5);
  const uint32_t idx[] = {0, 2};
  EXPECT_THROW(calc.compute(rp::SampleSeq(s.data(), idx, 2), 1.0, {1.0}), std::invalid_argument);
}
