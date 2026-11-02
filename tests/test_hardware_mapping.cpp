/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 *
 * @file test_hardware_mapping.cpp
 * @brief Offline G1 coupling, command-domain and IMU-chain regression; no hardware I/O.
 */
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <yaml-cpp/yaml.h>

#include "core/whole_body_core.h"

namespace {

void Require(bool value, const std::string &message) {
    if (!value) throw std::runtime_error(message);
}

void Near(double actual, double expected, double tolerance, const std::string &message) {
    Require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance,
        message + ": actual=" + std::to_string(actual) + ", expected=" + std::to_string(expected));
}

double Dot(const std::array<double, 2> &first, const std::array<double, 2> &second) {
    return first[0] * second[0] + first[1] * second[1];
}

const whole_body::CouplingConfig &CheckConfig(const whole_body::RuntimeConfig &config) {
    Require(!config.read_only && config.allow_actuation, "operator-controlled, disabled startup configuration");
    Near(config.cycle_s, 0.002, 1.0e-12, "500 Hz cycle");
    Require(config.num_dof == 29 && config.couplings.size() == 3, "29 joints, three couplings");
    Require(config.imu.base_joint_chain.empty(), "pelvis-mounted IMU must not subtract waist motion");
    Require(config.imu.mounting_matrix == std::array<float, 9>{0, 0, -1, 0, 1, 0, 1, 0, 0},
        "pelvis IMU axes: sensor X up, Y left, Z backward");
    Require(config.joints.at(13).name == "waist_roll_joint" &&
        config.joints.at(14).name == "waist_pitch_joint", "canonical waist order");
    for (size_t index : {13u, 14u}) {
        const auto &motor = config.motors.at(index);
        Require(motor.bus == "waist" && motor.command_id == index - 13 &&
            motor.feedback_id == index - 13, "waist serial endpoint order");
        Near(motor.polarity, 1.0, 0.0, "waist motor polarity");
        Near(motor.zero_offset, 0.0, 0.0, "waist motor offset");
        Require(config.joints[index].mapping == "table_2d" &&
            config.joints[index].impedance.mode == whole_body::ImpedanceMode::kMotorProjected,
            "waist requires coupled, transformed motor-side impedance");
        Near(motor.feedback_velocity_max, 0.0, 0.0, "no temporary raw-motor commissioning speed cap");
        Near(config.joints[index].velocity_limit, 37.0, 0.0, "waist joint speed protection retained");
    }
    const auto found = std::find_if(config.couplings.begin(), config.couplings.end(),
        [](const auto &coupling) { return coupling.joints[0] == "waist_pitch_joint"; });
    Require(found != config.couplings.end() && found->joints[1] == "waist_roll_joint",
        "table output must be pitch, roll");
    Require(found->motors[0] == "motor_alias_14" && found->motors[1] == "motor_alias_15" &&
        found->table_direction == "motor_to_joint" &&
        found->table_output_scale == std::array<double, 2>{1.0, 1.0}, "calibration table convention");
    return *found;
}

void CheckAnkleConfig(const whole_body::RuntimeConfig &config) {
    for (size_t leg = 0; leg < 2; ++leg) {
        const size_t index = leg == 0 ? 4 : 10;
        const double sign = leg == 0 ? 1.0 : -1.0;
        const auto &coupling = config.couplings.at(leg);
        Require(coupling.motors[0] == config.motors[index + 1].name &&
            coupling.motors[1] == config.motors[index].name, "ankle CSV input order ID5, ID4");
        Require(coupling.joints[0] == config.joints[index].name &&
            coupling.joints[1] == config.joints[index + 1].name, "ankle output pitch, roll");
        Require(coupling.table_direction == "motor_to_joint" &&
            coupling.table_output_scale == std::array<double, 2>{1.0, sign}, "ankle output signs");
        for (size_t side = 0; side < 2; ++side) {
            Near(config.motors[index + side].polarity, sign, 0.0, "ankle normalization sign");
            Near(config.motors[index + side].zero_offset, 0.0, 0.0, "ankle zero unchanged");
        }
    }
}

