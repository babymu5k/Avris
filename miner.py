from blake3 import blake3
import time
import requests
import random
import sys
from datetime import datetime
import json
import signal
import hashlib
from termcolor import colored

from concurrent.futures import ThreadPoolExecutor, as_completed

from groestlcoin_hash import getHash
import skein


_target_cache = {}
# ANSI color codes
COLORS = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "reset": "\033[0m",
}

# Terminal control codes
CLEAR_SCREEN = "\033[2J\033[H"
CURSOR_UP = "\033[1A"
CLEAR_LINE = "\033[2K"

config = json.load(open("src/data/config.json", "r"))
# Add to config.json loading
config = json.load(open("src/data/config.json", "r"))
threads = config.get("threads", 12)

def clear_screen():
    sys.stdout.write(CLEAR_SCREEN)
    sys.stdout.flush()


def move_cursor_up(lines=1):
    sys.stdout.write(CURSOR_UP * lines)
    sys.stdout.flush()


def clear_lines(count=1):
    for _ in range(count):
        sys.stdout.write(CLEAR_LINE)
        move_cursor_up()
    sys.stdout.write(CLEAR_LINE)
    sys.stdout.flush()


def get_node():
    response = requests.get(
        "https://raw.githubusercontent.com/babymu5k/avris/refs/heads/develop/nodelist.json"
    ).json()
    return random.choice(response["nodes"])


def get_mining_info(node):
    response = requests.get(f"{node}/mining/info")
    return response.json()


def get_miner_difficulty(node, address):
    """Check if miner has a custom difficulty"""
    response = requests.get(f"{node}/network/checkaddrdiff/{address}")
    return response.json()


def submit_block(node, block):
    response = requests.post(f"{node}/mining/submitblock", json=block)
    return response.json()


def proof_of_work_worker(last_proof, target_hex, start_nonce, end_nonce, result_dict):
    start_time = time.perf_counter()
    for nonce in range(start_nonce, end_nonce):
        elapsed = time.perf_counter() - start_time
        if elapsed > 0:
            hash_rate = nonce / elapsed
            print(colored(f"\r⛏ Mining... Elapsed: {elapsed:.2f}s", "light_grey"), end="")
            
        if valid_proof(last_proof, nonce, target_hex):
            result_dict['found'] = nonce
            return nonce
    return None

def proof_of_work(last_proof, target_hex, num_threads=4):
    start_time = time.perf_counter()
    result_dict = {'found': None}
    batch_size = 100000
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        nonce = 0
        while result_dict['found'] is None:
            futures = []
            for _ in range(num_threads):
                futures.append(executor.submit(
                    proof_of_work_worker, 
                    last_proof, target_hex, 
                    nonce, nonce + batch_size, 
                    result_dict
                ))
                nonce += batch_size
            
            for future in as_completed(futures):
                if result_dict['found'] is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
    
    end_time = time.perf_counter()
    hash_rate = nonce / (end_time - start_time) if (end_time - start_time) > 0 else 0
    return result_dict['found'], hash_rate

def check_mining_speed(node, miner_address):
    """Check if miner is going too fast and get current stats"""
    try:
        response = requests.get(
            f"{node}/network/checkaddrdiff/{miner_address}", timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("status") == "high", data
    except:
        pass
    return False, {}



def valid_proof(last_proof, proof, target_hex):
    # Cache target int conversion
    if target_hex not in _target_cache:
        _target_cache[target_hex] = int(target_hex, 16)
    target_int = _target_cache[target_hex]
    
    # Early simple hash before full chain
    guess = f"{last_proof}{proof}".encode()
    quick_hash = hashlib.sha256(guess).hexdigest()[:8]
    if int(quick_hash, 16) > target_int >> 192:  # Quick pre-check
        return False
    
    # Full hash chain
    guess_hash = blake3(guess).hexdigest().encode()
    guess_hash = skein.skein1024(guess_hash).hexdigest()
    guess_hash = getHash(guess_hash.encode(), len(guess_hash)).hex()
    
    return int(guess_hash, 16) <= target_int


def calculate_hash(block):
    block_string = f"{block['index']}{block['proofN']}{block['prev_hash']}{block['transactions']}{block['timestamp']}{block['mini_avr_root']}"
    return getHash(block_string.encode(), len(block_string)).hex()

def format_hash_rate(hash_rate):
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]
    unit_index = 0
    while hash_rate >= 1000 and unit_index < len(units) - 1:
        hash_rate /= 1000
        unit_index += 1
    return f"{hash_rate:.2f} {units[unit_index]}"


