#!/bin/bash
# SPDX-License-Identifier: MIT

# Read CPU temperature (in millidegrees Celsius)
cpu_raw=$(cat /sys/class/thermal/thermal_zone0/temp)
cpu_temp=$(echo "scale=1; $cpu_raw/1000" | bc)

# Read GPU temperature using vcgencmd
gpu_temp=$(/usr/bin/vcgencmd measure_temp | sed "s/temp=//")

echo "CPU Temperature: ${cpu_temp}°C"
echo "GPU Temperature: ${gpu_temp}"
