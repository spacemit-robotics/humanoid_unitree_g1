/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * @file test_waist_damping.cpp
 * @brief Replay captured waist oscillation with fake devices, including wire gain encoding.
 */
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <yaml-cpp/yaml.h>

#include "core/whole_body_core.h"
extern "C" {
#include "rs485_20_26_protocol.h"
}

namespace {

void Require(bool value, const std::string &reason) {
    if (!value) throw std::runtime_error(reason);
}

class CapturedDevices final : public whole_body::DeviceManager {
    public:
    int Init() override { return 0; }
    int Read(std::vector<motor_state> *motors, imu_data *imu,
        whole_body::DeviceFeedbackStatus *status) override {
        *motors = feedback;
        *imu = {};
        imu->quat[0] = 1.0;
        status->motor_received.assign(29, true);
        status->motor_fresh.assign(29, true);
        status->motor_age_s.assign(29, 0.0);
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
};

using Sample = std::array<double, 7>;

std::vector<Sample> LoadTrace(const std::string &path) {
    std::ifstream input(path);
    Require(input.good(), "open captured waist CSV");
    std::string line;
    std::getline(input, line);
    std::vector<Sample> samples;
    while (std::getline(input, line)) {
        std::istringstream row(line);
        Sample sample{};
        std::string token;
        for (double &value : sample) {
            Require(static_cast<bool>(std::getline(row, token, ',')), "short trace row");
            value = std::stod(token);
            Require(std::isfinite(value), "finite trace fields");
        }
        Require(!std::getline(row, token, ','), "extra trace column");
        samples.push_back(sample);
    }
    Require(samples.size() == 145, "complete captured enabled snapshots");
    return samples;
}

double Scale(const whole_body::MotorConfig &motor, const std::string &key) {
    for (const auto &option : motor.driver_options)
        if (option.name == key) return std::stod(option.value);
    throw std::runtime_error("missing wire scale " + key);
}

void Replay(whole_body::RuntimeConfig config, const whole_body_joint_command &command,
    const std::vector<Sample> &samples, bool legacy, bool guarded) {
    if (legacy) {
        for (size_t i : {13U, 14U}) config.joints[i].impedance.mode = whole_body::ImpedanceMode::kSoftware;
        for (auto &coupling : config.couplings) {
            coupling.table_interpolation = "bilinear";
            coupling.table_triangles_file.clear();
        }
    }
    if (guarded) {
        // Exercise the old commissioning guard only in this regression fixture.
        for (size_t i : {13U, 14U}) config.motors[i].feedback_velocity_max = 2.0;
    }
    auto devices = std::make_unique<CapturedDevices>();
    auto *fake = devices.get();
    whole_body::WholeBodyCore core(config, std::move(devices));
    Require(core.Init() == WHOLE_BODY_OK, "fake core initialization");
    double max_error = 0.0, peak_torque = 0.0;
    double min_wire_kd = 100.0, max_wire_kd = 0.0;
    size_t accepted = 0;
    for (const auto &sample : samples) {
        for (size_t side = 0; side < 2; ++side) {
            fake->feedback[13 + side].pos = static_cast<float>(sample[1 + side * 2]);
            fake->feedback[13 + side].vel = static_cast<float>(sample[2 + side * 2]);
        }
        whole_body_state state{};
        int result = core.Read(&state);
        if (result == WHOLE_BODY_OK)
            result = core.Write(command, 1.0 + sample[0] - samples[0][0]);
        const bool over_speed = std::abs(sample[2]) > 2.0 || std::abs(sample[4]) > 2.0;
        if (guarded && over_speed) {
            Require(result == WHOLE_BODY_ERR_STATE, "captured overspeed must disable");
            Require(core.LastError().find("measured_velocity=") != std::string::npos, "specific feedback fault");
            for (const auto &motor : fake->written)
                Require(motor.mode == MOTOR_MODE_IDLE && motor.kp == 0 && motor.kd == 0 &&
                    motor.trq_des == 0, "overspeed must send zero-output IDLE to all 29 motors");
            Require(core.Write(command, 2.0) == WHOLE_BODY_ERR_STATE, "fault cannot auto-reenable");
            std::cout << "guard=IDLE_and_latched first_overspeed_after_s=" << sample[0] - samples[0][0]
                << " accepted_before_guard=" << accepted << " old_torque_at_guard_nm="
                << sample[5] << ',' << sample[6] << '\n';
            return;
        }
        Require(result == WHOLE_BODY_OK, "captured replay: " + core.LastError());
        ++accepted;
        for (size_t side = 0; side < 2; ++side) {
            const auto &sent = fake->written[13 + side];
            peak_torque = std::max(peak_torque, std::abs(static_cast<double>(sent.trq_des)));
            if (legacy) {
                Require(sent.kp == 0 && sent.kd == 0, "old pure software PD reproduced");
                max_error = std::max(max_error, std::abs(sent.trq_des - sample[5 + side]));
                continue;
            }
            Require(sent.kp == 0 && sent.kd > 0 && sent.trq_des == 0 && sent.vel_des == 0,
                "native DAMP has no delayed host torque residual");
            const auto &motor = config.motors[13 + side];
            const rs485_20_26_scale scale{Scale(motor, "protocol_scales.torque"),
                Scale(motor, "protocol_scales.velocity"), Scale(motor, "protocol_scales.position"),
                Scale(motor, "protocol_scales.kp"), Scale(motor, "protocol_scales.kd")};
            rs485_20_26_command wire{};
            wire.id = motor.command_id;
            wire.enabled = wire.watchdog = 1;
            wire.position = sent.pos_des;
            wire.kd = sent.kd;
            std::array<uint8_t, RS485_20_26_COMMAND_SIZE> bytes{};
            Require(rs485_20_26_encode(&scale, &wire, bytes.data()) == 0, "encode using actual driver codec");
            Require(bytes[4] == 0 && bytes[5] == 0 && bytes[6] == 0 && bytes[7] == 0 &&
                bytes[12] == 0 && bytes[13] == 0, "wire torque/velocity/kp remain zero");
            const double encoded_kd = (bytes[14] | (bytes[15] << 8)) / scale.kd;
            Require(encoded_kd > 0 && encoded_kd <= sent.kd && sent.kd - encoded_kd < 1.0 / scale.kd + 1e-6,
                "native damping survives wire truncation with less than one-count error");
            min_wire_kd = std::min(min_wire_kd, encoded_kd);
            max_wire_kd = std::max(max_wire_kd, encoded_kd);
        }
    }
    Require(!guarded && accepted == 145, "unguarded test-only replay covers entire old trace");
    if (legacy) {
        Require(max_error < 1e-5 && peak_torque > 30.0, "exact old failure reproduction");
        std::cout << "legacy_samples=" << accepted << " peak_host_torque_nm=" << peak_torque
            << " replay_error_nm=" << max_error << '\n';
    } else {
        Require(peak_torque == 0, "no host PD torque in native DAMP");
        std::cout << "native_samples=" << accepted << " peak_host_torque_nm=" << peak_torque
            << " wire_kd_range=" << min_wire_kd << ',' << max_wire_kd << '\n';
    }
}

}  // namespace

int main(int argc, char **argv) {
    try {
        Require(argc == 3, "usage: test_g1_waist_damping g1.yaml captured_waist.csv");
        const auto config = whole_body::LoadConfig(argv[1]);
        const auto yaml = YAML::LoadFile(argv[1]);
        const auto samples = LoadTrace(argv[2]);
        whole_body_joint_command command{};
        command.num_dof = 29;
        command.enable = true;
        command.mode = WHOLE_BODY_MODE_DAMP;
        command.actuation_mode = WHOLE_BODY_ACTUATION_HYBRID;
        for (size_t i = 0; i < 29; ++i)
            command.kd[i] = yaml["behavior_manager"]["damp_kd"][i].as<double>();
        Replay(config, command, samples, true, false);
        Replay(config, command, samples, false, false);
        Replay(config, command, samples, false, true);
        std::cout << "PASS: recorded-feedback/codec regression only; no devices or physical dynamics\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
