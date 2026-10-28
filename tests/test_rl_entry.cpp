/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * @file test_rl_entry.cpp
 * @brief Replay recorded RL entry commands through the real core and fake devices.
 */
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <yaml-cpp/yaml.h>

#include "core/whole_body_core.h"

namespace {

void Require(bool value, const std::string &message) {
    if (!value) throw std::runtime_error(message);
}

using Record = std::unordered_map<std::string, std::string>;

std::vector<std::string> Split(const std::string &line) {
    std::istringstream stream(line);
    std::vector<std::string> columns;
    std::string token;
    while (std::getline(stream, token, ',')) columns.push_back(token);
    return columns;
}

std::vector<Record> LoadRecords(const std::string &path) {
    std::ifstream stream(path);
    Require(stream.good(), "open capture: " + path);
    std::string line;
    std::getline(stream, line);
    const auto header = Split(line);
    std::vector<Record> records;
    while (std::getline(stream, line)) {
        const auto columns = Split(line);
        Require(columns.size() == header.size(), "capture field count");
        Record record;
        for (size_t i = 0; i < header.size(); ++i) record.emplace(header[i], columns[i]);
        records.push_back(record);
    }
    Require(!records.empty(), "recorded inference frames required");
    return records;
}

double Number(const Record &record, const std::string &field) {
    const double value = std::stod(record.at(field));
    Require(std::isfinite(value), "finite capture field: " + field);
    return value;
}

class ReplayDevices final : public whole_body::DeviceManager {
    public:
    int Init() override { return 0; }
    int Read(std::vector<motor_state> *motors, imu_data *imu,
        whole_body::DeviceFeedbackStatus *status) override {
        *motors = feedback;
        *imu = {};
        imu->quat[0] = 1.0f;
        status->motor_received.assign(29, true);
        status->motor_fresh.assign(29, true);
        status->motor_age_s.assign(29, 0.0);
        status->motor_timestamp_s.assign(29, feedback_time_s);
        status->imu_received = status->imu_fresh = true;
        return whole_body::DEVICE_READ_OK;
    }
    int Write(const std::vector<motor_cmd> &commands) override {
        written = commands;
        return 0;
    }
    void Shutdown() override {}
    std::vector<motor_state> feedback = std::vector<motor_state>(29);
    std::vector<motor_cmd> written;
    double feedback_time_s = 1.0;
};

struct ReplayRuntime {
    explicit ReplayRuntime(const whole_body::RuntimeConfig &config) {
        for (const auto &coupling : config.couplings)
            mappings.push_back(std::make_unique<whole_body::CoupledMapping>(coupling));
        auto fake = std::make_unique<ReplayDevices>();
        devices = fake.get();
        core = std::make_unique<whole_body::WholeBodyCore>(config, std::move(fake));
        Require(core->Init() == WHOLE_BODY_OK, "replay initialization");
    }
    std::vector<std::unique_ptr<whole_body::CoupledMapping>> mappings;
    ReplayDevices *devices = nullptr;
    std::unique_ptr<whole_body::WholeBodyCore> core;
    double peak_write_us = 0.0;
    double previous_feedback_time_s = -1.0;
    std::array<double, 29> damping_velocity{};
};

size_t JointIndex(const whole_body::RuntimeConfig &config, const std::string &name) {
    for (size_t i = 0; i < config.joints.size(); ++i)
        if (config.joints[i].name == name) return i;
    throw std::runtime_error("unknown joint: " + name);
}

size_t MotorIndex(const whole_body::RuntimeConfig &config, const std::string &name) {
    for (size_t i = 0; i < config.motors.size(); ++i)
        if (config.motors[i].name == name) return i;
    throw std::runtime_error("unknown motor: " + name);
}

void SetFeedback(const whole_body::RuntimeConfig &config,
    const std::array<double, 29> &position, const std::array<double, 29> &velocity,
    ReplayRuntime *runtime) {
    auto *devices = runtime->devices;
    auto set_motor = [&](size_t index, double q, double v) {
        const auto &motor = config.motors[index];
        devices->feedback[index].pos = static_cast<float>(motor.polarity * q + motor.zero_offset);
        devices->feedback[index].vel = static_cast<float>(motor.polarity * v);
    };
    for (size_t i = 0; i < config.joints.size(); ++i) {
        const auto &joint = config.joints[i];
        if (joint.mapping == "direct")
            set_motor(MotorIndex(config, joint.motors[0]), position[i], velocity[i]);
    }
    for (size_t index = 0; index < config.couplings.size(); ++index) {
        const auto &coupling = config.couplings[index];
        auto &mapping = *runtime->mappings[index];
        const size_t first = JointIndex(config, coupling.joints[0]);
        const size_t second = JointIndex(config, coupling.joints[1]);
        const std::array<double, 2> q{position[first], position[second]};
        std::array<double, 2> motor_q, motor_v;
        Require(mapping.JointToMotor(q, &motor_q) && mapping.JointVelocityToMotor(q,
            {velocity[first], velocity[second]}, &motor_v), "reconstruct measured motor state");
        for (size_t side = 0; side < 2; ++side)
            set_motor(MotorIndex(config, coupling.motors[side]), motor_q[side], motor_v[side]);
    }
}

void CheckPolicyHold(const whole_body::RuntimeConfig &config, const YAML::Node &policies) {
    for (const char *name : {"stand", "walk_mjlab", "walk_rlgym"}) {
        const auto policy = policies[name];
        ReplayRuntime runtime(config);
        std::array<double, 29> position{}, velocity{};
        whole_body_joint_command command{};
        command.num_dof = 29;
        command.enable = true;
        command.mode = WHOLE_BODY_MODE_RL;
        command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
        for (size_t i = 0; i < 29; ++i) {
            position[i] = command.position[i] = policy["rl_default_pos"][i].as<double>();
            command.kp[i] = policy["kp"][i].as<double>();
            command.kd[i] = policy["kd"][i].as<double>();
            Require(policy["target_position_lower"][i].as<double>() == config.joints[i].position_limit[0] &&
                policy["target_position_upper"][i].as<double>() == config.joints[i].position_limit[1],
                std::string(name) + " final target bounds must match the hardware configuration");
        }
        const double expected_entry = std::string(name) == "stand" ? 0.5 : 0.0;
        Require(policy["entry_target_transition_duration"].as<double>() == expected_entry,
            std::string(name) + " must use its own configured RL entry transition");
        SetFeedback(config, position, velocity, &runtime);
        whole_body_state state{};
        Require(runtime.core->Read(&state) == WHOLE_BODY_OK, "hold feedback");
        Require(runtime.core->Write(command, 1.0) == WHOLE_BODY_OK,
            std::string(name) + " hold command: " + runtime.core->LastError());
        for (size_t i : {13U, 14U}) {
            const auto &sent = runtime.devices->written[i];
            Require(sent.kp > 0.0f && sent.kd > 0.0f && sent.trq_des == 0.0f,
                "waist uses native PD without host residual in RL");
        }
        for (size_t i : {4U, 5U, 10U, 11U}) {
            const auto &sent = runtime.devices->written[i];
            Require(sent.kp > 0.0f && sent.kd > 0.0f && sent.trq_des == 0.0f,
                "ankle uses projected native PD without host residual");
        }
    }
}

void CheckWristCommands(const whole_body::RuntimeConfig &config, const YAML::Node &policy) {
    for (size_t i = 0; i < config.motors.size(); ++i) {
        const bool small_wrist = i == 20 || i == 21 || i == 27 || i == 28;
        Require(config.motors[i].command_limits.estimated_torque_max == 0.0,
            "native-PD motors do not use the unverified host estimated-torque trip");
        if (small_wrist)
            Require(config.joints[i].torque_limit == 5.0 &&
                config.motors[i].command_limits.kp_max == 0.0 &&
                config.motors[i].command_limits.kd_max == 0.0,
                "retain wrist feedforward limit without invented gain trips");
    }
    struct WristSample {
        size_t joint;
        double position;
        double velocity;
        double target;
    };
    // Wrist effort regression cases. Values are inference-time observations,
    // not synchronous driver feedback; they exercise the estimated-effort boundary.
    const std::array<WristSample, 5> samples = {{{21, 0.008281092, 0.006135918, 0.32616148127},
        {21, 0.009767135, 0.012271836, 0.3159814850175},
        {28, -0.016813854, 0.079766937, -0.3376329},
        {21, -0.000035953, 0.0, 0.2994045712225},
        {28, -0.01396161, 0.018407755, -0.4366087847}}};
    for (const auto &sample : samples) {
        std::array<double, 29> position{}, velocity{};
        whole_body_joint_command command{};
        command.num_dof = 29;
        command.enable = true;
        command.mode = WHOLE_BODY_MODE_RL;
        command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
        for (size_t i = 0; i < 29; ++i) {
            position[i] = command.position[i] = policy["rl_default_pos"][i].as<double>();
            command.kp[i] = policy["kp"][i].as<double>();
            command.kd[i] = policy["kd"][i].as<double>();
        }
        position[sample.joint] = sample.position;
        velocity[sample.joint] = sample.velocity;
        command.position[sample.joint] = sample.target;
        for (bool estimate_gate : {true, false}) {
            auto replay_config = config;
            if (estimate_gate) replay_config.motors[sample.joint].command_limits.estimated_torque_max = 5.0;
            ReplayRuntime runtime(replay_config);
            SetFeedback(replay_config, position, velocity, &runtime);
            whole_body_state state{};
            Require(runtime.core->Read(&state) == WHOLE_BODY_OK, "wrist replay feedback");
            const int result = runtime.core->Write(command, 1.0);
            if (estimate_gate) {
                Require(result != WHOLE_BODY_OK &&
                    runtime.core->LastError().find("estimated_torque") != std::string::npos,
                    "5 Nm estimated-effort limit rejects this fixture");
                continue;
            }
            Require(result == WHOLE_BODY_OK, "corrected wrist command: " + runtime.core->LastError());
            const auto &sent = runtime.devices->written[sample.joint];
            Require(sent.mode == MOTOR_MODE_HYBRID && sent.trq_des == 0.0f &&
                std::abs(sent.kp - command.kp[sample.joint]) < 1.0e-5 &&
                std::abs(sent.kd - command.kd[sample.joint]) < 1.0e-5 &&
                std::abs(sent.pos_des - config.motors[sample.joint].polarity * sample.target) < 1.0e-6,
                "preserve native PD target and gains, do not replace it with host torque");
            auto invalid = command;
            invalid.torque[sample.joint] = 5.01;
            Require(runtime.core->Write(invalid, 1.002) != WHOLE_BODY_OK &&
                runtime.core->LastError().find(".torque=") != std::string::npos,
                "feedforward torque above 5 Nm still rejected");
            for (const auto &motor : runtime.devices->written)
                Require(motor.mode == MOTOR_MODE_IDLE, "invalid command still disables all motors");
        }
    }
    std::cout << "PASS five wrist releases: old gate rejects, corrected config accepts; feedforward guard retained\n";
}

void CheckWaistProjection(const whole_body::RuntimeConfig &config, const YAML::Node &policy) {
    const auto &coupling = config.couplings.back();
    Require(coupling.joints[0] == "waist_pitch_joint", "calibration table waist order");
    size_t checked = 0;
    ReplayRuntime runtime(config);
    for (double pitch : {-0.15, 0.0, 0.15}) {
        for (double roll : {-0.12, 0.0, 0.12}) {
            for (const auto &offset : std::array<std::array<double, 2>, 3>{{
                {0.06, 0.0}, {0.0, -0.05}, {-0.04, 0.03}}}) {
                std::array<double, 29> position{}, velocity{};
                whole_body_joint_command command{};
                command.num_dof = 29;
                command.enable = true;
                command.mode = WHOLE_BODY_MODE_RL;
                command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
                for (size_t i = 0; i < 29; ++i) {
                    position[i] = command.position[i] = policy["rl_default_pos"][i].as<double>();
                    command.kp[i] = policy["kp"][i].as<double>();
                    command.kd[i] = policy["kd"][i].as<double>();
                }
                position[14] = pitch;
                position[13] = roll;
                command.position[14] = pitch + offset[0];
                command.position[13] = roll + offset[1];
                SetFeedback(config, position, velocity, &runtime);
                runtime.devices->feedback_time_s = 1.0 + checked * 0.002;
                whole_body_state state{};
                Require(runtime.core->Read(&state) == WHOLE_BODY_OK, "waist projection feedback");
                Require(runtime.core->Write(command, runtime.devices->feedback_time_s) == WHOLE_BODY_OK,
                    "waist projected command: " + runtime.core->LastError());
                std::array<double, 2> motor_effort{}, joint_effort{};
                for (size_t side = 0; side < 2; ++side) {
                    const size_t motor = MotorIndex(config, coupling.motors[side]);
                    const auto &sent = runtime.devices->written[motor];
                    motor_effort[side] = config.motors[motor].polarity * sent.kp *
                        (sent.pos_des - runtime.devices->feedback[motor].pos);
                    Require(sent.trq_des == 0.0f && sent.kd > 0.0f,
                        "projection retains native damping without host residual");
                }
                Require(runtime.mappings.back()->MotorTorqueToJoint(
                    {state.position[14], state.position[13]}, motor_effort, &joint_effort),
                    "reverse native proportional effort");
                for (size_t side = 0; side < 2; ++side) {
                    const size_t joint = JointIndex(config, coupling.joints[side]);
                    Require(std::abs(joint_effort[side] - command.kp[joint] *
                        (command.position[joint] - state.position[joint])) < 2.0e-5,
                        "projected target preserves full joint proportional effort");
                }
                ++checked;
            }
        }
    }
    std::cout << "PASS waist projected proportional effort: " << checked << " real-table poses/targets\n";
}

double Replay(const whole_body::RuntimeConfig &config, const YAML::Node &policy,
    const Record &observation, const Record &target, ReplayRuntime *runtime,
    bool walking = false, bool rlgym = false) {
    Require(Number(observation, "release_sequence") == Number(target, "release_sequence"),
        "matching policy release");
    Require(Number(target, "wall_time_s") >= Number(observation, "wall_time_s") &&
        Number(target, "wall_time_s") - Number(observation, "wall_time_s") < 0.01,
        "observation and applied target belong to the same release");
    std::array<double, 29> position{}, velocity{};
    whole_body_joint_command command{};
    command.num_dof = 29;
    command.enable = true;
    command.mode = WHOLE_BODY_MODE_RL;
    command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
    for (size_t i = 0; i < 29; ++i) {
        position[i] = policy["rl_default_pos"][i].as<double>();
        command.position[i] = Number(target, "target_pos_" + std::to_string(i));
        command.kp[i] = policy["kp"][i].as<double>();
        command.kd[i] = policy["kd"][i].as<double>();
        if (rlgym) {
            // Apply the existing StateRL final-target clamp to the fixture command.
            // No physical limit or command rejection is relaxed in WholeBodyCore.
            command.position[i] = std::clamp(command.position[i],
                policy["target_position_lower"][i].as<double>(),
                policy["target_position_upper"][i].as<double>());
        }
    }
    for (size_t i = 0; i < policy["action_joint_index"].size(); ++i) {
        const size_t joint = policy["action_joint_index"][i].as<size_t>();
        position[joint] += Number(observation, "obs_" + std::to_string((walking && !rlgym ? 11 : 9) + i));
        const size_t velocity_offset = rlgym ? 21 : (walking ? 40 : 38);
        velocity[joint] = Number(observation, "obs_" + std::to_string(velocity_offset + i)) /
            (rlgym ? 0.05 : 1.0);
    }
    auto *fake = runtime->devices;
    auto &core = *runtime->core;
    SetFeedback(config, position, velocity, runtime);
    fake->feedback_time_s = Number(observation, "wall_time_s");
    whole_body_state state{};
    Require(core.Read(&state) == WHOLE_BODY_OK, "replay read: " + core.LastError());
    for (size_t i = 0; i < 29; ++i) {
        Require(std::abs(state.position[i] - position[i]) < 2.0e-6, "position round trip");
        Require(std::abs(state.velocity[i] - velocity[i]) < 2.0e-6, "velocity round trip");
        const double elapsed = fake->feedback_time_s - runtime->previous_feedback_time_s;
        const double tau = config.joints[i].impedance.velocity_filter_time_constant_s;
        if (tau <= 0.0 || runtime->previous_feedback_time_s < 0.0 || elapsed < 0.0 ||
            elapsed > config.feedback_timeout_s) {
            runtime->damping_velocity[i] = state.velocity[i];
        } else if (elapsed > 0.0) {
            runtime->damping_velocity[i] += (1.0 - std::exp(-elapsed / tau)) *
                (state.velocity[i] - runtime->damping_velocity[i]);
        }
    }
    runtime->previous_feedback_time_s = fake->feedback_time_s;
    auto &right = *runtime->mappings.at(1);
    if (!walking)
        Require(!right.CheckJointTarget({command.position[10], command.position[11]}),
            "recorded PD reference has no accepted position inverse");
    const auto write_start = std::chrono::steady_clock::now();
    const int result = core.Write(command, Number(observation, "wall_time_s"));
    const double write_us = std::chrono::duration<double, std::micro>(
        std::chrono::steady_clock::now() - write_start).count();
    runtime->peak_write_us = std::max(runtime->peak_write_us, write_us);
    Require(result == WHOLE_BODY_OK, "captured RL command rejected: " + core.LastError());
    Require(fake->written.size() == 29, "complete motor command");
    double peak = 0.0;
    for (size_t coupling_index = 0; coupling_index < config.couplings.size(); ++coupling_index) {
        const auto &coupling = config.couplings[coupling_index];
        const size_t first = JointIndex(config, coupling.joints[0]);
        const auto &impedance = config.joints[first].impedance;
        const auto mode = impedance.rl_mode.value_or(impedance.mode);
        if (mode == whole_body::ImpedanceMode::kMotor ||
            mode == whole_body::ImpedanceMode::kMotorProjected) continue;
        auto &mapping = *runtime->mappings[coupling_index];
        std::array<double, 2> measured{}, desired_torque{}, expected{};
        for (size_t side = 0; side < 2; ++side) {
            const size_t joint = JointIndex(config, coupling.joints[side]);
            measured[side] = state.position[joint];
            desired_torque[side] = std::clamp(command.kp[joint] *
                (command.position[joint] - measured[side]) -
                    command.kd[joint] * runtime->damping_velocity[joint],
                -config.joints[joint].torque_limit, config.joints[joint].torque_limit);
        }
        Require(mapping.JointTorqueToMotor(measured, desired_torque, &expected), "expected motor torque");
        for (size_t side = 0; side < 2; ++side) {
            const size_t index = MotorIndex(config, coupling.motors[side]);
            const auto &sent = fake->written[index];
            if (mode == whole_body::ImpedanceMode::kSoftware) {
                Require(sent.kp == 0.0f && sent.kd == 0.0f, "software PD has no duplicate motor gains");
            } else {
                Require(sent.kd > 0.0f, "split PD retains native damping");
                if (impedance.motor_kp_max > 0.0)
                    Require(sent.kp > 0.0f, "split PD retains native stiffness");
            }
            const double total = sent.trq_des +
                sent.kp * (sent.pos_des - fake->feedback[index].pos) + sent.kd *
                (sent.vel_des - fake->feedback[index].vel);
            Require(std::abs(total - config.motors[index].polarity * expected[side]) < 2.0e-5,
                "combined motor PD and feedforward match configured joint PD");
            peak = std::max(peak, std::abs(total));
        }
    }
    if (!walking) std::cout << "recorded_entry=" << observation.at("wall_time_s")
                << " accepted=29 peak_coupled_motor_torque_nm=" << peak << '\n';
    return peak;
}

}  // namespace

