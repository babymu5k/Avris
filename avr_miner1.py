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
from typing import Optional, Dict, Any, List
from termcolor import colored
import random
import os


class AVRISMinersBridge:
    def __init__(
        self,
        node_url = None,
        serial_ports: Optional[List[str]] = None,
        baud_rate: int = 115200,
        miner_address: Optional[str] = None,
        config_file: str = "miner_config.json"
    ):
        """
        Bridge between multiple Arduino miners and Avris blockchain.

        Args:
            node_url: URL of your blockchain node (e.g., "http://localhost:4024")
            serial_ports: List of COM ports for Arduinos (e.g., ["COM3", "COM4"])
            baud_rate: Serial communication speed
            miner_address: Your miner's wallet address
            config_file: File to save/load port configurations
        """
        node_url = requests.get("https://raw.githubusercontent.com/babymu5k/avris/refs/heads/develop/nodelist.json").json()
        node_url = random.choice(node_url["nodes"])
        self.node_url = node_url
        self.baud_rate = baud_rate
        self.miner_address = miner_address
        self.config_file = config_file
        
        # Multiple miners support
        self.miners = []  # List of dicts: {'port': port, 'conn': serial_conn, 'hash_count': 0}
        self.current_job = None
        self.is_mining = False
        self.total_hash_count = 0
        self.start_time = time.time()

        # Load saved ports if no ports specified
        if serial_ports is None:
            serial_ports = self._load_saved_ports()
        
        # Auto-detect if still no ports
        if not serial_ports:
            detected_ports = self._detect_arduino_ports()
            if detected_ports:
                serial_ports = detected_ports
                # Save detected ports
                self._save_ports(serial_ports)
        
        self.serial_ports = serial_ports

        # Stats
        self.stats = {
            "blocks_mined": 0,
            "hashes_total": 0,
            "avg_hashrate": 0,
            "uptime": 0,
            "active_miners": 0
        }

        # API endpoints from your main.py
        self.endpoints = {
            "mining_info": f"{node_url}/mini/mining/info",
            "submit_block": f"{node_url}/mini/mining/submitblock",
            "network_info": f"{node_url}/network/info",
            "fee_estimate": f"{node_url}/network/fee_estimate",
        }

        print(f"AVRIS Arduino Miner v0.2")
        print(f"Connect to Node: {node_url}")
        print(f"Miners to connect: {len(self.serial_ports)}")
        if miner_address:
            print(f"Miner Address: {miner_address}")

    def _load_saved_ports(self) -> List[str]:
        """Load saved COM ports from config file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    ports = config.get('serial_ports', [])
                    if ports:
                        print(f"Loaded {len(ports)} saved ports from {self.config_file}")
                    return ports
        except Exception as e:
            print(f"Error loading config: {e}")
        return []

    def _save_ports(self, ports: List[str]):
        """Save COM ports to config file"""
        try:
            config = {'serial_ports': ports}
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Saved {len(ports)} ports to {self.config_file}")
        except Exception as e:
            print(f"Error saving config: {e}")

    def _detect_arduino_ports(self) -> List[str]:
        """Automatically detect multiple Arduino ports"""
        ports_found = []
        ports = serial.tools.list_ports.comports()
        
        for port in ports:
            # Common Arduino identifiers
            if (
                "ARDUINO" in port.description.upper()
                or "CH340" in port.description.upper()
                or "USB SERIAL" in port.description.upper()
                or "USB2.0" in port.description.upper()
            ):
                print(f"Detected Arduino at: {port.device}")
                ports_found.append(port.device)
        
        if ports_found:
            print(f"Auto-detected {len(ports_found)} Arduino(s)")
        else:
            print("No Arduinos detected automatically.")
        
        return ports_found
    
    def connect_miners(self) -> int:
        """Establish serial connections to all Arduino miners"""
        connected_count = 0
        
        for port in self.serial_ports:
            try:
                conn = serial.Serial(
                    port=port,
                    baudrate=self.baud_rate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=1,
                )
                
                miner_info = {
                    'port': port,
                    'conn': conn,
                    'hash_count': 0,
                    'last_active': time.time(),
                    'current_job_index': None,  # **ADD THIS**
                }
                self.miners.append(miner_info)
                connected_count += 1
                print(f"Connected to miner at {port}")
                
                # Send initial ping
                conn.write(b"PING\n")
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Failed to connect to {port}: {e}")
        
        self.stats['active_miners'] = connected_count
        print(f"Successfully connected to {connected_count}/{len(self.serial_ports)} miners")
        return connected_count

    def send_job_to_all_miners(self, job: Dict[str, Any]) -> int:
        """Send mining job to all connected Arduinos"""
        if not self.miners:
            print("No miners connected")
            return 0
        
        # **FIX**: Clear any existing "found" flags or state
        # Format: JOB:index:last_proof:prev_hash:difficulty:target
        target_zeros = "0" * job["difficulty"]
        job_string = f"JOB:{job['index']}:{job['last_proof']}:{job['prev_hash']}:{job['difficulty']}:{target_zeros}\n"
        
        sent_count = 0
        for miner in self.miners:
            try:
                # **FIX**: Send STOP first to cancel any ongoing mining
                miner['conn'].write(b"STOP\n")
                miner['conn'].flush()
                time.sleep(0.5)  # Small delay
                
                # Now send new job
                miner['conn'].write(job_string.encode("utf-8"))
                miner['conn'].flush()
                sent_count += 1
                
                # Mark that this miner is working on this job
                miner['current_job_index'] = job['index']
                
            except Exception as e:
                print(f"Failed to send job to {miner['port']}: {e}")
        
        if sent_count > 0:
            print(f"Sent job #{job['index']} to {sent_count} miner(s) (difficulty: {job['difficulty']})")
        
        return sent_count

    def listen_to_all_miners(self):
        """Listen for messages from all Arduinos"""
        for miner in self.miners:
            try:
                while miner['conn'].in_waiting > 0:
                    line = miner['conn'].readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self.process_arduino_message(line, miner['port'])
            except Exception as e:
                print(f"Error reading from {miner['port']}: {e}")

    def process_arduino_message(self, message: str, port: str):
        """Process messages from Arduino"""
        print(f"[{port}] {message}")

        # Handle different message types
        if message.startswith("FOUND "):
            # Format: FOUND nonce hash
            parts = message.split(" ")
            if len(parts) == 3:
                nonce = parts[1]
                hash_found = parts[2]
                self.submit_solution(nonce, hash_found)

        elif message.startswith("STATS "):
            # Arduino reporting its stats
            parts = message.split(" ")
            if len(parts) >= 3:
                hash_increment = int(parts[1])
                self.total_hash_count += hash_increment
                self.stats["hashes_total"] = self.total_hash_count
                
                # Update individual miner stats
                for miner in self.miners:
                    if miner['port'] == port:
                        miner['hash_count'] += hash_increment
                        miner['last_active'] = time.time()
                        break

        elif message.startswith("ERROR"):
            print(f"Arduino error on {port}: {message}")

        elif message.startswith("READY"):
            print(f"Miner at {port} is ready")
            # Request new job if we don't have one
            if not self.current_job:
                self.request_new_job()

        elif message.startswith("PONG"):
            print(f"Miner at {port} is responsive")


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

        # Store the job index we're submitting for
        submitted_job_index = self.current_job["index"]
        
        submission = {
            "index": submitted_job_index,
            "proofN": int(nonce),
            "prev_hash": self.current_job["prev_hash"],
            "miner_address": self.miner_address,
            "timestamp": time.time(),
        }

        print(f"Submitting block #{submission['index']} with nonce {nonce}...")

        try:
            # Use the node_url directly for the endpoint
            submit_url = f"{self.node_url}/mini/mining/submitblock"
            response = requests.post(
                submit_url, json=submission, timeout=10
            )

            if response.status_code == 201:
                print(f"SUCCESS! Block #{submission['index']} accepted!")
                self.stats["blocks_mined"] += 1

                # Broadcast success to all miners
                self.broadcast_to_miners("SUCCESS")
                
                # **CRITICAL FIX**: Clear current job so ALL miners get new job
                self.current_job = None

                # Request new job
                time.sleep(1)  # Brief pause
                self.request_new_job()
                return True

            else:
                error_msg = response.json().get("message", "Unknown error")
                print(f"Block rejected: {error_msg}")

                # Check if this is because network moved on
                if "invalid proof" in error_msg.lower() or "stale" in error_msg.lower():
                    # **CRITICAL FIX**: Check current network height
                    print("Block rejected as invalid/stale. Checking if network moved on...")
                    try:
                        # Get current network info
                        network_response = requests.get(
                            f"{self.node_url}/network/info", timeout=3
                        )
                        if network_response.status_code == 200:
                            current_height = network_response.json()["height"]
                            
                            # If network is ahead of our submitted job
                            if current_height >= submitted_job_index:
                                print(f"Network is at block #{current_height}, clearing job #{submitted_job_index}")
                                self.current_job = None
                                self.request_new_job()
                                return False
                    except Exception as e:
                        print(f"Error checking network height: {e}")
                        # Still clear job to be safe
                        self.current_job = None
                        self.request_new_job()
                        return False
                
                # Inform all miners
                self.broadcast_to_miners(f"REJECTED:{error_msg}")
                
                return False

        except Exception as e:
            print(f"Error submitting block: {e}")
            # Clear job on network error
            self.current_job = None
            return False


    def request_new_job(self):
        """Request and send a new mining job to all Arduinos"""
        print("Requesting new mining job...")
        self.current_job = self.get_mining_job()
        if self.current_job:
            sent = self.send_job_to_all_miners(self.current_job)
            if sent == 0:
                print("Warning: Job sent to 0 miners")
        else:
            print("Failed to get new job. Will retry in 10 seconds...")
            time.sleep(10)
            self.request_new_job()
            
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

                # Add Avris Guard multiplier if applicable
                if self.miner_address:
                    try:
                        guard_response = requests.get(
                            f"{self.node_url}/network/checkaddrdiff/{self.miner_address}",
                            timeout=3,
                        )
                        if guard_response.status_code == 200:
                            guard_data = guard_response.json()
                            job["difficulty_multiplier"] = guard_data.get(
                                "difficulty_multiplier", 1.0
                            )
                    except:
                        job["difficulty_multiplier"] = 1.0

                return job
            else:
                print(f"Failed to get mining job: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"Error getting mining job: {e}")
            return None

    def broadcast_to_miners(self, message: str):
        """Broadcast a message to all connected miners"""
        for miner in self.miners:
            try:
                miner['conn'].write(f"{message}\n".encode("utf-8"))
            except Exception as e:
                print(f"Failed to broadcast to {miner['port']}: {e}")

    def check_miner_health(self):
        """Check if all miners are still connected and responsive"""
        for miner in self.miners[:]:  # Use slice copy for safe removal
            try:
                # Send a ping every 30 seconds if no activity
                if time.time() - miner['last_active'] > 30:
                    miner['conn'].write(b"PING\n")
            except Exception as e:
                print(f"Miner at {miner['port']} disconnected: {e}")
                try:
                    miner['conn'].close()
                except:
                    pass
                self.miners.remove(miner)
                self.stats['active_miners'] = len(self.miners)
                print(f"Miner removed. Active miners: {self.stats['active_miners']}")

    def calculate_total_hashrate(self) -> float:
        """Calculate combined hashrate of all miners"""
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.total_hash_count / elapsed
        return 0.0

    def print_stats(self):
        """Print mining statistics for all miners"""
        elapsed = time.time() - self.start_time
        total_hashrate = self.calculate_total_hashrate()

        print("\n" + "=" * 60)
        print(f"AVRIS Mining Stats (Multi-Miner)")
        print(f"Active Miners: {self.stats['active_miners']}/{len(self.serial_ports)}")
        print(f"Uptime: {datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {elapsed:.0f} seconds")
        print(f"Blocks Mined: {self.stats['blocks_mined']}")
        print(f"Total Hashes: {self.total_hash_count:,}")
        print(f"Combined Hashrate: {total_hashrate:.2f} H/s")
        
        # Individual miner stats
        if self.miners:
            print("\nIndividual Miner Stats:")
            for i, miner in enumerate(self.miners, 1):
                miner_hashrate = miner['hash_count'] / max(elapsed, 1)
                uptime = time.time() - miner.get('connected_at', self.start_time)
                print(f"  Miner {i} ({miner['port']}): {miner['hash_count']:,} hashes, {miner_hashrate:.1f} H/s")

        if self.current_job:
            print(f"\nCurrent Job: Block #{self.current_job['index']}")
            print(f"Difficulty: {self.current_job['difficulty']}")

        print("=" * 60 + "\n")

    # Keep existing methods from original class (they should work as-is with self.miners)
    # Only the interface changes, internal logic remains similar
    
    # ... [All other methods remain exactly the same as original, just using self.miners list]
    # The get_mining_job, submit_solution, background_checker, etc. remain unchanged
    # except they now work with multiple miners through the methods above

    def check_for_new_block(self):
        """Background check: see if network has new block"""
        index = self.current_job
        try:
            response = requests.get(f"{self.node_url}/network/info", timeout=3)
            if response.status_code == 200:
                current_height = response.json()["height"]  # Current chain height

                # If we have no current job OR network has advanced
                if not self.current_job or self.current_job["index"] >= current_height:
                    print(
                        f"Network advanced to height {current_height}, fetching new job..."
                    )
                    self.request_new_job()
                    return True

        except Exception as e:
            print(f"Block check failed: {e}")
        return False

    def background_checker(self):
        """Run in a thread to periodically check for new blocks"""
        while self.is_mining:
            self.check_for_new_block()
            time.sleep(10)  # Check every 10 seconds

    def run(self):
        """Main mining loop for multiple miners"""
        connected = self.connect_miners()
        if connected == 0:
            print("Failed to connect to any miners. Exiting...")
            return

        print(f"Starting AVRIS miner bridge with {connected} miner(s)...")
        print("Press Ctrl+C to stop\n")

        self.is_mining = True
        stats_timer = time.time()
        health_timer = time.time()
        block_timer = time.time()

        # Initial handshake
        time.sleep(2)
        self.broadcast_to_miners("PING")

        # # Start background checker
        # checker_thread = threading.Thread(target=self.background_checker, daemon=True)
        # checker_thread.start()

        try:
            while self.is_mining:
                # Listen to all miners
                self.listen_to_all_miners()
                
                # Check miner health every 15 seconds
                if time.time() - health_timer > 15:
                    self.check_miner_health()
                    health_timer = time.time()
                    
                if time.time() - block_timer > 15:
                    self.background_checker()
                
                # Print stats every 30 seconds
                if time.time() - stats_timer > 30:
                    self.print_stats()
                    stats_timer = time.time()
                
                # Check if we need a new job
                if not self.current_job:
                    self.check_for_new_block()
                
                time.sleep(0.1)

        except KeyboardInterrupt:
            print("\nStopping all miners...")
            self.is_mining = False
            self.broadcast_to_miners("STOP")
            
            # Close all connections
            for miner in self.miners:
                try:
                    miner['conn'].close()
                except:
                    pass
            
            # Save current port list
            active_ports = [miner['port'] for miner in self.miners]
            self._save_ports(active_ports)
            
            print(f"Miner stopped. Saved {len(active_ports)} active ports to config.")


# Updated command line interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AVRIS Arduino Miner Bridge (Multi-Miner Support)")
    parser.add_argument(
        "--node", help="Blockchain node URL"
    )
    parser.add_argument("--ports", nargs='+', help="Serial ports (e.g., COM3 COM4 /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--address", required=True, help="Your miner wallet address")
    parser.add_argument("--config", default="miner_config.json", help="Config file path")

    args = parser.parse_args()

    # Create and run miner bridge
    miner = AVRISMinersBridge(
        node_url=args.node,
        serial_ports=args.ports,
        baud_rate=args.baud,
        miner_address=args.address,
        config_file=args.config
    )

    miner.run()