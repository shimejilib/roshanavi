// Implementation of the pure image functions (see include/roshanavi_examples/image_ops.hpp).
#include "roshanavi_examples/image_ops.hpp"

#include <algorithm>
#include <cstdlib>
#include <utility>

namespace roshanavi_examples
{

namespace
{

// Where R, G and B are inside one pixel, and how many bytes a pixel has.
struct Layout
{
  int channels;
  int r, g, b;
};

bool layout_of(const std::string & encoding, Layout & out)
{
  if (encoding == "rgb8") {out = {3, 0, 1, 2}; return true;}
  if (encoding == "bgr8") {out = {3, 2, 1, 0}; return true;}
  if (encoding == "rgba8") {out = {4, 0, 1, 2}; return true;}
  if (encoding == "bgra8") {out = {4, 2, 1, 0}; return true;}
  if (encoding == "mono8") {out = {1, 0, 0, 0}; return true;}
  return false;
}

}  // namespace

GrayResult to_gray(
  const std::string & encoding, uint32_t width, uint32_t height, uint32_t step,
  const std::vector<uint8_t> & data)
{
  GrayResult result;
  Layout layout{};
  if (!layout_of(encoding, layout)) {
    result.error = "unsupported encoding '" + encoding + "' (use rgb8, bgr8, rgba8, bgra8 or mono8)";
    return result;
  }
  // Check the buffer before reading it: a broken message must not crash the node.
  const size_t row_bytes = static_cast<size_t>(width) * layout.channels;
  if (step < row_bytes || data.size() < static_cast<size_t>(step) * height) {
    result.error = "image data is smaller than width x height x channels";
    return result;
  }
  result.image.width = width;
  result.image.height = height;
  result.image.pixels.resize(static_cast<size_t>(width) * height);
  for (uint32_t y = 0; y < height; ++y) {
    const uint8_t * row = data.data() + static_cast<size_t>(y) * step;
    for (uint32_t x = 0; x < width; ++x) {
      const uint8_t * px = row + static_cast<size_t>(x) * layout.channels;
      // Integer luma: (299 R + 587 G + 114 B) / 1000, rounded.
      const uint32_t luma = layout.channels == 1 ? px[0] :
        (299u * px[layout.r] + 587u * px[layout.g] + 114u * px[layout.b] + 500u) / 1000u;
      result.image.pixels[static_cast<size_t>(y) * width + x] = static_cast<uint8_t>(luma);
    }
  }
  result.ok = true;
  return result;
}

GrayImage sobel_edges(const GrayImage & gray)
{
  GrayImage edges;
  edges.width = gray.width;
  edges.height = gray.height;
  edges.pixels.assign(gray.pixels.size(), 0);
  if (gray.width < 3 || gray.height < 3) {
    return edges;  // too small for a 3x3 neighbourhood
  }
  for (uint32_t y = 1; y + 1 < gray.height; ++y) {
    for (uint32_t x = 1; x + 1 < gray.width; ++x) {
      // Horizontal change (gx) and vertical change (gy) around (x, y).
      const int gx =
        -gray.at(x - 1, y - 1) + gray.at(x + 1, y - 1) +
        -2 * gray.at(x - 1, y) + 2 * gray.at(x + 1, y) +
        -gray.at(x - 1, y + 1) + gray.at(x + 1, y + 1);
      const int gy =
        -gray.at(x - 1, y - 1) - 2 * gray.at(x, y - 1) - gray.at(x + 1, y - 1) +
        gray.at(x - 1, y + 1) + 2 * gray.at(x, y + 1) + gray.at(x + 1, y + 1);
      const int magnitude = std::min(255, std::abs(gx) + std::abs(gy));
      edges.pixels[static_cast<size_t>(y) * gray.width + x] = static_cast<uint8_t>(magnitude);
    }
  }
  return edges;
}

std::vector<Blob> find_blobs(
  const GrayImage & gray, uint8_t threshold, uint32_t min_area, size_t max_blobs)
{
  std::vector<Blob> blobs;
  std::vector<uint8_t> visited(gray.pixels.size(), 0);
  std::vector<std::pair<uint32_t, uint32_t>> stack;  // explicit stack: no recursion depth limit

  for (uint32_t sy = 0; sy < gray.height; ++sy) {
    for (uint32_t sx = 0; sx < gray.width; ++sx) {
      const size_t start = static_cast<size_t>(sy) * gray.width + sx;
      if (visited[start] || gray.pixels[start] < threshold) {
        continue;
      }
      // Flood fill one region starting at (sx, sy).
      Blob blob{sx, sy, sx, sy, 0, 0.0, 0.0, 0.0};
      double sum = 0.0, sum_x = 0.0, sum_y = 0.0;
      visited[start] = 1;
      stack.assign(1, {sx, sy});
      while (!stack.empty()) {
        const auto [x, y] = stack.back();
        stack.pop_back();
        const uint8_t value = gray.at(x, y);
        ++blob.area;
        sum += value;
        sum_x += x;
        sum_y += y;
        blob.x_min = std::min(blob.x_min, x);
        blob.x_max = std::max(blob.x_max, x);
        blob.y_min = std::min(blob.y_min, y);
        blob.y_max = std::max(blob.y_max, y);
        // Visit the 4 neighbours (left, right, up, down) that are bright and new.
        const std::pair<int64_t, int64_t> next[4] = {
          {x - 1LL, y}, {x + 1LL, y}, {x, y - 1LL}, {x, y + 1LL}};
        for (const auto & [nx, ny] : next) {
          if (nx < 0 || ny < 0 || nx >= gray.width || ny >= gray.height) {
            continue;
          }
          const size_t idx = static_cast<size_t>(ny) * gray.width + static_cast<size_t>(nx);
          if (!visited[idx] && gray.pixels[idx] >= threshold) {
            visited[idx] = 1;
            stack.emplace_back(static_cast<uint32_t>(nx), static_cast<uint32_t>(ny));
          }
        }
      }
      if (blob.area >= min_area) {
        blob.mean = sum / blob.area;
        blob.cx = sum_x / blob.area;
        blob.cy = sum_y / blob.area;
        blobs.push_back(blob);
      }
    }
  }
  std::sort(blobs.begin(), blobs.end(), [](const Blob & a, const Blob & b) {
      return a.area > b.area;
    });
  if (blobs.size() > max_blobs) {
    blobs.resize(max_blobs);
  }
  return blobs;
}

}  // namespace roshanavi_examples
