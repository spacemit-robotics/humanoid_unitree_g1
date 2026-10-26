/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * @file test_mnn_sim.cpp
 * @brief Headless MNN simulation using the SDK adapter and policy executor.
 */

#include <mujoco/mujoco.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>  // NOLINT(build/c++17)
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "policy_adapter/policy_adapter.h"
#include "rl_service.h"
#include "robot_base.h"

int main(int argc, char **argv) {
    if (argc < 3) {
        std::cerr << "Usage: test_mnn_sim CONFIG OUTPUT [world|heading|initial_heading] "
            "[transpose] [initial_yaw_rad] [gestures|fast|stand|stairs|action_name|none] [policy] "
            "[gait_frequency_center_probe] [--diagnose-guard] [--cancel-after=SECONDS]\n";
        return 2;
    }
    try {
        if (mj_version() != mjVERSION_HEADER)
            throw std::runtime_error("MuJoCo headers/runtime version mismatch");
        const auto yaml = robot_base::YamlFile::Load(argv[1]);
        const auto root = yaml.ToAbsPath(yaml.Read<std::string>("robot_base.robot_dir").value());
        const std::string policy_name = argc > 7 ? argv[7] : "walk_mnn";
        const auto loaded = rl_policy::LoadPolicyConfigFromYaml(argv[1], policy_name, root);
        auto adapter_config = behavior_manager::policy_adapter::LoadConfig(argv[1], policy_name, root);
        const bool gestures = argc > 6 && std::string(argv[6]) == "gestures";
        const bool fast = argc > 6 && std::string(argv[6]) == "fast";
        const bool standing = argc > 6 && std::string(argv[6]) == "stand";
        const bool stairs = argc > 6 && std::string(argv[6]) == "stairs";
        const std::string dance_action = argc > 6 && std::string(argv[6]) != "none" &&
            policy_name == "dance_mnn" ? argv[6] : "";
        if (argc > 3) adapter_config.stance_motion.orientation_frame = argv[3];
        if (argc > 4) adapter_config.stance_motion.transpose_rotation = std::stoi(argv[4]) != 0;
        bool diagnose_guard = false;
        double cancel_after = -1.0;
        for (int i = 8; i < argc; ++i) {
            if (std::string(argv[i]) == "--diagnose-guard") {
                diagnose_guard = true;
            } else if (std::string(argv[i]).rfind("--cancel-after=", 0) == 0) {
                cancel_after = std::stod(std::string(argv[i]).substr(15));
                if (!std::isfinite(cancel_after) || cancel_after < 0)
                    throw std::runtime_error("Invalid cancellation time");
            } else if (i == 8) {
                adapter_config.history_actor.frequency_center = std::stod(argv[i]);
            } else {
                throw std::runtime_error("Unknown simulation argument");
            }
        }
        rl_policy::PolicyExecutor primary;
        primary.Init(loaded.exec_cfg);
        auto adapter = behavior_manager::policy_adapter::Create(adapter_config, loaded.exec_cfg);
        char error[1024] = {};
        const auto xml = root + "/resources/xml/" + (stairs ? "scene_stairs.xml" : "scene.xml");
        std::unique_ptr<mjModel, decltype(&mj_deleteModel)> model(
            mj_loadXML(xml.c_str(), nullptr, error, sizeof(error)), mj_deleteModel);
        if (!model) throw std::runtime_error(error);
        std::unique_ptr<mjData, decltype(&mj_deleteData)> data(mj_makeData(model.get()), mj_deleteData);
        if (model->nu != 29 || model->nq != 36) throw std::runtime_error("Unexpected robot layout");
        model->opt.timestep = 0.001;
        data->qpos[2] = 0.79;
        const double initial_yaw = argc > 5 ? std::stod(argv[5]) : 0.0;
        if (!std::isfinite(initial_yaw)) throw std::runtime_error("Invalid initial yaw");
        data->qpos[3] = std::cos(initial_yaw * 0.5);
        data->qpos[4] = data->qpos[5] = 0.0;
        data->qpos[6] = std::sin(initial_yaw * 0.5);
        for (int i = 0; i < 29; ++i) data->qpos[7 + i] = loaded.exec_cfg.rl_default_pos[i];
        mj_forward(model.get(), data.get());
        robot_base::RobotData robot = robot_base::RobotData::Create(29);
        const auto read_state = [&]() {
            std::copy_n(data->qpos, 3, robot.base_pos.begin());
            std::copy_n(data->qpos + 3, 4, robot.base_quat.begin());
            std::copy_n(data->qvel, 6, robot.base_vel.begin());
            std::copy_n(data->qpos + 7, 29, robot.joint_pos.begin());
            std::copy_n(data->qvel + 6, 29, robot.joint_vel.begin());
            robot.UpdateImuData();
        };
        read_state();
        adapter->Reset(robot);
        std::vector<double> target = loaded.exec_cfg.rl_default_pos;
        auto kp = loaded.kp;
        auto kd = loaded.kd;
        using Operation = robot_base::InteractionRequest::Operation;
        using Phase = robot_base::InteractionStatus::Phase;
        struct Event { double time; std::string name; };
        const std::vector<Event> events = {{5, "shake_hand"}, {30, "wave_above_head"},
            {40, "wave_under_head"}, {47, "blow_kiss_with_right_hand"}, {55, "clamp"},
            {62, "wave_above_head"}, {63, ""}, {67, "wave_above_head"}, {67.4, ""},
            {70, "wave_under_head"}};
        std::size_t event_index = 0;
        int completed = 0;
        Phase previous_phase = Phase::IDLE;
        const std::string policy_base = "rl_policy.onnx_infer.policies." + policy_name;
        const auto lower = yaml.Read<std::vector<double>>(policy_base + ".target_position_lower").value();
        const auto upper = yaml.Read<std::vector<double>>(policy_base + ".target_position_upper").value();
        std::ofstream output(argv[2]);
        if (!output) throw std::runtime_error("Cannot open output");
        output << "time,x,y,z,roll,pitch,yaw,vx,vy,wz,mode,obs3,obs4,obs5,obs6,obs7,obs8"
            ",interaction,phase,kp15,kd15\n";
        std::vector<double> previous_network_offset(29, 0.0);
        int takeover_frames = 0;
        double max_tilt = 0.0;
        double min_height = 10.0;
        bool guard_failed = false;
        const int duration = gestures ? 90 : dance_action == "rhythm" ? 125 : 60;
        for (int step = 0; step < duration * 1000; ++step) {
            const double t = step * model->opt.timestep;
            if (step % 20 == 0) {
                read_state();
                std::array<double, 3> command = {};
                if (gestures) {
                    if (t >= 78 && t < 82) command[0] = 0.5;
                } else if (stairs) {
                    if (t >= 5 && t < 30) command[0] = 0.5;
                } else if (policy_name != "dance_mnn" && !standing) {
                    if (t >= 5 && t < 13) command[0] = fast ? 2.0 : 0.5;
                    if (t >= 18 && t < 24) command[0] = -0.4;
                    if (t >= 29 && t < 35) command[1] = 0.35;
                    if (t >= 40 && t < 45) command[2] = 0.5;
                    if (t >= 50 && t < 55) command[0] = 0.5;
                }
                auto &executor = adapter->SelectExecutor(command, primary);
                if (!dance_action.empty() && event_index == 0 && t >= 5) {
                    robot_base::InteractionRequest request;
                    request.sequence = ++event_index;
                    request.action = dance_action;
                    request.operation = Operation::START;
                    adapter->HandleInteractionRequest(request, t);
                    if (!adapter->GetInteractionStatus().request_accepted)
                        throw std::runtime_error("Dance request rejected");
                }
                if (!dance_action.empty() && event_index == 1 && cancel_after >= 0 && t >= 5 + cancel_after) {
                    robot_base::InteractionRequest request;
                    request.sequence = ++event_index;
                    request.operation = Operation::CANCEL;
                    adapter->HandleInteractionRequest(request, t);
                }
                if (gestures && event_index < events.size() && t >= events[event_index].time) {
                    const auto &event = events[event_index];
                    robot_base::InteractionRequest request;
                    request.sequence = ++event_index;
                    request.action = event.name;
                    request.operation = event.name.empty() ? Operation::CANCEL : Operation::START;
                    adapter->HandleInteractionRequest(request, t);
                    if (!adapter->GetInteractionStatus().request_accepted)
                        throw std::runtime_error("Interaction rejected: " + event.name);
                }
                adapter->PrepareInputs(robot, t, executor);
                Eigen::VectorXf obs;
                executor.AssembleObs(robot.gyro, robot.rpy, command[0], command[1], command[2],
                    robot.joint_pos, robot.joint_vel, robot.base_quat, {}, loaded.rl_dt, obs);
                for (int i = 0; policy_name == "walk_mnn" && i < 29; ++i) {
                    if (std::abs(obs[67 + i] - previous_network_offset[i]) > 1e-5)
                        throw std::runtime_error("Model history contains a composed target");
                    if (std::abs(obs[38 + i] - robot.joint_vel[i]) > 1e-5)
                        throw std::runtime_error("Interaction changed measured velocity observations");
                    if (i < 12 && std::abs(obs[9 + i] - robot.joint_pos[i]) > 1e-5)
                        throw std::runtime_error("Interaction changed leg position observations");
                }
                const auto observed_phase = adapter->GetInteractionStatus().phase;
                if (observed_phase == Phase::PLAYING || observed_phase == Phase::HOLDING) {
                    const auto &settings = adapter_config.stance_motion;
                    for (std::size_t i = 0; i < settings.interaction_joint_indices.size(); ++i) {
                        if (std::abs(obs[9 + settings.interaction_joint_indices[i]] -
                                settings.interaction_neutral_positions[i]) > 1e-5)
                            throw std::runtime_error("Interaction neutral observation mismatch");
                    }
                }
                std::vector<double> action;
                executor.Infer(obs, action);
                for (int i = 0; policy_name == "walk_mnn" && i < 29; ++i)
                    previous_network_offset[i] = action[i] * loaded.exec_cfg.action_scale[i];
                adapter->OnAction(action);
                kp = loaded.kp;
                kd = loaded.kd;
                adapter->ApplyJointGains(kp, kd);
                primary.MapActionToTargetPos(action, target);
                for (int i = 0; i < 29; ++i) target[i] = std::clamp(target[i], lower[i], upper[i]);
                const auto interaction = adapter->GetInteractionStatus();
                if (gestures && (interaction.phase == Phase::PLAYING || interaction.phase == Phase::HOLDING)) {
                    ++takeover_frames;
                    for (int i = 12; i < 15; ++i) {
                        if (std::abs(target[i]) > 1e-6 || std::abs(kp[i] - 200.0) > 1e-6 ||
                            std::abs(kd[i] - 5.0) > 1e-6)
                            throw std::runtime_error("Waist trajectory/gain takeover mismatch");
                    }
                    for (int i = 0; i < 12; ++i) {
                        if (std::abs(kp[i] - loaded.kp[i]) > 1e-6 ||
                            std::abs(kd[i] - loaded.kd[i]) > 1e-6)
                            throw std::runtime_error("Gesture changed leg gains");
                    }
                }
                if (interaction.phase == Phase::FINISHED && previous_phase != Phase::FINISHED)
                    ++completed;
                previous_phase = interaction.phase;
                const auto mode = adapter->ActiveModelName();
                output << t << ',' << robot.base_pos[0] << ',' << robot.base_pos[1] << ','
                    << robot.base_pos[2] << ',' << robot.rpy[0] << ',' << robot.rpy[1] << ','
                    << robot.rpy[2] << ',' << command[0] << ',' << command[1] << ',' << command[2]
                    << ',' << mode;
                for (int i = 3; i < 9; ++i) output << ',' << obs[i];
                output << ',' << interaction.action << ',' << static_cast<int>(interaction.phase)
                    << ',' << kp[15] << ',' << kd[15] << '\n';
                max_tilt = std::max({max_tilt, std::abs(robot.rpy[0]), std::abs(robot.rpy[1])});
                min_height = std::min(min_height, robot.base_pos[2]);
                if (!guard_failed && (max_tilt > 0.7 || min_height < 0.5)) {
                    guard_failed = true;
                    std::cerr << "FAIL t=" << t << " z=" << robot.base_pos[2]
                        << " rpy=" << robot.rpy[0] << ',' << robot.rpy[1] << ',' << robot.rpy[2]
                        << " mode=" << mode << '\n';
                    // Offline diagnosis only: keep recording the ideal simulation
                    // to distinguish a guard crossing from a sustained fall.
                    // This test still fails; runtime/hardware guards are unchanged.
                    if (!diagnose_guard) return 1;
                }
            }
            // Same ideal joint PD used by the SDK MuJoCo backend, held at 500 Hz.
            if (step % 2 == 0) {
                for (int i = 0; i < 29; ++i) {
                    data->ctrl[i] = kp[i] * (target[i] - data->qpos[7 + i])
                        - kd[i] * data->qvel[6 + i];
                }
            }
            mj_step(model.get(), data.get());
        }
        if (gestures && (event_index != events.size() || completed != 8 || takeover_frames == 0))
            throw std::runtime_error("Incomplete gesture playback/cancellation sequence");
        if (!dance_action.empty() && completed != 1)
            throw std::runtime_error("Dance did not complete and return to standby");
        std::cout << (guard_failed ? "FAIL " : "PASS ") << duration
            << " s free-standing sim, min_height=" << min_height
            << " max_tilt=" << max_tilt << " final_xy=" << robot.base_pos[0]
            << ',' << robot.base_pos[1] << " final_height=" << robot.base_pos[2]
            << " final_rp=" << robot.rpy[0] << ',' << robot.rpy[1]
            << " completed_gestures=" << completed << '\n';
        if (guard_failed) return 1;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
