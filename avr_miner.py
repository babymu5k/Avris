"""
avr_miner.py - Bridge between Arduino miners and the Avris blockchain node
Copyright (C) 2024 Babymusk

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json
import time
import requests
import threading
import serial
import serial.tools.list_ports
from datetime import datetime
from typing import Optional, Dict, Any
from termcolor import colored
import random


class AVRSMinerBridge:
    def __init__(
        self,
        node_url = None,
        serial_port: Optional[str] = None,
        baud_rate: int = 115200,
        miner_address: Optional[str] = None,
    ):
        """
        Bridge between Arduino miners and Avris blockchain.

        Args:
            node_url: URL of your blockchain node (e.g., "http://localhost:4024")
            serial_port: COM port for Arduino (e.g., "COM3" or "/dev/ttyUSB0")
            baud_rate: Serial communication speed
            miner_address: Your miner's wallet address
        """
        node_url = requests.get("https://raw.githubusercontent.com/babymu5k/avris/refs/heads/develop/nodelist.json").json()
        node_url = random.choice(node_url["nodes"])
        self.node_url = node_url
        self.baud_rate = baud_rate
        self.miner_address = miner_address
        self.current_job = None
        self.is_mining = False
        self.hash_count = 0
        self.start_time = time.time()

        # Serial connection
        self.serial_conn = None
        self.serial_port = (
            self._detect_arduino_port() if serial_port is None else serial_port
        )

        # Stats
        self.stats = {
            "blocks_mined": 0,
            "hashes_total": 0,
            "avg_hashrate": 0,
            "uptime": 0,
        }

        # API endpoints from your main.py
        self.endpoints = {
            "mining_info": f"{node_url}/mini/mining/info",
            "submit_block": f"{node_url}/mini/mining/submitblock",
            "network_info": f"{node_url}/network/info",
            "fee_estimate": f"{node_url}/network/fee_estimate",
        }
        
        print(colored("AVRIS Arduino Miner v0.1", "white", "on_blue"))
        print(colored(f"Connect to Node: {node_url}", "white", "on_blue"))
        print(colored(f"Serial: {self.serial_port} @ {baud_rate} baud", "white", "on_blue"))
        if miner_address:
            print(colored(f"Address: {miner_address}", "white", "on_cyan"))

    def _detect_arduino_port(self) -> Optional[str]:
        """Automatically detect Arduino port"""
        ports = serial.tools.list_ports.comports()
        for port in ports:
            # Common Arduino identifiers
            if (
                "ARDUINO" in port.description.upper()
                or "CH340" in port.description.upper()
                or "USB SERIAL" in port.description.upper()
            ):
                print(f"Detected Arduino at: {port.device}")
                return port.device

        print("No Arduino detected automatically. Please specify port with --port")
        return None

    def connect_serial(self) -> bool:
        """Establish serial connection to Arduino"""
        if not self.serial_port:
            print(colored("ERROR: No serial port specified", "white", "on_red"))
            return False

        try:
            self.serial_conn = serial.Serial(
                port=self.serial_port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,  # 1 second timeout
            )
            print(colored(f"Connected to {self.serial_port}", "white", "on_green"))
            return True
        except Exception as e:
            print(colored(f"Failed to connect to {self.serial_port}: {e}", "white", "on_red"))
            return False

    def get_mining_job(self) -> Optional[Dict[str, Any]]:
        """Get current mining job from the node"""
        try:
            response = requests.get(self.endpoints["mining_info"], timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_block = data["latestblock"]

                job = {
                    "index": latest_block["index"] + 1,
                    "last_proof": latest_block["proofN"],
                    "prev_hash": latest_block["hash"],
                    "difficulty": data["difficulty"],
                    "timestamp": time.time(),
                }

                return job
            else:
                print(colored(f"Failed to get mining job: HTTP {response.status_code}", "white", "on_red"))
                return None
        except Exception as e:
            print(colored(f"Error getting mining job: {e}", "white", "on_red"))
            return None

    def send_job_to_arduino(self, job: Dict[str, Any]) -> bool:
        """Send mining job to Arduino in a simple format"""
        if not self.serial_conn or not self.serial_conn.is_open:
            print(colored("Serial port not connected", "white", "on_red"))
            return False

        # Format: JOB:index:last_proof:prev_hash:difficulty:target
        # Target is the required leading zeros (e.g., "000" for difficulty 3)
        target_zeros = "0" * job["difficulty"]

        job_string = f"JOB:{job['index']}:{job['last_proof']}:{job['prev_hash']}:{job['difficulty']}:{target_zeros}\n"

        try:
            self.serial_conn.write(job_string.encode("utf-8"))
            self.serial_conn.flush()
            # print(colored(
            #     f"Sent job #{job['index']} to Arduino (difficulty: {job['difficulty']})"
            # , "white", "on_green"))
            return True
        except Exception as e:
            print(colored(f"Failed to send job to Arduino: {e}", "white", "on_red"))
            return False

    def listen_to_arduino(self):
        """Listen for messages from Arduino"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return

        try:
            while self.serial_conn.in_waiting > 0:
                line = (
                    self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
                )
                if line:
                    self.process_arduino_message(line)
        except Exception as e:
            print(colored(f"Error reading from Arduino: {e}", "white", "on_red"))

    def process_arduino_message(self, message: str):
        """Process messages from Arduino"""
        # Handle different message types
        if message.startswith("FOUND "):
            # Format: FOUND nonce hash
            parts = message.split(" ")
            if len(parts) == 3:
                nonce = parts[1]
                hash_found = parts[2]
                self.submit_solution(nonce, hash_found)
                
            print(colored(f"[ARDUINO]:", "black", "on_yellow"), end="")
            print(colored(f" Found Block!", "white"))

        elif message.startswith("STATS "):
            print(colored(f"[ARDUINO]", "white", "on_blue"), end=":")
            print(colored(message, "light_grey"))
            # Arduino reporting its stats
            parts = message.split(" ")
            if len(parts) >= 3:
                self.hash_count += int(parts[1])
                self.stats["hashes_total"] = self.hash_count

        elif message.startswith("ERROR"):
            print(colored(f"[ARDUINO]", "white", "on_blue"), end=":")
            print(colored(message, "light_grey"))
            print(f"Arduino error: {message}")
            # Handle specific Arduino errors by restarting job
            if "invalid proof" in message.lower() or "index" in message.lower():
                print("Arduino reported invalid data, requesting fresh job...")
                self.current_job = None
                self.request_new_job()

        elif message.startswith("READY"):
            # Request new job immediately
            self.request_new_job()
            

    def submit_solution(self, nonce: str, hash_found: str) -> bool:
        """Submit found solution to the blockchain node"""
        if not self.miner_address:
            print("ERROR: No miner address set. Cannot submit block.")
            return False

        # Get current job to build submission
        if not self.current_job:
            print("ERROR: No current job. Getting new job...")
            self.current_job = self.get_mining_job()
            if not self.current_job:
                print("ERROR: Cannot get current job for submission")
                return False

        submission = {
            "index": self.current_job["index"],
            "proofN": int(nonce),
            "prev_hash": self.current_job["prev_hash"],
            "miner_address": self.miner_address,
            "timestamp": time.time(),
        }

        #print(f"Submitting block #{submission['index']} with nonce {nonce}...")

        try:
            response = requests.post(
                self.endpoints["submit_block"], json=submission, timeout=10
            )

            if response.status_code == 201:
                print(colored(f"SUCCESS! Block #{submission['index']} accepted!", "white", "on_blue"))
                self.stats["blocks_mined"] += 1

                # Broadcast success to Arduino
                if self.serial_conn and self.serial_conn.is_open:
                    self.serial_conn.write(b"SUCCESS\n")

                # Clear current job and request new job
                self.current_job = None
                time.sleep(1)  # Brief pause
                self.request_new_job()
                return True

            else:
                error_msg = response.json().get("message", "Unknown error")
                print(f"Block rejected: {error_msg}")

                # Check if the error indicates stale/invalid data
                if "invalid proof" in error_msg.lower() or "stale" in error_msg.lower():
                    print("Block data is stale/invalid, clearing job and updating...")
                    self.current_job = None
                    # Don't send REJECTED message to Arduino since we're clearing job
                    time.sleep(1)
                    self.request_new_job()
                    return False
                
                # For other errors, inform Arduino
                if self.serial_conn and self.serial_conn.is_open:
                    self.serial_conn.write(f"REJECTED:{error_msg}\n".encode())

                return False

        except Exception as e:
            print(f"Error submitting block: {e}")
            # On network error, clear job to get fresh data
            self.current_job = None
            return False

    def request_new_job(self):
        """Request and send a new mining job to Arduino"""
        # Send STOP to Arduino first to ensure it stops mining old job
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(b"STOP\n")
                self.serial_conn.flush()
                time.sleep(0.3)  # Small delay
            except:
                pass
        
        self.current_job = self.get_mining_job()
        if self.current_job:
            self.send_job_to_arduino(self.current_job)
        else:
            print(colored("Failed to get new job. Will retry in 5 seconds...", "white", "on_red"))
            time.sleep(5)
            self.request_new_job()

    def calculate_hashrate(self) -> float:
        """Calculate current hashrate"""
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.hash_count / elapsed
        return 0.0

    def print_stats(self):
        """Print mining statistics"""
        elapsed = time.time() - self.start_time
        hashrate = self.calculate_hashrate()

        print("\n" + "=" * 50)
        print(f"AVRIS Mining Stats")
        print(
            f"Uptime: {datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Duration: {elapsed:.0f} seconds")
        print(f"Blocks Mined: {self.stats['blocks_mined']}")
        print(f"Total Hashes: {self.hash_count:,}")
        print(f"Hashrate: {hashrate:.2f} H/s")

        if self.current_job:
            print(f"Current Job: Block #{self.current_job['index']}")
            print(f"Difficulty: {self.current_job['difficulty']}")

        print("=" * 50 + "\n")

    def check_for_new_block(self):
        """Background check: see if network has new block"""
        try:
            response = requests.get(f"{self.node_url}/network/info", timeout=3)
            if response.status_code == 200:
                current_height = response.json()["height"]  # Current chain height

                # If we have no current job OR network has advanced
                if not self.current_job or self.current_job["index"] <= current_height:
                    print(
                        f"Network at height {current_height}, fetching new job..."
                    )
                    self.current_job = None
                    self.request_new_job()
                    return True

        except Exception as e:
            print(f"Block check failed: {e}")
        return False

    def background_checker(self):
        """Run in a thread to periodically check for new blocks"""
        while self.is_mining:
            self.check_for_new_block()
            time.sleep(5)  # Check every 5 seconds (more frequently)

    def run(self):
        """Main mining loop"""
        if not self.connect_serial():
            print("Failed to connect to Arduino. Exiting...")
            return

        print("Starting AVRIS miner bridge...")
        print("Press Ctrl+C to stop\n")

        # Initial handshake with Arduino
        time.sleep(2)  # Wait for Arduino to boot
        # self.serial_conn.write(b"PING\n")

        self.is_mining = True
        stats_timer = time.time()
        job_refresh_timer = time.time()

        checker_thread = threading.Thread(target=self.background_checker, daemon=True)
        checker_thread.start()

        try:
            while self.is_mining:
                # Listen for Arduino messages
                self.listen_to_arduino()

                # Print stats every 30 seconds
                if time.time() - stats_timer > 30:
                    self.print_stats()
                    stats_timer = time.time()
                
                # Force job refresh every 60 seconds to prevent stale jobs
                if time.time() - job_refresh_timer > 60:
                    if self.current_job:
                        print("Periodic job refresh...")
                        self.current_job = None
                        self.request_new_job()
                    job_refresh_timer = time.time()

                # Check if we need a new job
                if not self.current_job:
                    self.request_new_job()

                time.sleep(0.1)  # Small delay to prevent CPU overload

        except KeyboardInterrupt:
            print("\nStopping miner...")
            self.is_mining = False
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.write(b"STOP\n")
                self.serial_conn.close()
            print("Miner stopped.")


# Command line interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AVRIS Arduino Miner Bridge")
    parser.add_argument(
        "--node", help="Blockchain node URL"
    )
    parser.add_argument("--port", help="Serial port (e.g., COM3 or /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--address", required=True, help="Your miner wallet address")

    args = parser.parse_args()

    # Create and run miner bridge
    miner = AVRSMinerBridge(
        node_url=args.node,
        serial_port=args.port,
        baud_rate=args.baud,
        miner_address=args.address,
    )

    miner.run()