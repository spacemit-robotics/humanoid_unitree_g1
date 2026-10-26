cmake_minimum_required(VERSION 3.16)
project(g1_mnn_sim_test LANGUAGES CXX)
get_filename_component(SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../../.." ABSOLUTE)
set(STAGING "${SDK_ROOT}/output/staging")
find_package(Eigen3 REQUIRED)
find_package(yaml-cpp REQUIRED)
find_path(MUJOCO_INCLUDE_DIR mujoco/mujoco.h
    HINTS "${MUJOCO_ROOT}/include" "${STAGING}/include" REQUIRED)
find_library(MUJOCO_LIBRARY mujoco HINTS "${STAGING}/lib" REQUIRED)
foreach(LIB rl behavior_manager robot_base)
    find_library(${LIB}_LIBRARY ${LIB} HINTS "${STAGING}/lib" NO_DEFAULT_PATH REQUIRED)
endforeach()
add_executable(test_mnn_sim test_mnn_sim.cpp)
target_compile_features(test_mnn_sim PRIVATE cxx_std_17)
target_compile_options(test_mnn_sim PRIVATE -Wall -Wextra)
target_include_directories(test_mnn_sim PRIVATE "${STAGING}/include"
    "${SDK_ROOT}/application/native/humanoid_common/src/behavior_manager"
    "${MUJOCO_INCLUDE_DIR}")
target_link_libraries(test_mnn_sim PRIVATE Eigen3::Eigen yaml-cpp
    ${rl_LIBRARY} ${behavior_manager_LIBRARY} ${robot_base_LIBRARY} ${MUJOCO_LIBRARY})
set_target_properties(test_mnn_sim PROPERTIES BUILD_RPATH "${STAGING}/lib")
