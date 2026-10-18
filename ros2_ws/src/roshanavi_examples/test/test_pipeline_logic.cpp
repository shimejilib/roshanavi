// Unit tests of the relay pipeline logic (no ROS): gate, payload size, fan-out, sink statistics.
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "roshanavi_examples/pipeline_logic.hpp"

using roshanavi_examples::pipeline::FanoutMode;
using roshanavi_examples::pipeline::FanoutSelector;
using roshanavi_examples::pipeline::LatencyWindow;
using roshanavi_examples::pipeline::RelayGate;
using roshanavi_examples::pipeline::SeqTracker;
using roshanavi_examples::pipeline::Verdict;

TEST(RelayGate, AcceptsEverythingWithoutDropOrLimit)
{
  RelayGate gate(1);
  for (int i = 0; i < 1000; ++i) {
    EXPECT_EQ(gate.decide(i * 0.0001, 0.0, 0.0), Verdict::kAccept);
  }
}

TEST(RelayGate, DropRatioOneDropsEverythingAndZeroNothing)
{
  RelayGate gate(2);
  for (int i = 0; i < 100; ++i) {
    EXPECT_EQ(gate.decide(i, 1.0, 0.0), Verdict::kDropRandom);
  }
}

TEST(RelayGate, DropRatioIsRoughlyTheGivenFraction)
{
  RelayGate gate(3);
  int dropped = 0;
  const int total = 20000;
  for (int i = 0; i < total; ++i) {
    if (gate.decide(i, 0.25, 0.0) == Verdict::kDropRandom) {
      ++dropped;
    }
  }
  EXPECT_NEAR(static_cast<double>(dropped) / total, 0.25, 0.02);
}

TEST(RelayGate, SameSeedGivesSameDecisions)
{
  RelayGate a(42);
  RelayGate b(42);
  for (int i = 0; i < 200; ++i) {
    EXPECT_EQ(a.decide(i, 0.5, 0.0), b.decide(i, 0.5, 0.0));
  }
}

TEST(RelayGate, RateLimitDropsMessagesCloserThanTheInterval)
{
  RelayGate gate(4);
  // 10 Hz limit: one message per 0.1 s
  EXPECT_EQ(gate.decide(0.00, 0.0, 10.0), Verdict::kAccept);
  EXPECT_EQ(gate.decide(0.05, 0.0, 10.0), Verdict::kDropRate);
  EXPECT_EQ(gate.decide(0.099, 0.0, 10.0), Verdict::kDropRate);
  EXPECT_EQ(gate.decide(0.10, 0.0, 10.0), Verdict::kAccept);
  EXPECT_EQ(gate.decide(0.15, 0.0, 10.0), Verdict::kDropRate);
}

TEST(RelayGate, DroppedMessagesDoNotMoveTheRateWindow)
{
  RelayGate gate(5);
  EXPECT_EQ(gate.decide(0.0, 0.0, 10.0), Verdict::kAccept);
  EXPECT_EQ(gate.decide(0.09, 0.0, 10.0), Verdict::kDropRate);
  // 0.10 s after the accepted one, not after the dropped one
  EXPECT_EQ(gate.decide(0.10, 0.0, 10.0), Verdict::kAccept);
}

TEST(MakePayload, NegativeSizeKeepsTheInput)
{
  const std::vector<uint8_t> in{1, 2, 3};
  EXPECT_EQ(roshanavi_examples::pipeline::make_payload(in, -1), in);
}

TEST(MakePayload, PadsWithZerosAndCuts)
{
  const std::vector<uint8_t> in{1, 2, 3};
  EXPECT_EQ(roshanavi_examples::pipeline::make_payload(in, 5),
    (std::vector<uint8_t>{1, 2, 3, 0, 0}));
  EXPECT_EQ(roshanavi_examples::pipeline::make_payload(in, 2), (std::vector<uint8_t>{1, 2}));
  EXPECT_TRUE(roshanavi_examples::pipeline::make_payload(in, 0).empty());
}

TEST(Fanout, AllPicksEveryOutput)
{
  FanoutSelector sel;
  EXPECT_EQ(sel.next(FanoutMode::kAll, 3), (std::vector<size_t>{0, 1, 2}));
  EXPECT_EQ(sel.next(FanoutMode::kAll, 3), (std::vector<size_t>{0, 1, 2}));
}

