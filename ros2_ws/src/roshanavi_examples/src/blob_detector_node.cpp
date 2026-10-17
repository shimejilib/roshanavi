// blob_detector: a sample C++ (rclcpp) node for roshanavi.
//
// What it does
//   Subscribes  image       (sensor_msgs/msg/Image, rgb8 / bgr8 / rgba8 / bgra8 / mono8)
//   Publishes   detections  (vision_msgs/msg/Detection2DArray): one Detection2D per bright blob
//                 - bbox.center.position.x/y, bbox.size_x/size_y: the blob's bounding box (pixels)
//                 - results[0].hypothesis.class_id = "blob"
//                 - results[0].hypothesis.score    = mean brightness of the blob / 255 (0..1)
//                 - header = the input image's header (same stamp: latency by header.stamp)
//               Every image produces one message, also when nothing is found (empty array),
//               so a scenario can check "the number of detections" frame by frame.
//
// Parameters (can be changed while running)
//   threshold (int, default 200)      pixels at least this bright (0..255) belong to a blob
//   min_area (int, default 30)        smaller blobs are ignored (noise)
//   max_detections (int, default 20)  keep at most this many (largest first)
//
// Try it: with roshanavi's perception demo, image_filter's /camera/gray feeds this node;
// the two moving discs of the sample video give two detections.
#include <algorithm>
#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "vision_msgs/msg/detection2_d_array.hpp"

#include "roshanavi_examples/image_ops.hpp"

namespace roshanavi_examples
{

class BlobDetector : public rclcpp::Node
{
public:
  BlobDetector()
  : Node("blob_detector")
  {
    declare_parameter<int>("threshold", 200);
    declare_parameter<int>("min_area", 30);
    declare_parameter<int>("max_detections", 20);

    // Best-effort subscriber (receives from any publisher), reliable publisher (any
    // subscriber can receive from it): see image_filter for the reasoning.
    pub_ = create_publisher<vision_msgs::msg::Detection2DArray>(
      "detections", rclcpp::QoS(10).reliable());
    sub_ = create_subscription<sensor_msgs::msg::Image>(
      "image", rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::Image::ConstSharedPtr msg) {on_image(*msg);});
    RCLCPP_INFO(get_logger(), "blob_detector ready: %s -> %s",
      sub_->get_topic_name(), pub_->get_topic_name());
  }

private:
  void on_image(const sensor_msgs::msg::Image & in)
  {
    const GrayResult gray = to_gray(in.encoding, in.width, in.height, in.step, in.data);
    if (!gray.ok) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "skipping image: %s",
        gray.error.c_str());
      return;
    }
    // Parameters are read for every image, so changes apply immediately.
    const auto threshold = std::clamp<int64_t>(get_parameter("threshold").as_int(), 0, 255);
    const auto min_area = std::max<int64_t>(get_parameter("min_area").as_int(), 1);
    const auto max_count = std::max<int64_t>(get_parameter("max_detections").as_int(), 0);
    const auto blobs = find_blobs(gray.image, static_cast<uint8_t>(threshold),
        static_cast<uint32_t>(min_area), static_cast<size_t>(max_count));

    vision_msgs::msg::Detection2DArray out;
    out.header = in.header;
    for (size_t i = 0; i < blobs.size(); ++i) {
      const Blob & blob = blobs[i];
      vision_msgs::msg::Detection2D det;
      det.header = in.header;
      det.id = std::to_string(i);
      // Bounding box: centre and size in pixels (x to the right, y down).
      const double width = blob.x_max - blob.x_min + 1.0;
      const double height = blob.y_max - blob.y_min + 1.0;
      det.bbox.center.position.x = blob.x_min + width / 2.0;
      det.bbox.center.position.y = blob.y_min + height / 2.0;
      det.bbox.size_x = width;
      det.bbox.size_y = height;
      vision_msgs::msg::ObjectHypothesisWithPose hypothesis;
      hypothesis.hypothesis.class_id = "blob";
      hypothesis.hypothesis.score = blob.mean / 255.0;
      det.results.push_back(hypothesis);
      out.detections.push_back(det);
    }
    pub_->publish(out);
  }

  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
  rclcpp::Publisher<vision_msgs::msg::Detection2DArray>::SharedPtr pub_;
};

}  // namespace roshanavi_examples

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<roshanavi_examples::BlobDetector>());
  rclcpp::shutdown();
  return 0;
}
