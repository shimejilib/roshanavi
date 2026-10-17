// Pure image processing used by the sample nodes image_filter and blob_detector.
//
// Nothing in here knows about ROS: the functions take plain pixel buffers, so they
// can be unit-tested with gtest (test/test_image_ops.cpp) without starting a node.
// The nodes (src/*_node.cpp) only convert between ROS messages and these types.
//
// Why no OpenCV? The sample nodes are teaching material: a few dozen lines of plain
// C++ show exactly what "grayscale" and "edges" mean, and the package needs no
// extra libraries. Real projects would normally use cv_bridge + OpenCV.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace roshanavi_examples
{

// One channel, 8 bits per pixel, rows stored one after another without padding.
struct GrayImage
{
  uint32_t width = 0;
  uint32_t height = 0;
  std::vector<uint8_t> pixels;  // size == width * height

  uint8_t at(uint32_t x, uint32_t y) const {return pixels[static_cast<size_t>(y) * width + x];}
};

// Result of to_gray(): either an image, or an error message for the log.
struct GrayResult
{
  bool ok = false;
  GrayImage image;
  std::string error;
};

// Convert a sensor_msgs/Image style buffer to grayscale.
//   encoding: "rgb8", "bgr8", "rgba8", "bgra8" or "mono8" (others are rejected)
//   step:     bytes per row in `data` (may be larger than width * channels)
// Uses the usual luma weights 0.299 R + 0.587 G + 0.114 B.
GrayResult to_gray(
  const std::string & encoding, uint32_t width, uint32_t height, uint32_t step,
  const std::vector<uint8_t> & data);

// Edge strength with the 3x3 Sobel operator: |gx| + |gy|, clamped to 255.
// The 1-pixel border has no full neighbourhood and is set to 0.
GrayImage sobel_edges(const GrayImage & gray);

// A bright region found by find_blobs().
struct Blob
{
  uint32_t x_min = 0, y_min = 0, x_max = 0, y_max = 0;  // bounding box (inclusive)
  uint32_t area = 0;                                    // number of pixels
  double mean = 0.0;                                    // mean brightness 0..255
  double cx = 0.0, cy = 0.0;                            // centre of the pixels
};

// Find connected regions (4-neighbourhood) of pixels >= threshold that have at
// least min_area pixels. Sorted by area, largest first; at most max_blobs.
std::vector<Blob> find_blobs(
  const GrayImage & gray, uint8_t threshold, uint32_t min_area, size_t max_blobs);

}  // namespace roshanavi_examples
