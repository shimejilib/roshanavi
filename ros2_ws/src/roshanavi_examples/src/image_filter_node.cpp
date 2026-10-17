// image_filter: a sample C++ (rclcpp) node for roshanavi.
//
// What it does
//   Subscribes  image        (sensor_msgs/msg/Image, rgb8 / bgr8 / rgba8 / bgra8 / mono8)
//   Publishes   image_gray   (sensor_msgs/msg/Image, mono8): the same picture in grayscale
//               image_edges  (sensor_msgs/msg/Image, mono8): edge strength (Sobel filter)
//   Topic names are relative, so they follow the node's namespace and can be remapped:
//     ros2 run roshanavi_examples image_filter --ros-args -r image:=/camera/image
//
// Parameters (can be changed while running, e.g. from the roshanavi map or `ros2 param set`)
//   keep_stamp (bool, default true)
//       true:  the outputs copy header.stamp of the input image. A scenario can then pair
//              input and output by stamp (latency mode "header.stamp").
//       false: the outputs are stamped with the current time. Pairing then has to use
//              the receive order (latency mode "order"), like many real nodes.
//   process_delay_ms (int, default 0)
//       Sleep this long in every callback to simulate slow processing. With 詳細計測モード
//       (tracing) on, roshanavi then shows "processing is behind" for this node.
//
// Why C++? roshanavi's tracing mode measures receive count, processed count and
// processing time for rclcpp nodes; Python (rclpy) nodes only report the receive count.
// The image samples are C++ so both kinds can be compared side by side.
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <utility>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"

#include "roshanavi_examples/image_ops.hpp"

namespace roshanavi_examples
{

class ImageFilter : public rclcpp::Node
{
public:
  ImageFilter()
  : Node("image_filter")
  {
    // declare_parameter() registers the parameter with a default value; the UI lists it.
    declare_parameter<bool>("keep_stamp", true);
    declare_parameter<int>("process_delay_ms", 0);

    // QoS: the subscriber is best effort (SensorDataQoS), which receives from reliable
    // AND best-effort publishers. The publishers are reliable (depth 10), which every
    // subscriber can receive from. This combination never causes a QoS mismatch.
    const auto out_qos = rclcpp::QoS(10).reliable();
    gray_pub_ = create_publisher<sensor_msgs::msg::Image>("image_gray", out_qos);
    edges_pub_ = create_publisher<sensor_msgs::msg::Image>("image_edges", out_qos);
    sub_ = create_subscription<sensor_msgs::msg::Image>(
      "image", rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::Image::ConstSharedPtr msg) {on_image(*msg);});
    RCLCPP_INFO(get_logger(), "image_filter ready: %s -> %s, %s",
      sub_->get_topic_name(), gray_pub_->get_topic_name(), edges_pub_->get_topic_name());
  }

private:
  void on_image(const sensor_msgs::msg::Image & in)
  {
    // 1) Optional artificial slowness (see process_delay_ms above).
    const auto delay_ms = get_parameter("process_delay_ms").as_int();
    if (delay_ms > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
    }

    // 2) Convert to grayscale. Bad input is logged (at most every 5 s) and skipped.
    GrayResult gray = to_gray(in.encoding, in.width, in.height, in.step, in.data);
    if (!gray.ok) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "skipping image: %s",
        gray.error.c_str());
      return;
    }

    // 3) Edges from the grayscale picture.
    GrayImage edges = sobel_edges(gray.image);

    // 4) Header: keep the input stamp, or stamp with "now" (see keep_stamp above).
    std_msgs::msg::Header header = in.header;
    if (!get_parameter("keep_stamp").as_bool()) {
      header.stamp = now();
    }
    gray_pub_->publish(to_message(header, std::move(gray.image)));
    edges_pub_->publish(to_message(header, std::move(edges)));
  }

  static sensor_msgs::msg::Image to_message(const std_msgs::msg::Header & header, GrayImage img)
  {
    sensor_msgs::msg::Image out;
    out.header = header;
    out.width = img.width;
    out.height = img.height;
    out.encoding = "mono8";
    out.is_bigendian = false;
    out.step = img.width;  // 1 byte per pixel, no padding
    out.data = std::move(img.pixels);
    return out;
  }

  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr gray_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr edges_pub_;
};

}  // namespace roshanavi_examples

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<roshanavi_examples::ImageFilter>());
  rclcpp::shutdown();
  return 0;
}
