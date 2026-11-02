/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * @file test_pre_rl.cpp
 * @brief Actual SDK pre-RL FSM and command mapping with in-memory devices only.
 */
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <yaml-cpp/yaml.h>

#include "behavior_manager.h"
#include "core/whole_body_core.h"

namespace {

void Require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

class FakeDevices final : public whole_body::DeviceManager {
    public:
    int Init() override { return 0; }
    int Read(std::vector<motor_state> *motors, imu_data *imu,
        whole_body::DeviceFeedbackStatus *status) override {
        *motors = feedback;
        *imu = sensor;
        status->motor_received.assign(feedback.size(), true);
        status->motor_fresh.assign(feedback.size(), true);
        status->motor_age_s.assign(feedback.size(), 0.0);
        status->imu_received = status->imu_fresh = true;
        return whole_body::DEVICE_READ_OK;
    }
    int Write(const std::vector<motor_cmd> &commands) override {
        written = commands;
        return 0;
    }
    void Shutdown() override {}
    std::vector<motor_state> feedback = std::vector<motor_state>(29);
    imu_data sensor{};
    std::vector<motor_cmd> written;
};

whole_body_mode Mode(behavior_manager::StateName state) {
    using behavior_manager::StateName;
    switch (state) {
    case StateName::POWER_OFF: return WHOLE_BODY_MODE_POWER_OFF;
    case StateName::DAMP: return WHOLE_BODY_MODE_DAMP;
    case StateName::HOME: return WHOLE_BODY_MODE_HOME;
    case StateName::ZERO: return WHOLE_BODY_MODE_ZERO;
    default: throw std::runtime_error("test must never enter RL or SAFETY");
    }
}

template <class T>
size_t Index(const std::vector<T> &items, const std::string &name) {
    const auto found = std::find_if(items.begin(), items.end(),
        [&](const auto &item) { return item.name == name; });
    Require(found != items.end(), "unknown joint/motor " + name);
    return static_cast<size_t>(found - items.begin());
}

class PreRlTest {
    public:
    PreRlTest(const std::string &yaml_path, const std::string &fixture_path, bool hanging_ankle = false)
        : config_(whole_body::LoadConfig(yaml_path)), yaml_(YAML::LoadFile(yaml_path)), manager_(yaml_path) {
        Require(!config_.read_only && config_.allow_actuation, "operator actuation must be configured");
        Require(config_.num_dof == 29 && std::abs(config_.cycle_s - 0.002) < 1e-12, "29 DOF at 500 Hz");
        auto devices = std::make_unique<FakeDevices>();
        fake_ = devices.get();
        const auto fixture = YAML::LoadFile(fixture_path);
        Require(fixture["raw_motor_positions"].size() == 29, "29 recorded raw positions required");
        for (size_t i = 0; i < 29; ++i)
            fake_->feedback[i].pos = fixture["raw_motor_positions"][i].as<float>();
        for (size_t i = 0; i < 4; ++i) fake_->sensor.quat[i] = fixture["torso_quaternion"][i].as<float>();
        for (const auto &coupling : config_.couplings)
            mappings_.push_back(std::make_unique<whole_body::CoupledMapping>(coupling));
        const auto home = yaml_["behavior_manager"]["home"];
        for (size_t i = 0; i < config_.joints.size(); ++i) {
            Require(home["target_position_lower"][i].as<double>() == config_.joints[i].position_limit[0] &&
                home["target_position_upper"][i].as<double>() == config_.joints[i].position_limit[1],
                "HOME and hardware must use the same joint envelope");
        }
        if (hanging_ankle) {
            for (size_t n = 0; n < 2; ++n) {
                std::array<double, 2> motor{};
                Require(mappings_[n]->JointToMotor({0.0, n == 0 ? 0.269196 : -0.266339}, &motor),
                    "hanging-ankle fixture must be reachable");
                for (size_t i = 0; i < 2; ++i) {
                    const size_t index = Index(config_.motors, config_.couplings[n].motors[i]);
                    fake_->feedback[index].pos = static_cast<float>(motor[i] / config_.motors[index].polarity +
                        config_.motors[index].zero_offset);
                }
            }
        }
        core_ = std::make_unique<whole_body::WholeBodyCore>(config_, std::move(devices));
        Require(core_->Init() == WHOLE_BODY_OK, "fake initialization");
        for (const auto &command : fake_->written)
            Require(command.mode == MOTOR_MODE_IDLE && command.kp == 0 && command.kd == 0 &&
                command.trq_des == 0, "initialization may send IDLE only");
        manager_.Init();
        Require(manager_.CurrentPolicyName() == "stand", "default policy is LocoMode");
    }