void CheckAnkleGrid(const whole_body::CouplingConfig &config) {
    whole_body::CoupledMapping mapping(config);
    double max_condition = 0.0, max_amplification = 0.0, max_residual = 0.0;
    size_t count = 0, refused = 0;
    // Initial standing neighborhood only, not a certified mechanical travel box.
    for (int p = 0; p <= 40; ++p) {
        for (int r = 0; r <= 30; ++r) {
            const std::array<double, 2> joint{-0.4 + p * 0.015, -0.15 + r * 0.01};
            std::array<double, 2> motor, recovered;
            Require(mapping.JointToMotor(joint, &motor) && mapping.MotorToJoint(motor, &recovered),
                "standing-neighborhood ankle grid");
            ++count;
            if (!mapping.CheckJointTarget(joint)) ++refused;
            for (size_t i = 0; i < 2; ++i)
                max_residual = std::max(max_residual, std::abs(recovered[i] - joint[i]));
            double condition, amplification;
            Require(mapping.Metrics(joint, &condition, &amplification), "ankle grid Jacobian");
            max_condition = std::max(max_condition, condition);
            max_amplification = std::max(max_amplification, amplification);
        }
    }
    Require(max_residual < 1.0e-6 && refused == 0, "ankle neighborhood residual and target guards");
    std::cout << config.joints[0] << " grid_points=" << count << " max_roundtrip_rad=" << max_residual
        << " max_condition=" << max_condition << " max_amplification=" << max_amplification << '\n';
}

