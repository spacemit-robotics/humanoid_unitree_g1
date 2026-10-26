cmake_minimum_required(VERSION 3.16)
project(g1_hardware_offline_tests LANGUAGES C CXX)

# Standalone, opt-in tests. Production G1 remains a configuration-only package.
get_filename_component(SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../.." ABSOLUTE)
set(STAGING "${SDK_ROOT}/output/staging")
find_library(WHOLE_BODY_LIBRARY NAMES whole_body PATHS "${STAGING}/lib" NO_DEFAULT_PATH)
if(NOT WHOLE_BODY_LIBRARY)
    message(FATAL_ERROR "Build whole_body with mm in this SDK first")
endif()
find_package(yaml-cpp REQUIRED)
add_executable(test_g1_hardware_mapping test_hardware_mapping.cpp)
target_compile_features(test_g1_hardware_mapping PRIVATE cxx_std_17)
target_compile_options(test_g1_hardware_mapping PRIVATE -Wall -Wextra -Werror)
# Test-only access to mapping/core internals; no production dependency is added.
target_include_directories(test_g1_hardware_mapping PRIVATE
    "${SDK_ROOT}/components/control/whole_body/src"
    "${SDK_ROOT}/components/control/whole_body/include"
    "${STAGING}/include")
target_link_libraries(test_g1_hardware_mapping PRIVATE ${WHOLE_BODY_LIBRARY} yaml-cpp)
set_target_properties(test_g1_hardware_mapping PROPERTIES BUILD_RPATH "${STAGING}/lib")
enable_testing()
add_executable(test_g1_coupling_commands test_coupling_commands.cpp)
target_compile_features(test_g1_coupling_commands PRIVATE cxx_std_17)
target_compile_options(test_g1_coupling_commands PRIVATE -Wall -Wextra -Werror)
target_include_directories(test_g1_coupling_commands PRIVATE
    "${SDK_ROOT}/components/control/whole_body/src"
    "${SDK_ROOT}/components/control/whole_body/include"
    "${STAGING}/include")
target_link_libraries(test_g1_coupling_commands PRIVATE ${WHOLE_BODY_LIBRARY} yaml-cpp)
set_target_properties(test_g1_coupling_commands PROPERTIES BUILD_RPATH "${STAGING}/lib")
add_test(NAME g1_coupling_commands COMMAND test_g1_coupling_commands
    "${CMAKE_CURRENT_SOURCE_DIR}/../config/g1.yaml")
add_test(NAME g1_hardware_mapping COMMAND test_g1_hardware_mapping
    "${CMAKE_CURRENT_SOURCE_DIR}/../config/g1.yaml")

find_library(BEHAVIOR_LIBRARY NAMES behavior_manager PATHS "${STAGING}/lib" NO_DEFAULT_PATH)
find_library(ROBOT_BASE_LIBRARY NAMES robot_base PATHS "${STAGING}/lib" NO_DEFAULT_PATH)
if(NOT BEHAVIOR_LIBRARY OR NOT ROBOT_BASE_LIBRARY)
    message(FATAL_ERROR "Build humanoid_common with mm before running the pre-RL regression")
endif()
add_executable(test_g1_pre_rl test_pre_rl.cpp)
target_compile_features(test_g1_pre_rl PRIVATE cxx_std_17)
target_compile_options(test_g1_pre_rl PRIVATE -Wall -Wextra -Werror)
target_include_directories(test_g1_pre_rl PRIVATE
    "${SDK_ROOT}/components/control/whole_body/src"
    "${SDK_ROOT}/components/control/whole_body/include"
    "${STAGING}/include")
target_link_libraries(test_g1_pre_rl PRIVATE
    ${WHOLE_BODY_LIBRARY} ${BEHAVIOR_LIBRARY} ${ROBOT_BASE_LIBRARY} yaml-cpp)
set_target_properties(test_g1_pre_rl PROPERTIES BUILD_RPATH "${STAGING}/lib")
add_test(NAME g1_pre_rl COMMAND test_g1_pre_rl
    "${CMAKE_CURRENT_SOURCE_DIR}/../config/g1.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/data/pre_rl_feedback.yaml")

set(G1_CODEC "${SDK_ROOT}/components/peripherals/motor/src/drivers/drv_uart_rs485_20_26")
add_executable(test_g1_waist_damping test_waist_damping.cpp "${G1_CODEC}/src/rs485_20_26_protocol.c")
target_compile_features(test_g1_waist_damping PRIVATE cxx_std_17 c_std_99)
target_compile_options(test_g1_waist_damping PRIVATE -Wall -Wextra -Werror)
target_include_directories(test_g1_waist_damping PRIVATE
    "${SDK_ROOT}/components/control/whole_body/src"
    "${SDK_ROOT}/components/control/whole_body/include"
    "${STAGING}/include" "${G1_CODEC}/include")
target_link_libraries(test_g1_waist_damping PRIVATE ${WHOLE_BODY_LIBRARY} yaml-cpp)
set_target_properties(test_g1_waist_damping PROPERTIES BUILD_RPATH "${STAGING}/lib")
add_test(NAME g1_waist_damping COMMAND test_g1_waist_damping
    "${CMAKE_CURRENT_SOURCE_DIR}/../config/g1.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/data/waist_damping.csv")

add_executable(test_g1_rl_entry test_rl_entry.cpp)
target_compile_features(test_g1_rl_entry PRIVATE cxx_std_17)
target_compile_options(test_g1_rl_entry PRIVATE -Wall -Wextra -Werror)
target_include_directories(test_g1_rl_entry PRIVATE
    "${SDK_ROOT}/components/control/whole_body/src"
    "${SDK_ROOT}/components/control/whole_body/include"
    "${STAGING}/include")
target_link_libraries(test_g1_rl_entry PRIVATE ${WHOLE_BODY_LIBRARY} yaml-cpp)
set_target_properties(test_g1_rl_entry PROPERTIES BUILD_RPATH "${STAGING}/lib")
add_test(NAME g1_rl_entry COMMAND test_g1_rl_entry
    "${CMAKE_CURRENT_SOURCE_DIR}/../config/g1.yaml"
    "${CMAKE_CURRENT_SOURCE_DIR}/data/entry_observations.csv"
    "${CMAKE_CURRENT_SOURCE_DIR}/data/entry_targets.csv")
