// Unit tests for the pure image functions used by image_filter and blob_detector.
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "roshanavi_examples/image_ops.hpp"

using roshanavi_examples::find_blobs;
using roshanavi_examples::GrayImage;
using roshanavi_examples::sobel_edges;
using roshanavi_examples::to_gray;

namespace
{

GrayImage blank(uint32_t w, uint32_t h, uint8_t value = 0)
{
  GrayImage img;
  img.width = w;
  img.height = h;
  img.pixels.assign(static_cast<size_t>(w) * h, value);
  return img;
}

void fill_rect(GrayImage & img, uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint8_t v)
{
  for (uint32_t y = y0; y < y0 + h; ++y) {
    for (uint32_t x = x0; x < x0 + w; ++x) {
      img.pixels[static_cast<size_t>(y) * img.width + x] = v;
    }
  }
}

}  // namespace

TEST(ToGray, Rgb8UsesLumaWeights) {
  // One red, one green, one blue, one white pixel.
  const std::vector<uint8_t> data = {255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255};
  const auto result = to_gray("rgb8", 4, 1, 12, data);
  ASSERT_TRUE(result.ok) << result.error;
  EXPECT_EQ(result.image.width, 4u);
  EXPECT_EQ(result.image.height, 1u);
  EXPECT_EQ(result.image.pixels, (std::vector<uint8_t>{76, 150, 29, 255}));
}

TEST(ToGray, Bgr8SwapsChannels) {
  const std::vector<uint8_t> data = {0, 0, 255};  // red in BGR order
  const auto result = to_gray("bgr8", 1, 1, 3, data);
  ASSERT_TRUE(result.ok);
  EXPECT_EQ(result.image.pixels[0], 76);
}

TEST(ToGray, HonoursRowPadding) {
  // 2x2 mono8 with step 4 (2 bytes of padding per row).
  const std::vector<uint8_t> data = {1, 2, 99, 99, 3, 4, 99, 99};
  const auto result = to_gray("mono8", 2, 2, 4, data);
  ASSERT_TRUE(result.ok);
  EXPECT_EQ(result.image.pixels, (std::vector<uint8_t>{1, 2, 3, 4}));
}

TEST(ToGray, RejectsUnknownEncodingAndShortBuffers) {
  EXPECT_FALSE(to_gray("yuv422", 2, 2, 4, std::vector<uint8_t>(8)).ok);
  const auto short_buffer = to_gray("rgb8", 4, 4, 12, std::vector<uint8_t>(10));
  EXPECT_FALSE(short_buffer.ok);
  EXPECT_FALSE(short_buffer.error.empty());
  EXPECT_FALSE(to_gray("rgb8", 4, 1, 4, std::vector<uint8_t>(12)).ok);  // step < width * 3
}

TEST(Sobel, FlatImageHasNoEdgesAndKeepsSize) {
  const auto edges = sobel_edges(blank(8, 6, 120));
  EXPECT_EQ(edges.width, 8u);
  EXPECT_EQ(edges.height, 6u);
  for (auto v : edges.pixels) {
    EXPECT_EQ(v, 0);
  }
}

TEST(Sobel, VerticalStepGivesStrongEdgeOnlyAtTheBoundary) {
  GrayImage img = blank(10, 5);
  fill_rect(img, 5, 0, 5, 5, 200);  // left half dark, right half bright
  const auto edges = sobel_edges(img);
  EXPECT_EQ(edges.at(4, 2), 255);  // next to the boundary: clamped maximum
  EXPECT_EQ(edges.at(5, 2), 255);
  EXPECT_EQ(edges.at(2, 2), 0);   // far from it: flat
  EXPECT_EQ(edges.at(8, 2), 0);
  EXPECT_EQ(edges.at(0, 2), 0);   // border is always 0
}

TEST(Sobel, TinyImageIsAllZero) {
  const auto edges = sobel_edges(blank(2, 2, 255));
  EXPECT_EQ(edges.pixels, (std::vector<uint8_t>{0, 0, 0, 0}));
}

TEST(Blobs, FindsTwoSeparateRegionsLargestFirst) {
  GrayImage img = blank(40, 30);
  fill_rect(img, 2, 2, 5, 4, 220);     // 20 pixels
  fill_rect(img, 20, 10, 10, 10, 250);  // 100 pixels
  const auto blobs = find_blobs(img, 200, 1, 10);
  ASSERT_EQ(blobs.size(), 2u);
  EXPECT_EQ(blobs[0].area, 100u);
  EXPECT_EQ(blobs[0].x_min, 20u);
  EXPECT_EQ(blobs[0].y_max, 19u);
  EXPECT_DOUBLE_EQ(blobs[0].mean, 250.0);
  EXPECT_DOUBLE_EQ(blobs[0].cx, 24.5);
  EXPECT_EQ(blobs[1].area, 20u);
}

TEST(Blobs, ThresholdMinAreaAndMaxCount) {
  GrayImage img = blank(30, 10);
  fill_rect(img, 0, 0, 3, 3, 210);   // 9 pixels
  fill_rect(img, 10, 0, 5, 5, 150);  // below the threshold
  fill_rect(img, 20, 0, 4, 4, 255);  // 16 pixels
  EXPECT_EQ(find_blobs(img, 200, 1, 10).size(), 2u);
  EXPECT_EQ(find_blobs(img, 200, 10, 10).size(), 1u);   // min_area drops the small one
  EXPECT_EQ(find_blobs(img, 100, 1, 10).size(), 3u);    // lower threshold finds all three
  EXPECT_EQ(find_blobs(img, 100, 1, 1).size(), 1u);     // max_blobs
  EXPECT_TRUE(find_blobs(blank(5, 5), 1, 1, 10).empty());
}

TEST(Blobs, DiagonalPixelsAreSeparate) {
  // 4-neighbourhood: pixels touching only at a corner are different blobs.
  GrayImage img = blank(4, 4);
  img.pixels[0] = 255;
  img.pixels[5] = 255;
  EXPECT_EQ(find_blobs(img, 200, 1, 10).size(), 2u);
}

TEST(Blobs, LargeRegionDoesNotOverflowTheStack) {
  const auto blobs = find_blobs(blank(1000, 1000, 255), 200, 1, 10);
  ASSERT_EQ(blobs.size(), 1u);
  EXPECT_EQ(blobs[0].area, 1000000u);
}
