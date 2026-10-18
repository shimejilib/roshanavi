// heavy_source / heavy_sink: big sensor messages for measuring how heavy a topic roshanavi can
// monitor (scripts/bench_heavy.py, docs/design/measurement.md "重いデータの計測の限界").
//
// heavy_source publishes `out` (remap it): sensor_msgs/msg/Image (rgb8, width x height) or
//   sensor_msgs/msg/PointCloud2 (x y z intensity float32, `points` points) at rate_hz.
//   header.stamp = now, header.frame_id = a counting sequence number (as text).
// heavy_sink subscribes `in` with the same QoS, measures (now - stamp) per message and the
//   sequence gaps, and publishes ~/stats (roshanavi_examples_msgs/msg/SinkStats, path "heavy").
//   It never touches the data, so it costs next to nothing.
//
// Parameters (both): kind (image | pointcloud), qos (best_effort | reliable), depth (5).
//   source: width (1920), height (1080), points (100000), rate_hz (30).
//   sink:   window_s (5), stats_period_s (1).
// Composable (roshanavi_examples::HeavySource / HeavySink) and standalone (heavy_source / heavy_sink).
#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
#include "roshanavi_examples_msgs/msg/sink_stats.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/msg/point_field.hpp"

#include "pipeline_common.hpp"
#include "roshanavi_examples/pipeline_logic.hpp"

namespace roshanavi_examples
{

namespace pl = roshanavi_examples::pipeline;
using SinkStats = roshanavi_examples_msgs::msg::SinkStats;

namespace
{

rclcpp::QoS make_qos(const std::string & qos, int depth)
{
  rclcpp::QoS out(static_cast<size_t>(depth));
  if (qos == "best_effort") {
    out.best_effort();
  } else if (qos == "reliable") {
    out.reliable();
  } else {
    throw std::invalid_argument("qos must be best_effort or reliable, not '" + qos + "'");
  }
  return out;
}

sensor_msgs::msg::Image make_image(int width, int height)
{
  sensor_msgs::msg::Image img;
  img.width = static_cast<uint32_t>(width);
  img.height = static_cast<uint32_t>(height);
  img.encoding = "rgb8";
  img.step = img.width * 3;
  img.data.resize(static_cast<size_t>(img.step) * img.height);
  for (size_t i = 0; i < img.data.size(); ++i) {
    img.data[i] = static_cast<uint8_t>((i * 7) ^ (i >> 9));
  }
  return img;
}

sensor_msgs::msg::PointCloud2 make_cloud(int points)
{
  sensor_msgs::msg::PointCloud2 cloud;
  cloud.width = static_cast<uint32_t>(points);
  cloud.height = 1;
  const char * names[4] = {"x", "y", "z", "intensity"};
  for (uint32_t i = 0; i < 4; ++i) {
    sensor_msgs::msg::PointField f;
    f.name = names[i];
    f.offset = i * 4;
    f.datatype = sensor_msgs::msg::PointField::FLOAT32;
    f.count = 1;
    cloud.fields.push_back(f);
  }
  cloud.point_step = 16;
  cloud.row_step = cloud.point_step * cloud.width;
  cloud.is_dense = true;
  cloud.data.resize(static_cast<size_t>(cloud.row_step));
  for (size_t i = 0; i < cloud.data.size(); ++i) {
    cloud.data[i] = static_cast<uint8_t>((i * 13) ^ (i >> 7));
  }
  return cloud;
}

}  // namespace

class HeavySource : public rclcpp::Node
{
public:
  explicit HeavySource(const rclcpp::NodeOptions & options)
  : Node("heavy_source", options)
  {
    const auto kind = declare_parameter<std::string>("kind", "image");
    const auto qos = declare_parameter<std::string>("qos", "best_effort");
    const auto depth = declare_parameter<int>("depth", 5);
    const auto width = declare_parameter<int>("width", 1920);
    const auto height = declare_parameter<int>("height", 1080);
    const auto points = declare_parameter<int>("points", 100000);
    const auto rate = pl::declare_number(*this, "rate_hz", 30.0, "messages per second");
    if (kind == "image") {
      image_ = make_image(width, height);
      image_pub_ = create_publisher<sensor_msgs::msg::Image>("out", make_qos(qos, depth));
    } else if (kind == "pointcloud") {
      cloud_ = make_cloud(points);
      cloud_pub_ = create_publisher<sensor_msgs::msg::PointCloud2>("out", make_qos(qos, depth));
    } else {
      throw std::invalid_argument("kind must be image or pointcloud, not '" + kind + "'");
    }
    if (rate <= 0.0) {
      throw std::invalid_argument("rate_hz must be positive");
    }
    timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / rate), [this]() {tick();});
  }

