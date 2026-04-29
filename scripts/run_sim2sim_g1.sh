#!/bin/bash
: "${SDK_ROOT:=$(cd "$(dirname "$(readlink -f "$0")")/../../.." && pwd)}"
exec control_sim2sim_runtime "$SDK_ROOT/application/native/humanoid_unitree_g1/config/g1.yaml"
