/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 * @file test_switch_client.cpp
 * @brief Exercise live policy selection through an isolated simulation operator service.
 */
#include <chrono>
#include <algorithm>
#include <cmath>
#include <filesystem>  // NOLINT(build/c++17)
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sstream>
#include <thread>

#include <yaml-cpp/yaml.h>
#include "operator_client.h"
#include "simulation_monitor.h"

namespace {
using Clock = std::chrono::steady_clock;
SimulationMonitor *monitor = nullptr;
void Check(const operator_service::Reply &reply) {
    if (!reply.ok) throw std::runtime_error(reply.code + ": " + reply.message);
}
void Wait(operator_service::Client &client, double seconds,
        const std::function<bool(const operator_service::Status &)> &done = {},
        const std::function<void()> &tick = {}) {
    const auto start = Clock::now();
    auto renewed = start - std::chrono::seconds(1);
    do {
        const auto status = client.LatestStatus();
        if (monitor) monitor->Poll(status.policy);
        if (!client.Connected()) throw std::runtime_error("operator connection lost");
        if (status.age_ms > 2000) throw std::runtime_error("control status stopped updating");
        if (status.fault.latched) throw std::runtime_error(status.fault.source + "/" +
            status.fault.code + ": " + status.fault.detail);
        if (done && done(status)) return;
        if (tick) tick();
        if (status.owns_control && Clock::now() - renewed > std::chrono::milliseconds(150)) {
            Check(client.RenewControl());
            renewed = Clock::now();
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    } while (std::chrono::duration<double>(Clock::now() - start).count() < seconds);
    if (done) throw std::runtime_error("simulation condition timed out");
}
}  // namespace

int main(int argc, char **argv) {
    if (argc < 3) return 2;
    try {
        const auto config = YAML::LoadFile(argv[1]);
        if (config["driver"]["backend"].as<std::string>() != "mujoco")
            throw std::runtime_error("this test requires an explicit MuJoCo configuration");
        const double handoff_timeout = config["hmi"]["request_timeout"].as<double>() + 1;
        auto connection = operator_service::Client::ReadConnectionFile(argv[2]);
        if (connection.endpoint.rfind("ws://127.0.0.1:", 0) != 0)
            throw std::runtime_error("this test only connects to its loopback simulation");
        connection.name = "simulation-test";
        operator_service::Client client;
        std::string error;
        if (!client.Connect(connection, &error)) throw std::runtime_error(error);
        Wait(client, 20, [](const auto &s) { return s.online && s.hmi_connected; });
        SimulationMonitor observer(config,
            (std::filesystem::path(argv[1]).parent_path() / "simulation_state.csv").string());
        monitor = &observer;
        Check(client.AcquireControl());
        const auto state = [&](const std::string &name) {
            Check(client.RequestState(name));
            Wait(client, 10, [&](const auto &s) { return s.state == name; });
        };
        state("DAMP");
        Wait(client, 2);
        state("HOME");
        Wait(client, 4.5);
        state("ZERO");
        Wait(client, 8, [](const auto &s) { return s.zero_ready; });
        state("RL");
        Wait(client, 5);
        for (int index = 3; index < argc; ++index) {
            const std::string target = argv[index];
            if (target.rfind("velocity:", 0) == 0) {
                auto parameters = target.substr(9);
                std::replace(parameters.begin(), parameters.end(), ',', ' ');
                std::istringstream values(parameters);
                operator_service::Velocity velocity;
                double seconds = 0;
                if (!(values >> velocity.vx >> velocity.vy >> velocity.wz >> seconds) ||
                    !std::isfinite(seconds) || seconds <= 0 || seconds > 60)
                    throw std::runtime_error("velocity step requires vx,vy,wz,seconds (0 < seconds <= 60)");
                const auto before = observer.State();
                auto refreshed = Clock::now() - std::chrono::seconds(1);
                Wait(client, seconds, {}, [&] {
                    if (Clock::now() - refreshed >= std::chrono::milliseconds(50)) {
                        Check(client.SetVelocity(velocity));
                        refreshed = Clock::now();
                    }
                });
                Check(client.SetVelocity({}));
                const auto after = observer.State();
                const double x = after.base_pos[0] - before.base_pos[0];
                const double y = after.base_pos[1] - before.base_pos[1];
                const double yaw = before.rpy[2];
                const double forward = std::cos(yaw) * x + std::sin(yaw) * y;
                const double lateral = -std::sin(yaw) * x + std::cos(yaw) * y;
                const double turn = std::remainder(after.rpy[2] - yaw, 2 * std::acos(-1));
                std::cout << "MOTION " << target << " dx=" << forward << " dy=" << lateral
                    << " dyaw=" << turn << " height=" << after.base_pos[2] << std::endl;
                if (after.base_pos[2] < 0.5 ||
                    (velocity.vx != 0 && forward * velocity.vx < 0.1 * seconds * velocity.vx * velocity.vx) ||
                    (velocity.vy != 0 && lateral * velocity.vy < 0.1 * seconds * velocity.vy * velocity.vy) ||
                    (velocity.wz != 0 && turn * velocity.wz < 0.1 * seconds * velocity.wz * velocity.wz))
                    throw std::runtime_error("velocity command did not produce motion in the requested direction");
                Wait(client, 3);
                std::cout << "PASS motion and stop -> " << client.LatestStatus().policy << std::endl;
                continue;
            }
            if (target == "idle" || target == "finished") {
                const auto mode = client.LatestStatus().policy;
                Wait(client, target == "finished" ? 290 : 1, [&](const auto &s) {
                    if (s.policy != mode || s.state != "RL") throw std::runtime_error("action changed mode/FSM");
                    if (s.interaction_phase == "REJECTED") throw std::runtime_error("action was rejected");
                    return s.interaction_phase == (target == "idle" ? "IDLE" : "FINISHED");
                });
                Wait(client, 3);
                const auto s = client.LatestStatus();
                if (s.policy != mode || (s.interaction_phase != "IDLE" && s.interaction_phase != "FINISHED"))
                    throw std::runtime_error("standby restarted an action without a request");
                std::cout << "PASS " << target << " -> " << mode << std::endl;
                continue;
            }
            if (target == "cancel") {
                Check(client.CancelInteraction());
                Wait(client, 8, [](const auto &s) { return s.interaction_phase == "FINISHED"; });
                std::cout << "PASS cancel -> " << client.LatestStatus().policy << std::endl;
                continue;
            }
            if (target == "reference" || target.rfind("action:", 0) == 0) {
                Check(target == "reference" ? client.StartReference() :
                    client.StartInteraction(target.substr(7)));
                if (target != "reference") {
                    Wait(client, 10, [](const auto &s) {
                        if (s.interaction_phase == "REJECTED") throw std::runtime_error("action was rejected");
                        return s.interaction_phase == "PLAYING" || s.interaction_phase == "BLEND_IN";
                    });
                }
                Wait(client, 2);
                std::cout << "PASS playback -> " << target << std::endl;
                continue;
            }
            if (target.rfind("wait:", 0) == 0) {
                const double seconds = std::stod(target.substr(5));
                if (!std::isfinite(seconds) || seconds < 0 || seconds > 300)
                    throw std::runtime_error("wait must be between 0 and 300 seconds");
                Wait(client, seconds);
                std::cout << "PASS hold -> " << client.LatestStatus().policy << std::endl;
                continue;
            }
            Check(client.SelectPolicy(target));
            Wait(client, handoff_timeout, [&](const auto &s) {
                if (s.state != "RL") throw std::runtime_error("live switch left RL");
                if (s.request.phase == "failed" || s.request.phase == "rejected" || s.request.phase == "expired")
                    throw std::runtime_error(s.request.message);
                return s.policy == target && s.request.phase == "completed";
            });
            Wait(client, 5);
            std::cout << "PASS live switch -> " << target << std::endl;
        }
        state("POWER_OFF");
        Check(client.ReleaseControl());
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