private:
  void tick()
  {
    const auto stamp = now();
    const auto seq = std::to_string(seq_++);
    if (image_pub_) {
      auto msg = std::make_unique<sensor_msgs::msg::Image>(image_);
      msg->header.stamp = stamp;
      msg->header.frame_id = seq;
      image_pub_->publish(std::move(msg));
    } else {
      auto msg = std::make_unique<sensor_msgs::msg::PointCloud2>(cloud_);
      msg->header.stamp = stamp;
      msg->header.frame_id = seq;
      cloud_pub_->publish(std::move(msg));
    }
  }

  sensor_msgs::msg::Image image_;
  sensor_msgs::msg::PointCloud2 cloud_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
  uint64_t seq_ = 0;
};

class HeavySink : public rclcpp::Node
{
public:
  explicit HeavySink(const rclcpp::NodeOptions & options)
  : Node("heavy_sink", options)
  {
    const auto kind = declare_parameter<std::string>("kind", "image");
    const auto qos = declare_parameter<std::string>("qos", "best_effort");
    const auto depth = declare_parameter<int>("depth", 5);
    const auto window = pl::declare_number(*this, "window_s", 5.0, "statistics window");
    const auto period = pl::declare_number(*this, "stats_period_s", 1.0, "publish ~/stats this often");
    latency_ = std::make_unique<pl::LatencyWindow>(window, 20000);
    window_sec_ = window;
    if (kind == "image") {
      image_sub_ = create_subscription<sensor_msgs::msg::Image>(
        "in", make_qos(qos, depth),
        [this](sensor_msgs::msg::Image::ConstSharedPtr m) {on_message(m->header);});
    } else if (kind == "pointcloud") {
      cloud_sub_ = create_subscription<sensor_msgs::msg::PointCloud2>(
        "in", make_qos(qos, depth),
        [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr m) {on_message(m->header);});
    } else {
      throw std::invalid_argument("kind must be image or pointcloud, not '" + kind + "'");
    }
    stats_pub_ = create_publisher<SinkStats>("~/stats", rclcpp::QoS(10));
    timer_ = create_wall_timer(std::chrono::duration<double>(period), [this]() {publish();});
  }

private:
  void on_message(const std_msgs::msg::Header & header)
  {
    const double ms = (now() - rclcpp::Time(header.stamp)).seconds() * 1000.0;
    latency_->add(pl::steady_sec(), ms);
    try {
      seq_.add(static_cast<uint32_t>(std::stoul(header.frame_id)));
    } catch (const std::exception &) {
      // a frame without a sequence number is counted by the rate only
    }
  }

  void publish()
  {
    const double t = pl::steady_sec();
    const auto s = latency_->summarize(t);
    SinkStats out;
    out.header.stamp = now();
    out.sink = get_name();
    out.window_sec = window_sec_;
    roshanavi_examples_msgs::msg::PathStats row;
    row.path = "heavy";
    row.received = seq_.received();
    row.lost = seq_.lost();
    row.rate_hz = latency_->rate_hz(t);
    row.latency_ms_mean = static_cast<float>(s.mean_ms);
    row.latency_ms_p50 = static_cast<float>(s.p50_ms);
    row.latency_ms_p95 = static_cast<float>(s.p95_ms);
    row.latency_ms_max = static_cast<float>(s.max_ms);
    out.paths.push_back(row);
    stats_pub_->publish(out);
  }

  double window_sec_ = 5.0;
  std::unique_ptr<pl::LatencyWindow> latency_;
  pl::SeqTracker seq_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_sub_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_sub_;
  rclcpp::Publisher<SinkStats>::SharedPtr stats_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace roshanavi_examples

RCLCPP_COMPONENTS_REGISTER_NODE(roshanavi_examples::HeavySource)
RCLCPP_COMPONENTS_REGISTER_NODE(roshanavi_examples::HeavySink)
