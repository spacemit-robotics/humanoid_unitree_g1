/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 * @file simulation_monitor.h
 * @brief Observe an isolated simulation without consuming its control-loop state channel.
 */
#ifndef SIMULATION_MONITOR_H
#define SIMULATION_MONITOR_H

#include <fcntl.h>
#include <unistd.h>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <stdexcept>
#include <string>

#include <yaml-cpp/yaml.h>
#include "transport_packet.h"

class SimulationMonitor {
    public:
    SimulationMonitor(const YAML::Node &config, const std::string &output) : trace_(output) {
        if (config["transport"]["type"].as<std::string>() != "shm")
            throw std::runtime_error("simulation monitor requires SHM");
        const auto prefix = config["transport"]["shm"]["prefix"].as<std::string>();
        if (prefix.rfind("g1_policy_test_", 0) != 0)
            throw std::runtime_error("simulation monitor requires a private test channel");
        if (!trace_) throw std::runtime_error("cannot open simulation trace");
        descriptor_ = open(("/dev/shm/hmrs_" + prefix + "_state").c_str(), O_RDONLY | O_CLOEXEC);
        if (descriptor_ < 0) throw std::runtime_error("cannot open simulation monitor");
        trace_ << "wall_time_s,device_time_s,mode,x,y,z,roll,pitch,yaw,vx,vy,wz\n";
    }
    ~SimulationMonitor() { if (descriptor_ >= 0) close(descriptor_); }
    SimulationMonitor(const SimulationMonitor &) = delete;
    SimulationMonitor &operator=(const SimulationMonitor &) = delete;

    void Poll(const std::string &mode) {
        // Do not use Shm::Read: its shared consumer index belongs to control, not this observer.
        for (int attempt = 0; attempt < 3; ++attempt) {
            std::array<uint32_t, 16> header{}, check{};
            if (pread(descriptor_, header.data(), sizeof(header), 0) != sizeof(header) ||
                header[2] < 2 || header[0] >= header[2] || header[3] < sizeof(state_)) continue;
            const auto slot = (header[0] + header[2] - 1) % header[2];
            transport::RobotStatePacket sample;
            if (pread(descriptor_, &sample, sizeof(sample), 64 + slot * header[3]) != sizeof(sample) ||
                pread(descriptor_, check.data(), sizeof(check), 0) != sizeof(check) ||
                header[0] != check[0]) continue;
            if (sample.header.magic != transport::kMagic || sample.header.version != transport::kVersion ||
                sample.header.type != static_cast<uint16_t>(transport::MsgType::ROBOT_STATE) ||
                sample.num_dof != 29 || !std::isfinite(sample.time)) continue;
            state_ = sample;
            if (sample.header.seq == last_sequence_) return;
            last_sequence_ = sample.header.seq;
            const double wall = std::chrono::duration<double>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            trace_ << std::fixed << std::setprecision(9) << wall << ',' << sample.time << ',' << mode;
            for (double value : sample.base_pos) trace_ << ',' << value;
            for (double value : sample.rpy) trace_ << ',' << value;
            trace_ << ',' << sample.base_vel[0] << ',' << sample.base_vel[1] << ',' << sample.gyro[2] << '\n';
            return;
        }
    }
    const transport::RobotStatePacket &State() const { return state_; }

    private:
    int descriptor_ = -1;
    uint32_t last_sequence_ = 0;
    transport::RobotStatePacket state_{};
    std::ofstream trace_;
};

#endif  // SIMULATION_MONITOR_H