    void Run() {
        using behavior_manager::StateName;
        Step(0);
        Require(manager_.CurrentState() == StateName::POWER_OFF, "startup POWER_OFF");
        RequireIdle();
        Step(1);
        Require(manager_.CurrentState() == StateName::DAMP, "POWER_OFF -> DAMP");
        for (double kp : manager_.GetOutput().kp) Require(kp == 0.0, "DAMP has no position stiffness");

        // Actual BehaviorManager loads the selected runtime before allowing HOME.
        // This does not enter RL or run a policy inference loop.
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
        while (manager_.CurrentState() == StateName::DAMP && std::chrono::steady_clock::now() < deadline) {
            Step(4);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        Require(manager_.CurrentState() == StateName::HOME, "prepared policy permits DAMP -> HOME");
        Step(2);
        Require(manager_.CurrentState() == StateName::HOME, "early ZERO request must not bypass HOME motion");
        for (int i = 0; i < 2200; ++i) Step(0);
        CheckTarget(yaml_["robot_base"]["default_joint_pos"]);
        Step(2);
        Require(manager_.CurrentState() == StateName::ZERO, "HOME -> ZERO");
        for (int i = 0; i < 1300; ++i) Step(0);
        Require(manager_.IsZeroReady(), "ZERO must converge using measured feedback");
        const auto policy = yaml_["rl_policy"]["onnx_infer"]["policies"][manager_.CurrentPolicyName()];
        CheckTarget(policy["zero_target_pos"] ? policy["zero_target_pos"] : policy["rl_default_pos"]);
        for (int i = 0; i < 300; ++i) Step(0);
        Require(manager_.CurrentState() == StateName::ZERO, "ZERO must not automatically enter RL");
        Step(-1);
        Require(manager_.CurrentState() == StateName::POWER_OFF, "ZERO -> POWER_OFF");
        RequireIdle();

        // Verify immediate exit also works in DAMP and while HOME is moving.
        Step(1);
        Step(-1);
        RequireIdle();
        Step(1);
        Step(4);
        Require(manager_.CurrentState() == StateName::HOME, "second HOME entry");
        for (int i = 0; i < 600; ++i) Step(0);
        Step(-1);
        RequireIdle();
        Require(max_target_step_ < 0.01, "unexpected enabled position target discontinuity");
        std::cout << "PASS pre_RL_commands=" << steps_ << " max_target_step_rad=" << max_target_step_
            << " max_mapping_write_us=" << max_write_us_ << '\n';
        std::cout << "boundary=ideal_following_fake_devices,not_physical_tracking_or_loop_timing\n";
    }

    private:
    void RequireIdle() const {
        Require(!manager_.GetOutput().enable && fake_->written.size() == 29, "disabled output");
        for (const auto &command : fake_->written) {
            Require(command.mode == MOTOR_MODE_IDLE && command.kp == 0 && command.kd == 0 &&
                command.trq_des == 0, "POWER_OFF must send zero-output idle commands");
        }
    }

    void CheckTarget(const YAML::Node &expected) const {
        const auto &position = manager_.GetOutput().target_pos;
        for (size_t i = 0; i < 29; ++i)
            Require(std::abs(position[i] - expected[i].as<double>()) < 1e-7, "configured target reached");
    }

    void FollowTarget(const std::vector<double> &position) {
        std::vector<double> raw(29);
        for (size_t i = 0; i < 29; ++i) {
            const auto &joint = config_.joints[i];
            if (joint.mapping != "direct") continue;
            const size_t index = Index(config_.motors, joint.motors[0]);
            raw[index] = position[i] / config_.motors[index].polarity + config_.motors[index].zero_offset;
        }
        for (size_t n = 0; n < config_.couplings.size(); ++n) {
            const auto &coupling = config_.couplings[n];
            std::array<double, 2> target, motor;
            for (size_t i = 0; i < 2; ++i) target[i] = position[Index(config_.joints, coupling.joints[i])];
            Require(mappings_[n]->JointToMotor(target, &motor), "trajectory target must remain reachable");
            for (size_t i = 0; i < 2; ++i) {
                const size_t index = Index(config_.motors, coupling.motors[i]);
                raw[index] = motor[i] / config_.motors[index].polarity + config_.motors[index].zero_offset;
            }
        }
        for (size_t i = 0; i < 29; ++i) {
            fake_->feedback[i].vel = static_cast<float>((raw[i] - fake_->feedback[i].pos) / config_.cycle_s);
            fake_->feedback[i].pos = static_cast<float>(raw[i]);
        }
    }

    void Step(int key) {
        whole_body_state feedback{};
        Require(core_->Read(&feedback) == WHOLE_BODY_OK, "fake read: " + core_->LastError());
        auto sensor = robot_base::RobotData::Create(29);
        sensor.time = (++steps_) * config_.cycle_s;
        for (size_t i = 0; i < 29; ++i) {
            sensor.joint_pos[i] = feedback.position[i];
            sensor.joint_vel[i] = feedback.velocity[i];
            sensor.joint_torque[i] = feedback.torque[i];
        }
        for (size_t i = 0; i < 4; ++i) sensor.base_quat[i] = feedback.base_quat[i];
        robot_base::QuatToRpy(sensor.base_quat, sensor.rpy);
        manager_.SetSensorData(sensor);
        robot_base::Command request{};
        request.key = key;
        manager_.SetCommand(request);
        manager_.Step(static_cast<float>(config_.cycle_s), 0.02f);
        Require(!manager_.CurrentFault().latched, "FSM fault: " + manager_.CurrentFault().detail);
        const auto &output = manager_.GetOutput();
        if (manager_.CurrentState() == behavior_manager::StateName::HOME) {
            for (size_t i = 0; i < 29; ++i)
                Require(output.target_pos[i] >= config_.joints[i].position_limit[0] &&
                    output.target_pos[i] <= config_.joints[i].position_limit[1], "HOME target must stay in bounds");
        }
        whole_body_joint_command command{};
        command.num_dof = 29;
        command.enable = output.enable;
        command.mode = Mode(manager_.CurrentState());
        command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
        for (size_t i = 0; i < 29; ++i) {
            command.position[i] = output.target_pos[i];
            command.velocity[i] = output.target_vel[i];
            command.torque[i] = output.target_torque[i];
            command.kp[i] = output.kp[i];
            command.kd[i] = output.kd[i];
            if (output.enable && previous_enabled_)
                max_target_step_ = std::max(max_target_step_, std::abs(output.target_pos[i] - previous_target_[i]));
        }
        const auto start = std::chrono::steady_clock::now();
        const int result = core_->Write(command, sensor.time);
        const double duration = std::chrono::duration<double, std::micro>(
            std::chrono::steady_clock::now() - start).count();
        max_write_us_ = std::max(max_write_us_, duration);
        Require(result == WHOLE_BODY_OK, "fake write: " + core_->LastError());
        if (output.enable) {
            for (size_t index : {13U, 14U}) {
                const auto &motor = fake_->written[index];
                Require(motor.mode == MOTOR_MODE_HYBRID && motor.kd > 0 && motor.trq_des == 0,
                    "waist DAMP/HOME/ZERO must keep damping on the motor, no host PD torque");
                if (manager_.CurrentState() == behavior_manager::StateName::DAMP)
                    Require(motor.kp == 0 && motor.vel_des == 0, "native waist DAMP fields");
            }
        }
        previous_target_ = output.target_pos;
        previous_enabled_ = output.enable;
        if (output.enable && manager_.CurrentState() != behavior_manager::StateName::DAMP)
            FollowTarget(output.target_pos);
    }

    whole_body::RuntimeConfig config_;
    YAML::Node yaml_;
    behavior_manager::BehaviorManagerClass manager_;
    FakeDevices *fake_ = nullptr;
    std::unique_ptr<whole_body::WholeBodyCore> core_;
    std::vector<std::unique_ptr<whole_body::CoupledMapping>> mappings_;
    std::vector<double> previous_target_;
    bool previous_enabled_ = false;
    size_t steps_ = 0;
    double max_target_step_ = 0.0;
    double max_write_us_ = 0.0;
};

}  // namespace

int main(int argc, char **argv) {
    try {
        Require(argc == 3, "usage: test_g1_pre_rl g1.yaml recorded_pose.yaml");
        PreRlTest test(argv[1], argv[2]);
        test.Run();
        PreRlTest hanging_test(argv[1], argv[2], true);
        hanging_test.Run();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