void CheckMapping(const whole_body::CoupledMapping &mapping) {
    // Retain the historical bilinear fixture; deployed Delaunay values are checked
    // independently in test_coupling_commands, not against these old interpolants.
    auto legacy_config = mapping.Config();
    legacy_config.table_interpolation = "bilinear";
    legacy_config.table_triangles_file.clear();
    whole_body::CoupledMapping legacy(legacy_config);
    const std::array<std::array<double, 4>, 3> recorded = {{
        {0.009453324247191012, -0.0682163710786517, -0.0319509631035121, -0.03724311709379077},
        {-0.18938641253846153, 0.1351183980934066, 0.12522050349782887, -0.03317415466666332},
        {0.027135174911602212, -0.06837934661325966, -0.03908504905865798, -0.026159286502043883},
    }};
    std::array<double, 2> joint, motor, recovered;
    for (const auto &pose : recorded) {
        Require(legacy.MotorToJoint({pose[0], pose[1]}, &joint), "recorded waist position");
        Near(joint[0], pose[2], 1.0e-10, "recorded pitch");
        Near(joint[1], pose[3], 1.0e-10, "recorded roll");
    }
    double max_roundtrip = 0.0;
    double max_condition = 0.0;
    double central_max_condition = 0.0;
    double central_max_amplification = 0.0;
    double max_power_error = 0.0;
    size_t mapped = 0, rejected = 0;
    // Independent axis limits do not make the whole rectangle reachable. Record
    // refused combined poses; require every point in the central box to solve.
    // This is not permission to sweep either box on the physical robot.
    for (int pitch = 0; pitch <= 40; ++pitch) {
        for (int roll = 0; roll <= 40; ++roll) {
            joint = {-0.52 + pitch * 0.026, -0.52 + roll * 0.026};
            if (!mapping.JointToMotor(joint, &motor)) {
                ++rejected;
                Require(std::abs(joint[0]) > 0.2 || std::abs(joint[1]) > 0.2,
                    "central joint-box point unexpectedly rejected");
                continue;
            }
            ++mapped;
            Require(mapping.MotorToJoint(motor, &recovered), "mapped point must round trip");
            for (size_t axis = 0; axis < 2; ++axis)
                max_roundtrip = std::max(max_roundtrip, std::abs(recovered[axis] - joint[axis]));
            double condition, amplification;
            Require(mapping.Metrics(joint, &condition, &amplification), "finite waist Jacobian");
            max_condition = std::max(max_condition, condition);
            if (std::abs(joint[0]) <= 0.2 && std::abs(joint[1]) <= 0.2) {
                central_max_condition = std::max(central_max_condition, condition);
                central_max_amplification = std::max(central_max_amplification, amplification);
                Require(mapping.CheckJointTarget(joint), "central waist target guards");
            }
            const std::array<double, 2> velocity{0.13, -0.21}, torque{0.31, -0.47};
            std::array<double, 2> motor_velocity, motor_torque, recovered_torque;
            Require(mapping.JointVelocityToMotor(joint, velocity, &motor_velocity) &&
                mapping.JointTorqueToMotor(joint, torque, &motor_torque) &&
                mapping.MotorTorqueToJoint(joint, motor_torque, &recovered_torque), "waist power map");
            max_power_error = std::max(max_power_error,
                std::abs(Dot(velocity, torque) - Dot(motor_velocity, motor_torque)));
            for (size_t axis = 0; axis < 2; ++axis)
                Near(recovered_torque[axis], torque[axis], 1.0e-9, "torque round trip");
        }
    }
    Require(mapped > 1000 && max_roundtrip < 1.0e-6 && max_power_error < 1.0e-9,
        "grid coverage and numerical tolerances");
    // The public mapping Jacobian is dMotor/dJoint. Invert it and compare its
    // forward derivative against finite differences inside this motor-grid cell.
    std::array<double, 4> jacobian;
    const std::array<double, 2> sample{-0.18938641253846153, 0.1351183980934066};
    Require(mapping.MotorToJoint(sample, &joint, &jacobian), "Jacobian sample");
    const double det = jacobian[0] * jacobian[3] - jacobian[1] * jacobian[2];
    const std::array<double, 4> forward{jacobian[3] / det, -jacobian[1] / det,
        -jacobian[2] / det, jacobian[0] / det};
    for (size_t axis = 0; axis < 2; ++axis) {
        auto plus = sample;
        auto minus = sample;
        plus[axis] += 1.0e-6;
        minus[axis] -= 1.0e-6;
        std::array<double, 2> positive, negative;
        Require(mapping.MotorToJoint(plus, &positive) && mapping.MotorToJoint(minus, &negative),
            "finite difference inputs");
        for (size_t output = 0; output < 2; ++output)
            Near((positive[output] - negative[output]) / 2.0e-6,
                forward[output * 2 + axis], 1.0e-7, "forward finite difference");
    }
    Require(!mapping.MotorToJoint({1.32, 0.0}, &joint), "table overflow must be rejected");
    std::cout << "waist_grid_points=1681 mapped=" << mapped << " rejected=" << rejected
        << " max_roundtrip_rad=" << max_roundtrip
        << " max_condition=" << max_condition << " central_max_condition=" << central_max_condition
        << " central_max_amplification=" << central_max_amplification
        << " max_power_error=" << max_power_error << '\n';
}