int main(int argc, char **argv) {
    try {
        Require(argc == 4 || argc == 5,
            "usage: test_g1_rl_entry g1.yaml observation.csv target.csv [walk_mjlab|walk_rlgym]");
        const auto config = whole_body::LoadConfig(argv[1]);
        const bool rlgym = argc == 5 && std::string(argv[4]) == "walk_rlgym";
        const bool walking = rlgym || (argc == 5 && std::string(argv[4]) == "walk_mjlab");
        Require(argc == 4 || walking, "supported captured policy");
        const auto policies = YAML::LoadFile(argv[1])["rl_policy"]["onnx_infer"]["policies"];
        const auto policy = policies[rlgym ? "walk_rlgym" : (walking ? "walk_mjlab" : "stand")];
        Require(config.num_dof == 29 && !config.read_only && config.allow_actuation,
            "replay the deployed actuation configuration without changing protection limits");
        CheckPolicyHold(config, policies);
        CheckWristCommands(config, policies["walk_mjlab"]);
        CheckWaistProjection(config, policies["walk_mjlab"]);
        const auto observations = LoadRecords(argv[2]);
        const auto targets = LoadRecords(argv[3]);
        ReplayRuntime runtime(config);
        if (!walking) {
            Require(observations.size() == 3 && targets.size() == 3, "three regression entries");
            for (size_t i = 0; i < observations.size(); ++i)
                Replay(config, policy, observations[i], targets[i], &runtime);
        } else {
            size_t next = 0;
            size_t replayed = 0;
            double peak = 0.0;
            for (size_t index = 0; index < targets.size(); ++index) {
                const auto &target = targets[index];
                // A policy reload restarts release_sequence within the same log file.
                while (next < observations.size() &&
                    (Number(observations[next], "wall_time_s") < Number(target, "wall_time_s") - 0.01 ||
                        Number(observations[next], "release_sequence") != Number(target, "release_sequence")))
                    ++next;
                Require(next < observations.size(), "applied target has a matching observation");
                peak = std::max(peak, Replay(config, policy, observations[next], target, &runtime, true, rlgym));
                ++replayed;
            }
            std::cout << (rlgym ? "walk_rlgym" : "walk_mjlab") << " replayed_frames=" << replayed
                << " available_frames=" << targets.size()
                << " peak_coupled_motor_torque_nm=" << peak
                << " peak_fake_write_us=" << runtime.peak_write_us << '\n';
        }
        std::cout << "PASS recorded RL entries; fake devices only, no robot motion\n";
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
