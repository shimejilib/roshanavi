// Small helpers shared by the pipeline source / relay / sink nodes (see docs/design/nodes.md).
#ifndef PIPELINE_COMMON_HPP_
#define PIPELINE_COMMON_HPP_

#include <chrono>
#include <cstdint>
#include <functional>
#include <string>

#include "rcl_interfaces/msg/parameter_descriptor.hpp"
#include "rclcpp/rclcpp.hpp"

namespace roshanavi_examples
{
namespace pipeline
{

inline double steady_sec()
{
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

// A numeric parameter may arrive as an integer ("-p process_ms:=5") or a float ("5.0"); both
// are accepted, so the node declares such parameters with dynamic typing.
inline double number_of(const rclcpp::Parameter & p)
{
  return p.get_type() == rclcpp::ParameterType::PARAMETER_INTEGER ?
         static_cast<double>(p.as_int()) : p.as_double();
}

inline bool is_number(const rclcpp::Parameter & p)
{
  return p.get_type() == rclcpp::ParameterType::PARAMETER_INTEGER ||
         p.get_type() == rclcpp::ParameterType::PARAMETER_DOUBLE;
}

// Declares a number parameter that accepts int and double, with a description for the UI.
inline double declare_number(
  rclcpp::Node & node, const std::string & name, double default_value, const std::string & doc)
{
  rcl_interfaces::msg::ParameterDescriptor desc;
  desc.description = doc;
  desc.dynamic_typing = true;
  node.declare_parameter(name, rclcpp::ParameterValue(default_value), desc);
  return number_of(node.get_parameter(name));
}

inline rcl_interfaces::msg::ParameterDescriptor describe(const std::string & doc, bool read_only = false)
{
  rcl_interfaces::msg::ParameterDescriptor desc;
  desc.description = doc;
  desc.read_only = read_only;
  return desc;
}

// Stable default seed from a node name (so two relays do not drop the same messages).
inline uint64_t seed_from_name(const std::string & name)
{
  return static_cast<uint64_t>(std::hash<std::string>{}(name));
}

}  // namespace pipeline
}  // namespace roshanavi_examples

#endif  // PIPELINE_COMMON_HPP_