void CheckGains(const whole_body::RuntimeConfig &config, const std::string &path) {
    const auto yaml = YAML::LoadFile(path);
    const auto stand = yaml["rl_policy"]["onnx_infer"]["policies"]["stand"];
    for (const auto &coupling : config.couplings) {
        whole_body::CoupledMapping mapping(coupling);
        std::array<size_t, 2> indices{};
        for (size_t side = 0; side < 2; ++side) {
            const auto it = std::find(config.joint_names.begin(), config.joint_names.end(), coupling.joints[side]);
            Require(it != config.joint_names.end(), "coupling canonical joint index");
            indices[side] = static_cast<size_t>(it - config.joint_names.begin());
        }
        for (bool policy : {false, true}) {
            const auto parameters = policy ? stand : yaml["robot_base"];
            const auto position = parameters[policy ? "rl_default_pos" : "default_joint_pos"];
            const std::array<double, 2> joint{position[indices[0]].as<double>(), position[indices[1]].as<double>()};
            std::array<double, 2> motor;
            std::array<double, 4> inverse;
            Require(mapping.JointToMotor(joint, &motor, &inverse) && mapping.CheckJointTarget(joint),
                "nominal standing/home coupling target");
            const double det = inverse[0] * inverse[3] - inverse[1] * inverse[2];
            const std::array<double, 4> a{inverse[3] / det, -inverse[1] / det,
                -inverse[2] / det, inverse[0] / det};  // dJoint/dNormalizedMotor.
            std::array<double, 4> stiffness{}, damping{};
            for (size_t row = 0; row < 2; ++row) {
                const double kp = parameters["kp"][indices[row]].as<double>();
                const double kd = parameters["kd"][indices[row]].as<double>();
                Require(kp > 0.0 && kd > 0.0, "positive coupling gains");
                if (policy) {
                    const bool waist = coupling.joints[0] == "waist_pitch_joint";
                    Near(kp, waist ? 200.0 : 20.0, 0.0, "retain stand policy kp");
                    Near(kd, waist ? 5.0 : 2.0, 0.0, "retain stand policy kd");
                }
                for (size_t i = 0; i < 2; ++i) {
                    for (size_t j = 0; j < 2; ++j) {
                        stiffness[i * 2 + j] += a[row * 2 + i] * kp * a[row * 2 + j];
                        damping[i * 2 + j] += a[row * 2 + i] * kd * a[row * 2 + j];
                    }
                }
            }
            for (const auto &matrix : {stiffness, damping})
                Require(matrix[0] > 0 && matrix[3] > 0 &&
                    matrix[0] * matrix[3] - matrix[1] * matrix[2] > 0, "positive definite local impedance");
            std::cout << coupling.joints[0] << (policy ? " stand" : " home")
                << " normalized_motor=" << motor[0] << ',' << motor[1]
                << " local_Km=" << stiffness[0] << ',' << stiffness[1] << ',' << stiffness[3]
                << " local_Dm=" << damping[0] << ',' << damping[1] << ',' << damping[3] << '\n';
        }
    }
    std::cout << "gain_boundary=local_linearization_not_discrete_time_stability_or_gain_equivalence\n";
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
        ++writes;
        return 0;
    }
    void Shutdown() override {}
    std::vector<motor_state> feedback = std::vector<motor_state>(29);
    imu_data sensor{};
    size_t writes = 0;
    std::vector<motor_cmd> written;
};

void CheckCore(const whole_body::RuntimeConfig &config, const whole_body::CoupledMapping &mapping) {
    auto devices = std::make_unique<FakeDevices>();
    auto *fake = devices.get();
    fake->feedback[13].pos = -0.18938641f;
    fake->feedback[14].pos = 0.13511840f;
    std::array<double, 2> expected;
    Require(mapping.MotorToJoint({fake->feedback[13].pos, fake->feedback[14].pos}, &expected),
        "mock feedback waist mapping");
    // FakeDevices supplies the already mounting-corrected IMU, like DeviceManager.
    // Nonzero waist angles must no longer rotate a pelvis-mounted IMU.
    fake->sensor.quat[0] = 1.0f;
    fake->sensor.gyro[0] = 0.1f;
    fake->sensor.gyro[1] = 0.2f;
    fake->sensor.gyro[2] = 0.3f;
    auto read_only_config = config;
    read_only_config.read_only = true;
    read_only_config.allow_actuation = false;
    whole_body::WholeBodyCore core(read_only_config, std::move(devices));
    Require(core.Init() == WHOLE_BODY_OK, "offline core initialization");
    whole_body_state state{};
    Require(core.Read(&state) == WHOLE_BODY_OK, "offline core read: " + core.LastError());
    Near(state.position[13], expected[1], 1.0e-9, "canonical roll uses CSV column four");
    Near(state.position[14], expected[0], 1.0e-9, "canonical pitch uses CSV column three");
    Near(state.base_quat[0], 1.0, 1.0e-6, "pelvis quaternion w");
    for (size_t i = 1; i < 4; ++i) Near(state.base_quat[i], 0.0, 1.0e-6, "pelvis quaternion xyz");
    for (size_t i = 0; i < 3; ++i)
        Near(state.gyro[i], fake->sensor.gyro[i], 0.0, "pelvis gyro must not subtract waist motion");
    Require(core.SetMode(WHOLE_BODY_MODE_RL) == WHOLE_BODY_ERR_READ_ONLY && fake->writes == 0,
        "read-only core must not enable or issue motor writes");
    std::cout << "canonical_joint_order=PASS pelvis_imu_passthrough=PASS read_only_gate=PASS\n";
}

