#!/usr/bin/env python3
from prometheus_client import start_http_server, Gauge
import adafruit_dht
import board
import time

# Prometheus
PROMETHEUS_PORT = 8001
PI_TEMP = Gauge('pi_temp', 'CPU Temp')
CABINET_TEMP = Gauge('cabinet_temp', 'Cabinet Temp')

dht = None


def main() -> None:
    print("\033[90m", "initializing prometheus web server", "\033[0m")
    init_prometheus()

    print("\033[90m", "initializing DHT22 sensor", "\033[0m")
    init_dht()

    try:
        while True:
            pi_temp = read_pi_temp()
            cabinet_temp = read_cabinet_temp()

            print("temps", round(pi_temp, 1), round(cabinet_temp, 1))

            if pi_temp is not None:
                PI_TEMP.set(pi_temp)

            if cabinet_temp is not None:
                CABINET_TEMP.set(cabinet_temp)

            time.sleep(5)

    except KeyboardInterrupt:
        return

def init_prometheus() -> None:
    start_http_server(PROMETHEUS_PORT)


def init_dht() -> None:
    global dht
    dht = adafruit_dht.DHT22(board.D25)


def read_pi_temp() -> float | None:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return float(f.read()) / 1000.0
    except:
        return None


def read_cabinet_temp() -> float | None:
    try:
        cabinet_temp = dht.temperature

        if cabinet_temp is not None:
            return dht.temperature
        else:
            return None
    except:
        return None

if __name__ == "__main__":
    main()
