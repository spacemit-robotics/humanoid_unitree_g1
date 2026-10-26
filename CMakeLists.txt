cmake_minimum_required(VERSION 3.16)
project(humanoid_unitree_g1)

install(PROGRAMS
    scripts/configure_g1_realtime.py
    scripts/install_g1_service.py
    scripts/run_g1.sh
    scripts/run_hmi_tui_g1.sh
    scripts/run_driver_g1.sh
    scripts/run_control_g1.sh
    scripts/run_hmi_g1.sh
    scripts/run_sim2sim_g1.sh
    scripts/download_models_g1.sh
    DESTINATION bin
)

install(FILES services/g1.service.in DESTINATION share/humanoid_unitree_g1)
install(FILES services/70-g1-gamepad-rumble.rules DESTINATION share/humanoid_unitree_g1)