void CheckMockCommand(const whole_body::RuntimeConfig &config,
    const whole_body::CoupledMapping &mapping, bool projected) {
    // Only this in-memory copy accepts commands; FakeDevices never opens a device.
    auto mock_config = config;
    mock_config.read_only = false;
    mock_config.allow_actuation = true;
    for (size_t i : {13U, 14U})
        mock_config.joints[i].impedance.mode = projected
            ? whole_body::ImpedanceMode::kMotorProjected : whole_body::ImpedanceMode::kMotor;
    auto devices = std::make_unique<FakeDevices>();
    auto *fake = devices.get();
    fake->feedback[13].pos = -0.18938641f;
    fake->feedback[14].pos = 0.13511840f;
    fake->sensor.quat[0] = 1.0f;
    whole_body::WholeBodyCore core(mock_config, std::move(devices));
    Require(core.Init() == WHOLE_BODY_OK, "mock command core initialization");
    whole_body_state state{};
    Require(core.Read(&state) == WHOLE_BODY_OK, "mock command core read");
    whole_body_joint_command command{};
    command.num_dof = 29;
    command.enable = true;
    command.mode = WHOLE_BODY_MODE_HOME;
    for (size_t i = 0; i < 29; ++i) command.position[i] = state.position[i];
    command.position[14] += 0.001;
    command.position[13] += 0.002;
    command.kp[13] = command.kp[14] = 10.0;
    Require(core.Write(command, 1.0) == WHOLE_BODY_OK, "mock command mapping");
    std::array<double, 2> expected_position, expected_kp;
    Require(mapping.CheckJointTarget({command.position[14], command.position[13]},
        &expected_position), "expected mock waist motor position");
    Require(mapping.JointGainToMotor({state.position[14], state.position[13]}, {10.0, 10.0},
        &expected_kp), "expected transformed motor kp");
    if (projected) {
        std::array<double, 2> proportional;
        Require(mapping.JointTorqueToMotor({state.position[14], state.position[13]},
            {0.01, 0.02}, &proportional), "project waist proportional effort");
        for (size_t side = 0; side < 2; ++side)
            expected_position[side] = fake->feedback[13 + side].pos + proportional[side] / expected_kp[side];
    }
    Require(fake->written.size() == 29, "all mock motor commands produced");
    for (size_t side = 0; side < 2; ++side) {
        const auto &sent = fake->written[13 + side];
        Near(sent.pos_des, expected_position[side], 1.0e-7, "waist target motor order");
        Near(sent.trq_des, 0.0, 0.0, "native PD must not also apply host PD torque");
        Near(sent.kp, expected_kp[side], 1.0e-6, "positive transformed native kp");
        Near(sent.kd, 0.0, 0.0, "zero requested damping remains zero");
    }
    std::cout << "mock_HOME_" << (projected ? "projected" : "inverse")
        << "_native_PD_target_order_and_no_double_PD=PASS\n";

    if (projected) {
        command.position[14] = 0.53;
        Require(core.Write(command, 1.002) == WHOLE_BODY_ERR_COMMAND,
            "projected command retains joint position bounds");
        for (const auto &sent : fake->written)
            Require(sent.mode == MOTOR_MODE_IDLE, "out-of-bounds projected command must disable motors");
        return;
    }

    // Independent limits accept both -0.52 values, but this combined waist pose
    // has no solution in the original table. No enabled frame may escape.
    command.position[13] = command.position[14] = -0.52;
    const auto start = std::chrono::steady_clock::now();
    Require(core.Write(command, 1.002) == WHOLE_BODY_ERR_COMMAND, "unreachable combined waist target");
    const double duration_us = std::chrono::duration<double, std::micro>(
        std::chrono::steady_clock::now() - start).count();
    for (const auto &sent : fake->written)
        Require(sent.mode == MOTOR_MODE_IDLE, "unreachable target must send only idle frames");
    command.position[13] = state.position[13];
    command.position[14] = state.position[14];
    Require(core.Write(command, 1.004) != WHOLE_BODY_OK, "unreachable target fault remains latched");
    std::cout << "unreachable_waist_target=IDLE_and_latched desktop_check_us=" << duration_us << '\n';
}

