#!/usr/bin/env python3
from prometheus_client import start_http_server, Gauge
import time

# Prometheus
PROMETHEUS_PORT = 8001
PI_TEMP = Gauge('pi_temp', 'CPU Temp')
CABINET_TEMP = Gauge('cabinet_temp', 'Cabinet Temp')

def main():
    print("\033[90m", "initializing prometheus web server", "\033[0m")
    init_prometheus()

    try:
        while True:
            pi_temp = read_pi_temp()
            cabinet_temp = read_cabinet_temp()

            print("temps", round(pi_temp, 1), round(cabinet_temp, 1))

            PI_TEMP.set(pi_temp)
            CABINET_TEMP.set(cabinet_temp)

            time.sleep(5)

    except KeyboardInterrupt:
        return

def init_prometheus():
    start_http_server(PROMETHEUS_PORT)


def read_pi_temp() -> float:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return float(f.read()) / 1000.0
    except:
        return 0.0


def read_cabinet_temp() -> float:
    # todo: read from the little temperature sensor
    return 42.0

if __name__ == "__main__":
    main()
