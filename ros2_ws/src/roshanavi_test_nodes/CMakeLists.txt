cmake_minimum_required(VERSION 3.8)
project(roshanavi_test_nodes)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

# rate_talker: publishes String (or Image) at a fixed rate.
# slow_listener: subscribes and sleeps sleep_ms in every callback; prints latency once a second.
foreach(exe rate_talker slow_listener)
  add_executable(${exe} src/${exe}.cpp)
  target_link_libraries(${exe} rclcpp::rclcpp ${std_msgs_TARGETS} ${sensor_msgs_TARGETS})
  install(TARGETS ${exe} DESTINATION lib/${PROJECT_NAME})
endforeach()

ament_package()