void CheckAnkleCore(const whole_body::RuntimeConfig &config) {
    auto mock_config = config;
    // Archived four-corner/software-PD regression, not the projected motor mode.
    for (auto &coupling : mock_config.couplings) {
        coupling.table_interpolation = "bilinear";
        coupling.table_triangles_file.clear();
    }
    for (size_t i : {4U, 5U, 10U, 11U}) {
        mock_config.joints[i].impedance.mode = whole_body::ImpedanceMode::kSoftware;
        mock_config.joints[i].impedance.rl_mode.reset();
    }
    mock_config.read_only = false;
    mock_config.allow_actuation = true;
    auto devices = std::make_unique<FakeDevices>();
    auto *fake = devices.get();
    for (size_t i : {4u, 10u}) {
        fake->feedback[i].pos = 0.113f;
        fake->feedback[i + 1].pos = -0.207f;
        fake->feedback[i].vel = 0.13f;
        fake->feedback[i + 1].vel = -0.21f;
        fake->feedback[i].trq = 0.31f;
        fake->feedback[i + 1].trq = -0.47f;
    }
    fake->sensor.quat[0] = 1.0f;
    // Independent four-corner CSV interpolation at raw (ID4, ID5)=(.113,-.207).
    // Derivatives below are d(pitch,roll)/d(raw_ID4,raw_ID5), in row-major order.
    const std::array<std::array<double, 2>, 2> expected = {{
        {0.11409093801158447, -0.05001620132433282},
        {-0.11575190896444143, -0.05494180898610133}}};
    const std::array<std::array<double, 4>, 2> derivative = {{
        {0.37199990211844725, -0.3410708082768332, 0.5321406148610375, 0.5176265436314387},
        {-0.34637724762032196, 0.3693034069662815, 0.574770107272804, 0.5865940888513665}}};
    whole_body::WholeBodyCore core(mock_config, std::move(devices));
    Require(core.Init() == WHOLE_BODY_OK, "ankle core initialization");
    whole_body_state state{};
    Require(core.Read(&state) == WHOLE_BODY_OK, "ankle core read: " + core.LastError());
    whole_body_joint_command command{};
    command.num_dof = 29;
    command.enable = true;
    command.mode = WHOLE_BODY_MODE_RL;
    for (size_t i = 0; i < 29; ++i) command.position[i] = state.position[i];
    for (size_t leg = 0; leg < 2; ++leg) {
        const size_t i = leg == 0 ? 4 : 10;
        const auto &a = derivative[leg];
        for (size_t side = 0; side < 2; ++side) {
            Near(state.position[i + side], expected[leg][side], 1.0e-7, "raw-to-virtual ankle position");
            Near(state.velocity[i + side], a[side * 2] * 0.13 - a[side * 2 + 1] * 0.21,
                1.0e-7, "raw-to-virtual ankle velocity");
            command.position[i + side] += 0.001 * (side + 1);
            command.kp[i + side] = 10.0;
        }
        Near(state.torque[i] * state.velocity[i] + state.torque[i + 1] * state.velocity[i + 1],
            0.31 * 0.13 + (-0.47) * (-0.21), 1.0e-7, "raw-to-virtual power");
    }
    Require(core.Write(command, 1.0) == WHOLE_BODY_OK, "ankle torque command");
    for (size_t leg = 0; leg < 2; ++leg) {
        const size_t i = leg == 0 ? 4 : 10;
        const auto &a = derivative[leg];
        for (size_t side = 0; side < 2; ++side) {
            Near(fake->written[i + side].trq_des, a[side] * 0.01 + a[2 + side] * 0.02,
                1.0e-7, "virtual-to-raw ankle torque and polarity");
            Near(fake->written[i + side].kp, 0.0, 0.0, "no duplicated ankle kp");
            Near(fake->written[i + side].kd, 0.0, 0.0, "no duplicated ankle kd");
        }
    }
    std::cout << "left_and_right_raw_position_velocity_torque_and_command=PASS\n";
}

