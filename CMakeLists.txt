cmake_minimum_required(VERSION 3.16)
project(humanoid_unitree_g1)

install(PROGRAMS
    scripts/run_driver_g1.sh
    scripts/run_control_g1.sh
    scripts/run_hmi_g1.sh
    scripts/run_sim2sim_g1.sh
    scripts/download_models_g1.sh
    DESTINATION bin
)
