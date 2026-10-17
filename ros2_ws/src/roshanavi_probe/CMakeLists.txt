cmake_minimum_required(VERSION 3.8)
project(roshanavi_probe)

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
find_package(rmw REQUIRED)
find_package(roshanavi_msgs REQUIRED)

# Pure statistics (no ROS): shared by the node and the unit tests.
add_library(probe_stats STATIC src/stats.cpp)
target_include_directories(probe_stats PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
set_target_properties(probe_stats PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_executable(probe src/main.cpp src/probe_node.cpp src/stats_msg.cpp)
target_link_libraries(probe probe_stats rclcpp::rclcpp rmw::rmw
  ${roshanavi_msgs_TARGETS})

install(TARGETS probe DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_stats test/test_stats.cpp)
  target_link_libraries(test_stats probe_stats)
endif()

ament_package()