void ReplayRecord(const whole_body::RuntimeConfig &config, const std::string &path) {
    const auto record = YAML::LoadFile(path);
    Require(!record["incomplete"] && record["poses"].size() == 3, "complete three-pose record required");
    auto devices = std::make_unique<FakeDevices>();
    auto *fake = devices.get();
    // This optional fixture uses a torso-mounted IMU and the full waist joint chain.
    auto recorded_config = config;
    recorded_config.imu.base_joint_chain = {
        {"waist_yaw_joint", {0.0, 0.0, 1.0}},
        {"waist_roll_joint", {1.0, 0.0, 0.0}},
        {"waist_pitch_joint", {0.0, 1.0, 0.0}}};
    whole_body::WholeBodyCore core(recorded_config, std::move(devices));
    Require(core.Init() == WHOLE_BODY_OK, "replay core initialization");
    for (const auto &pose : record["poses"]) {
        for (size_t i = 0; i < config.motors.size(); ++i)
            fake->feedback[i].pos = pose["motor"][config.motors[i].name + ".raw_pos"]["mean"].as<float>();
        const std::array<std::string, 4> fields{"qw", "qx", "qy", "qz"};
        for (size_t i = 0; i < fields.size(); ++i)
            fake->sensor.quat[i] = pose["imu"][fields[i]]["mean"].as<float>();
        whole_body_state state{};
        Require(core.Read(&state) == WHOLE_BODY_OK, "replay read: " + core.LastError());
        const auto &q = state.base_quat;
        const double pitch = std::asin(std::clamp(2.0 * (q[0] * q[2] - q[3] * q[1]), -1.0, 1.0));
        constexpr double kDegreesPerRadian = 57.29577951308232;
        std::cout << "replay=" << pose["label"].as<std::string>()
            << " waist_pitch_deg=" << state.position[14] * kDegreesPerRadian
            << " waist_roll_deg=" << state.position[13] * kDegreesPerRadian
            << " computed_pelvis_pitch_deg=" << pitch * kDegreesPerRadian << '\n';
    }
    Require(fake->writes == 0, "replay must not write commands");
    std::cout << "replay_boundary=window_means_only,no_velocity_samples,no_external_pose_ground_truth\n";
}

}  // namespace

int main(int argc, char **argv) {
    try {
        Require(argc == 2 || argc == 3, "usage: test_g1_hardware_mapping g1.yaml [manual_record.json]");
        std::cout << std::setprecision(12);
        const auto config = whole_body::LoadConfig(argv[1]);
        whole_body::CoupledMapping mapping(CheckConfig(config));
        CheckAnkleConfig(config);
        CheckAnkleGrid(config.couplings[0]);
        CheckAnkleGrid(config.couplings[1]);
        CheckMapping(mapping);
        CheckGains(config, argv[1]);
        CheckCore(config, mapping);
        CheckMockCommand(config, mapping, false);
        CheckMockCommand(config, mapping, true);
        CheckAnkleCore(config);
        if (argc == 3) ReplayRecord(config, argv[2]);
        std::cout << "PASS: offline only; no robot devices or hardware devices opened\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