TEST(Fanout, RoundRobinCyclesOverTheOutputs)
{
  FanoutSelector sel;
  std::vector<size_t> seen;
  for (int i = 0; i < 7; ++i) {
    const auto picked = sel.next(FanoutMode::kRoundRobin, 3);
    ASSERT_EQ(picked.size(), 1u);
    seen.push_back(picked[0]);
  }
  EXPECT_EQ(seen, (std::vector<size_t>{0, 1, 2, 0, 1, 2, 0}));
}

TEST(Fanout, NoOutputsPicksNothing)
{
  FanoutSelector sel;
  EXPECT_TRUE(sel.next(FanoutMode::kAll, 0).empty());
  EXPECT_TRUE(sel.next(FanoutMode::kRoundRobin, 0).empty());
}

TEST(Fanout, ParseKnownAndUnknownNames)
{
  using roshanavi_examples::pipeline::parse_fanout;
  EXPECT_EQ(parse_fanout("all"), FanoutMode::kAll);
  EXPECT_EQ(parse_fanout("round_robin"), FanoutMode::kRoundRobin);
  EXPECT_FALSE(parse_fanout("random").has_value());
}

TEST(SeqTracker, CountsGapsAsLost)
{
  SeqTracker t;
  for (uint32_t seq : {0u, 1u, 2u, 5u, 6u, 10u}) {
    t.add(seq);
  }
  EXPECT_EQ(t.received(), 6u);
  EXPECT_EQ(t.lost(), 2u + 3u);
}

TEST(SeqTracker, FirstSequenceIsNotALossAndRestartIsNotEither)
{
  SeqTracker t;
  t.add(100);
  t.add(101);
  t.add(0);  // source restarted
  t.add(1);
  EXPECT_EQ(t.received(), 4u);
  EXPECT_EQ(t.lost(), 0u);
}

TEST(LatencyWindow, SummaryOfKnownSamples)
{
  LatencyWindow w(5.0, 1000);
  for (int i = 1; i <= 100; ++i) {
    w.add(1.0, i);  // 1..100 ms
  }
  const auto s = w.summarize(1.0);
  EXPECT_EQ(s.count, 100u);
  EXPECT_DOUBLE_EQ(s.mean_ms, 50.5);
  EXPECT_DOUBLE_EQ(s.p50_ms, 50.0);
  EXPECT_DOUBLE_EQ(s.p95_ms, 95.0);
  EXPECT_DOUBLE_EQ(s.max_ms, 100.0);
}

TEST(LatencyWindow, OldSamplesLeaveTheWindow)
{
  LatencyWindow w(5.0, 1000);
  w.add(0.0, 500.0);
  w.add(10.0, 7.0);
  const auto s = w.summarize(10.0);
  EXPECT_EQ(s.count, 1u);
  EXPECT_DOUBLE_EQ(s.max_ms, 7.0);
}

TEST(LatencyWindow, CapDropsTheOldestSamples)
{
  LatencyWindow w(5.0, 3);
  for (int i = 1; i <= 5; ++i) {
    w.add(1.0, i);
  }
  const auto s = w.summarize(1.0);
  EXPECT_EQ(s.count, 3u);
  EXPECT_DOUBLE_EQ(s.p50_ms, 4.0);
}

TEST(LatencyWindow, EmptyWindowHasZeroCount)
{
  LatencyWindow w(5.0, 10);
  EXPECT_EQ(w.summarize(1.0).count, 0u);
  EXPECT_DOUBLE_EQ(w.rate_hz(1.0), 0.0);
}

TEST(LatencyWindow, RateUsesTheElapsedSpanUntilTheWindowIsFull)
{
  LatencyWindow w(5.0, 1000);
  for (int i = 0; i < 20; ++i) {
    w.add(i * 0.1, 1.0);  // 10 Hz for 2 s
  }
  EXPECT_NEAR(w.rate_hz(1.9), 20.0 / 1.9, 0.01);
}

TEST(EndpointName, FirstIsPlainTheRestAreNumbered)
{
  using roshanavi_examples::pipeline::endpoint_name;
  EXPECT_EQ(endpoint_name("in", 0), "in");
  EXPECT_EQ(endpoint_name("in", 1), "in_1");
  EXPECT_EQ(endpoint_name("out", 12), "out_12");
}

TEST(SpinFor,BurnsAtLeastTheRequestedTime)
{
  const auto t0 = std::chrono::steady_clock::now();
  roshanavi_examples::pipeline::spin_for_ms(20.0);
  const auto dt = std::chrono::duration<double, std::milli>(
    std::chrono::steady_clock::now() - t0).count();
  EXPECT_GE(dt, 20.0);
  EXPECT_LT(dt, 200.0);
}
