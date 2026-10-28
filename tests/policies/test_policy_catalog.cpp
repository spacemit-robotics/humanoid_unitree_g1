/**
 * Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
 * SPDX-License-Identifier: Apache-2.0
 * @file test_policy_catalog.cpp
 * @brief Load every configured policy and validate its native observation/action contract.
 */
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "policy_adapter/policy_adapter.h"
#include "rl_service.h"
#include "robot_base.h"

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    try {
        const auto yaml = robot_base::YamlFile::Load(argv[1]);
        const auto root = yaml.ToAbsPath(yaml.Read<std::string>("robot_base.robot_dir").value());
        const auto names = yaml.Read<std::vector<std::string>>("rl_policy.onnx_infer.policy_names").value();
        for (const auto &name : names) {
            const auto config = rl_policy::LoadPolicyConfigFromYaml(argv[1], name, root);
            const auto adapter_config = behavior_manager::policy_adapter::LoadConfig(argv[1], name, root);
            auto adapter = adapter_config.Enabled()
                ? behavior_manager::policy_adapter::Create(adapter_config, config.exec_cfg) : nullptr;
            rl_policy::PolicyExecutor policy;
            policy.Init(config.exec_cfg);
            auto robot = robot_base::RobotData::Create(29);
            robot.base_quat = {1, 0, 0, 0};
            robot.joint_pos = yaml.Read<std::vector<double>>(
                "rl_policy.onnx_infer.policies." + name + ".zero_target_pos")
                    .value_or(config.exec_cfg.rl_default_pos);
            if (adapter) adapter->Reset(robot);
            Eigen::VectorXf observation;
            std::vector<double> action, target;
            for (int frame = 0; frame < 10; ++frame) {
                if (adapter) adapter->PrepareInputs(robot, frame * config.rl_dt, policy);
                policy.AssembleObs(robot.gyro, robot.rpy, 0, 0, 0, robot.joint_pos,
                    robot.joint_vel, robot.base_quat, {}, config.rl_dt, observation);
                policy.Infer(observation, action);
                if (adapter) adapter->OnAction(action);
                policy.MapActionToTargetPos(action, target);
                if (target.size() != 29 || !observation.allFinite() ||
                    !std::all_of(target.begin(), target.end(), [](double q) { return std::isfinite(q); }))
                    throw std::runtime_error(name + ": invalid observation/target");
            }
            if (adapter && adapter_config.type == "protomotions") {
                adapter->PreparePolicySwitch(true, 0.2);
                adapter->PrepareInputs(robot, 100000.0, policy);
                if (!adapter->ReadyForPolicySwitch())
                    throw std::runtime_error("reference completion did not permit handoff");
            }
            std::cout << "PASS " << name << " obs=" << observation.size()
                << " action=" << action.size() << " joints=" << target.size() << '\n';
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
