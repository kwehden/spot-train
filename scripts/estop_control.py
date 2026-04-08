#!/usr/bin/env python3
"""Separate e-stop controller for Spot.

Run this in a dedicated terminal BEFORE starting the agent.
It owns the e-stop endpoint and keepalive, isolated from the agent process.

Why separate? The Keepalive service (SDK 3.3+) automatically creates a policy
when an e-stop endpoint is registered: if check-ins stop, motors are cut.
Running the e-stop keepalive in the same process as the agent risks GIL
contention during long LLM inference calls, which can delay check-ins
past the timeout and trigger an unwanted motor cut.

Usage:
    python estop_control.py

    Then in another terminal:
    python run.py
"""

import os

import bosdyn.client
import bosdyn.client.util
from bosdyn.client.estop import EstopClient, EstopEndpoint, EstopKeepAlive


def main():
    hostname = os.environ.get("SPOT_HOSTNAME", "192.168.80.3")
    username = os.environ.get("SPOT_USERNAME")
    password = os.environ.get("SPOT_PASSWORD")
    if not username:
        username = input("Spot username: ")
    if not password:
        password = input("Spot password: ")
    os.environ.setdefault("BOSDYN_CLIENT_USERNAME", username)
    os.environ.setdefault("BOSDYN_CLIENT_PASSWORD", password)

    print(f"Connecting to Spot at {hostname}...")
    sdk = bosdyn.client.create_standard_sdk("estop_control")
    robot = sdk.create_robot(hostname)
    bosdyn.client.util.authenticate(robot)
    robot.sync_with_directory()
    robot.time_sync.wait_for_sync()

    estop_client = robot.ensure_client(EstopClient.default_service_name)
    endpoint = EstopEndpoint(estop_client, name="estop_control", estop_timeout=9.0)
    endpoint.force_simple_setup()

    keepalive = None
    estopped = True
    print("✅ Connected — e-stop endpoint registered")
    print("🛑 E-stop is ENGAGED (motors cannot power on)")
    print()
    print("Press Enter to toggle e-stop, Ctrl+C to quit.")
    print("Release the e-stop BEFORE telling the agent to power on.")

    try:
        while True:
            input()
            if estopped:
                keepalive = EstopKeepAlive(endpoint)
                estopped = False
                print("✅ E-stop RELEASED — motors can power on")
            else:
                if keepalive:
                    keepalive.stop()
                    keepalive.shutdown()
                    keepalive = None
                estopped = True
                print("🛑 E-stop ENGAGED — motors stopped")
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        if keepalive:
            keepalive.stop()
            keepalive.shutdown()
        print("Done.")


if __name__ == "__main__":
    main()
