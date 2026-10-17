cmake_minimum_required(VERSION 3.8)
project(roshanavi_examples)

# Sample nodes bundled with roshanavi (tutorial, demo and test targets).
#   C++ (rclcpp): image_filter, blob_detector   -> tracing shows receive + processing
#   Python (rclpy): audio_level, state_machine  -> tracing shows the receive count only

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
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(vision_msgs REQUIRED)

# Pure image functions (no ROS): shared by both image nodes and the unit tests.
add_library(image_ops STATIC src/image_ops.cpp)
target_include_directories(image_ops PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
set_target_properties(image_ops PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_executable(image_filter src/image_filter_node.cpp)
target_link_libraries(image_filter image_ops rclcpp::rclcpp ${sensor_msgs_TARGETS})

add_executable(blob_detector src/blob_detector_node.cpp)
target_link_libraries(blob_detector image_ops rclcpp::rclcpp ${sensor_msgs_TARGETS}
  ${vision_msgs_TARGETS})

install(TARGETS image_filter blob_detector DESTINATION lib/${PROJECT_NAME})

# Python nodes: the module (importable for tests) + `ros2 run` entry scripts.
ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS scripts/audio_level scripts/state_machine DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_image_ops test/test_image_ops.cpp)
  target_link_libraries(test_image_ops image_ops)
endif()

ament_package()