def print_header(address):
    clear_screen()
    print(f"{COLORS['cyan']}╔══════════════════════════════════════════════════╗")
    print(
        f"║{COLORS['yellow']}          AVRIS MINER v0.1.0 (Python)          {COLORS['cyan']}   ║"
    )
    print(
        f"║{COLORS['white']}                                                  {COLORS['cyan']}║"
    )
    print(
        f"║{COLORS['white']}              Created by Babymusk                 {COLORS['cyan']}║"
    )
    print(
        f"║{COLORS['white']}                                                  {COLORS['cyan']}║"
    )
    print(
        f"║{COLORS['white']}       Official miner for AVRIS Network        {COLORS['cyan']}   ║"
    )
    print(f"╚══════════════════════════════════════════════════╝{COLORS['reset']}")
    print(f"{COLORS['blue']}⏣  Connected to network: {COLORS['green']}AVRIS Mainnet")
    print(f"{COLORS['blue']}⏣  Miner address: {COLORS['yellow']}{address}")
    print(
        f"{COLORS['blue']}⏣  Started at {datetime.now().strftime('%I:%M:%S')}{COLORS['reset']}"
    )
    print("\n" + "-" * 60 + "\n")  # Separator line
    print(f"{COLORS['cyan']}⚙  Current Stats:{COLORS['reset']}\n")


def print_block_result(result, hash_rate, block_time):
    if isinstance(result, dict) and "index" in result:
        # Successful block
        print(
            f"\n[{datetime.fromtimestamp(time.time()):%I:%M:%S}] {COLORS['green']} ✔  Block accepted!  {COLORS['white']}│ {COLORS['blue']}Hashrate: {COLORS['yellow']}{format_hash_rate(hash_rate)} {COLORS['white']}│ {COLORS['blue']}Time: {COLORS['yellow']}{block_time:.2f}s{COLORS['reset']} │ {COLORS['blue']}New height: {COLORS['yellow']}{result['index']}{COLORS['reset']}"
        )
    else:
        # Failed block - handle different error formats
        if isinstance(result, dict):
            if result.get("status") == "error":
                reason = result.get("message", "Unknown error")
                if "required_difficulty" in result:
                    reason += f" (Current multiplier: {result.get('your_difficulty_multiplier', 1.0)}x)"
            else:
                reason = str(result)
        else:
            reason = result["message"]

        print(
            f"\n{COLORS['red']}✖  Block rejected  {COLORS['white']}│ {COLORS['blue']}Reason: {COLORS['yellow']}{reason}{COLORS['reset']}"
        )
        # print(f"{COLORS['cyan']}   Tip: Try reducing your mining speed to lower your difficulty multiplier{COLORS['reset']}\n")


def print_mining_stats(diff, hash_rate, block_height, blocks_mined):
    if blocks_mined % 5 == 0:  # Only show stats every 5 blocks
        print(
            f"\n{COLORS['green']}⚙  Mining info  {COLORS['white']}│ {COLORS['blue']}Difficulty: {COLORS['yellow']}{diff} {COLORS['white']}│ {COLORS['blue']}Hashrate: {COLORS['yellow']}{format_hash_rate(hash_rate)} {COLORS['white']}│ {COLORS['blue']}Height: {COLORS['yellow']}{block_height}{COLORS['reset']}"
        )


def mine():
    node = get_node()
    print_header(config["address"])
    miner_address = config["address"]
    blocks_mined = 0  # Add counter for mined blocks
    blocks_mined = 0
    
    print(colored(f"Using {threads} threads!", "green"))

    while True:
        try:
            # Get current mining info
            mining_data = get_mining_info(node)
            latest_block = mining_data["latestblock"]
            diff = mining_data["difficulty"]
            target_hex = mining_data["target"]
            last_proof = latest_block["proofN"]
            
            # Start mining with warning callback
            start_time = time.time()
            proof, hash_rate = proof_of_work(last_proof, target_hex, num_threads=threads)
            block_time = time.time() - start_time

            # Print mining stats
            print_mining_stats(
                diff, hash_rate, latest_block["index"], blocks_mined
            )

            # Check if block is still valid
            new_mining_data = get_mining_info(node)
            if new_mining_data["latestblock"]["index"] != latest_block["index"]:
                print(
                    f"{COLORS['yellow']}⚠  New block found by another miner. Restarting...{COLORS['reset']}"
                )
                time.sleep(1)
                continue

            # Prepare and submit block
            new_block = {
                "index": latest_block["index"] + 1,
                "proofN": proof,
                "prev_hash": calculate_hash(latest_block),
                "miner_address": miner_address,
                "timestamp": time.time(),
            }

            result = submit_block(node, new_block)
            if isinstance(result, dict) and "index" in result:
                blocks_mined += 1
            print_block_result(result, hash_rate, block_time)

            time.sleep(1)

        except Exception as e:
            print(
                f"{COLORS['red']}⚠  Connection error: {e}. Reconnecting...{COLORS['reset']}"
            )
            time.sleep(5)
            node = get_node()


if __name__ == "__main__":
    clear_screen()
    try:
        mine()
    except KeyboardInterrupt:
        print(
            f"{COLORS['blue']} Ctrl-C Detected... Exiting gracefully... {COLORS['reset']}"
        )
