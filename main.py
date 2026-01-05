"""
main.py handles the core blockchain
Copyright (C) 2024 Babymusk

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

"""

import asyncio
import hashlib
import os
import random
import secrets
import time

import requests
import sanic_jinja2
import ujson as jsonify
from blake3 import blake3
from jinja2 import FileSystemLoader
from sanic import Sanic
from sanic.response import json, text
from sanic_ext import openapi
from src.node.addressgen import AddressGen
from src.node.block import Block, MiniAVRBlock
from src.node.mempool import Mempool, MempoolFullError
from src.node.P2P import P2PNetwork
from src.node.startup import greeter
from termcolor import colored
from web3 import Web3

from src.node.TxDecoder import EthTxDecoder
import skein

from Crypto.Hash import keccak

from groestlcoin_hash import getHash

with open("src/data/words.txt") as f:
    WORDLIST = [line.strip() for line in f]
    f.close()


class MiniAvrChain:

    def __init__(self, blockchain):
        self.mini_chain = self.LoadDB()  # Pending mini-blocks
        self.blockchain = blockchain
        self.construct_genesis()

        self.mini_difficulty = 1
        self.mini_reward = 1
        self.block_time_target = 30
        self.adjustment_interval = 72  # Every 36 minutes

        self.save_flag = True
        self.mini_difficulty = self.adjust_difficulty()

    def construct_genesis(self):
        if not self.mini_chain:
            print(colored("CREATING THE MINI GENESIS", "green"))
            mini_block = MiniAVRBlock(
                index=0, proofN=0, prev_hash="0" * 40, miner_address="None"
            )
            self.mini_chain.append(mini_block)
            self.SaveDB()

    def submit_mini_solution(self, mini_proofN, prev_hash, miner_address):
        """Arduino submits a found mini-block"""
        # Verify mini-proof (SHA1, low difficulty)
        if not self.verifying_proof(
            self.latest_block.proofN, mini_proofN, self.mini_difficulty
        ):
            return (
                {
                    "status": "error",
                    "message": f"Proof doesn't meet required difficulty (needed: {self.mini_difficulty})",
                },
                400,
            )

        # Create mini-block
        mini_index = len(self.mini_chain)
        mini_block = MiniAVRBlock(
            index=mini_index,
            proofN=mini_proofN,
            prev_hash=prev_hash or "0" * 40,
            miner_address=miner_address,
        )

        # Add to pending mini-chain
        self.mini_chain.append(mini_block)

        # Create reward transaction immediately
        reward_tx = {
            "sender": "node",
            "recipient": miner_address,
            "quantity": self.mini_reward,
            "memo": f"Mini-AVR block #{mini_index}",
        }

        # Add to mempool (will be included in next main block)
        self.blockchain.new_data(
            "node", miner_address, self.mini_reward, f"Mini-AVR block #{mini_index}"
        )
        self.blockchain.balances[miner_address] = (
            self.blockchain.balances.get(miner_address, 0) + self.mini_reward
        )
        self.adjust_difficulty()

        return mini_block

    def get_mini_mining_job(self):
        """Get a mining job for Arduino/ESP"""
        last_mini_hash = self.mini_chain[-1].hash if self.mini_chain else "0" * 40

        return {
            "prev_mini_hash": last_mini_hash,
            "difficulty": self.mini_difficulty,
            "target": "0" * self.mini_difficulty,
            "mini_reward": self.mini_reward,
        }

    def verifying_proof(self, last_proof, proof, difficulty=None):
        """Modified to accept optional custom difficulty"""
        guess = f"{last_proof}{proof}".encode()
        guess_hash = hashlib.sha1(guess).hexdigest()

        if not guess_hash.startswith("0" * self.mini_difficulty):
            return False
        else:
            return True

    def create_merkle_root(self):
        """Create Merkle root of all pending mini-blocks"""
        if not self.mini_chain:
            return "None"

        # Simple Merkle tree: hash all mini-block hashes together
        hashes = [block.hash for block in self.mini_chain]

        while len(hashes) > 1:
            new_hashes = []
            for i in range(0, len(hashes), 2):
                if i + 1 < len(hashes):
                    combined = hashes[i] + hashes[i + 1]
                else:
                    combined = hashes[i] + hashes[i]  # Duplicate if odd
                new_hashes.append(blake3(combined.encode()).hexdigest())
            hashes = new_hashes

        return hashes[0] if hashes else "None"

    def SaveDB(self):
        """Only save when chain has changed"""
        if not self.save_flag:
            return

        # Use atomic write to prevent corruption
        temp_path = "src/data/minichain.json.tmp"
        with open(temp_path, "w") as f:
            jsonify.dump([block.to_dict() for block in self.mini_chain], f)

        # Atomic rename (works on Unix/Windows)
        os.replace(temp_path, "src/data/minichain.json")
        # print(colored("Blockchain Database SAVED!", "green"))

    def LoadDB(self):
        self.save_flag = False
        if os.path.exists("src/data/minichain.json"):
            print(colored("minichain Database FOUND!", "green"))
            db = jsonify.load(open("src/data/minichain.json", "r"))
            chain = [MiniAVRBlock.from_dict(block_dict) for block_dict in db]
            # print(chain)
            return chain
        else:
            print(colored("Couldnt Find A DB in src/data/ :("))
            return []

    def adjust_difficulty(self):
        """More sophisticated difficulty adjustment algorithm"""
        if len(self.mini_chain) % self.adjustment_interval == 0:
            # Calculate block time ratio
            actual_time = (
                self.mini_chain[-1].timestamp
                - self.mini_chain[-self.adjustment_interval].timestamp
            )
            expected_time = self.block_time_target * self.adjustment_interval
            ratio = actual_time / expected_time

            # Dynamic smoothing factor (α)
            if not hasattr(self, "difficulty_ema"):
                self.difficulty_ema = 1.0  # Initialize

            # Choose α based on market conditions
            if abs(ratio - self.difficulty_ema) > 0.3:
                alpha = 0.5  # Aggressive for large deviations
            else:
                alpha = 0.3  # Conservative otherwise

            # Update EMA
            self.difficulty_ema = alpha * ratio + (1 - alpha) * self.difficulty_ema

            # Adjust difficulty
            if self.difficulty_ema < 0.9:
                self.mini_difficulty += 1
            elif self.difficulty_ema > 1.1:
                self.mini_difficulty = max(1, self.mini_difficulty - 1)

            print(
                colored(
                    f"Mini Difficulty adjusted to {self.mini_difficulty} "
                    f"(EMA: {self.difficulty_ema:.2f}, "
                    f"Actual: {actual_time:.1f}s, "
                    f"Expected: {expected_time:.1f}s)",
                    "blue",
                )
            )

        return self.mini_difficulty

    @property
    def latest_block(self):
        return self.mini_chain[-1]


class BlockChain:
    def __init__(self):
        self.chain = self.LoadDB()
        self.miniChain = MiniAvrChain(self)
        self.mempool = Mempool()
        self.current_transactions = []
        self.nodes = set()
        self.diff = 1000  # Initial difficulty
        self.block_time_target = 5 * 60  # 5 minutes in seconds
        self.adjustment_interval = 72  # Adjust every 72 blocks / six hours

        self.rewards = 80  # base rewards for every block

        # Block halving configuration
        # `initial_block_reward` keeps the immutable starting reward value
        # `halving_interval` is the number of blocks between each halving
        self.initial_block_reward = self.rewards
        self.halving_interval = 420000  # Roughly every four years a halving event
        self.min_block_reward = 0  # floor reward after many halvings

        self.construct_genesis()
        self.max_target = 2**256 -1
        self.diff = self.adjust_difficulty()
        self.miningTarget = self.calculate_target(self.diff)
        self.save_flag = True  # Flag to control saving
        self.memo_limit = 64  # Char limit for memos
        if not hasattr(self, "balances"):
            self.balances = {}

        self.totalsupply = (
            self.GetSupply()
        )  # Warning this variable only gives tsupply of init
        self.block_hash_map = {block.calculate_hash: block for block in self.chain}

        # Web3 compatibility
        self.CHAIN_ID = 676767
        self.SYMBOL = "AVRI"
        self.DECIMAL = 18

        self.AddressGen = AddressGen()

        # Avris Guard
        self.miner_stats = {}  # Track miner performance
        self.avriguard_threshold = 10  # Blocks per hour considered "high power"
        self.avriguard_window = 5 * 60  # 5 minute window for stats
        self.avriguard = False  # Enable Avris Guard
        self.nonces = {}

        # Tokens #TODO: Add later
        self.tokens = (
            {}
        )  # Format: {token_id: {"name": str, "symbol": str, "supply": int, "creator": str, "balances": {address: amount}}}

        # Transactions Fees
        self.transaction_fee_address = (
            self.GetConfig()
        )  # Address to receive transaction fees

        # P2P
        self.p2p = P2PNetwork(self)
        self.version = 0.10

    def resolve_conflicts(self):
        """
        This is our consensus algorithm, it resolves conflicts
        by replacing our chain with the longest one in the network.
        """
        neighbours = self.p2p.connected_peers
        new_chain = None

        # We're only looking for chains longer than ours
        max_length = len(self.chain)

        # Grab and verify the chains from all the nodes in our network
        for node in neighbours:
            try:
                response = requests.get(f"http://{node}/network/chain")
                if response.status_code == 200:
                    length = response.json()["length"]
                    chain = response.json()["chain"]

                    # Check if the length is longer and the chain is valid
                    if length > max_length and self.valid_chain(chain):
                        max_length = length
                        new_chain = chain
            except:
                continue

        # Replace our chain if we discovered a new, valid chain longer than ours
        if new_chain:
            self.chain = [Block.from_dict(block) for block in new_chain]
            self.SaveDB()
            self.miniChain.SaveDB()
            return True

        return False

    def valid_chain(self, chain):
        """
        Determine if a given blockchain is valid
        """
        if not isinstance(chain, list):
            return False

        # Convert dicts to Block objects
        try:
            chain = [Block.from_dict(block) for block in chain]
        except:
            return False

        # Check the genesis block matches
        if chain[0].calculate_hash != self.chain[0].calculate_hash:
            return False

        # Check each subsequent block
        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # Check that the hash of the block is correct
            if current.calculate_hash != current.calculate_hash:
                return False

            # Check that the Proof of Work is correct
            if not self.verifying_proof(previous.proofN, current.proofN):
                return False

        return True

    def broadcast_block(self, block):
        """Broadcast a new block to all peers"""
        block = Block.to_dict(block)
        if len(self.chain) > 1:  # Only Broadcast if it isnt genesis block
            for peer in self.p2p.connected_peers:
                try:
                    requests.post(f"http://{peer}/block/new", json=block, timeout=3)
                except Exception as e:
                    print(e)
        else:
            pass

    def broadcast_transaction(self, transaction):
        """Broadcast a new transaction to all peers"""
        for peer in self.p2p.connected_peers:
            try:
                requests.post(
                    f"http://{peer}/transaction/new", json=transaction, timeout=3
                )
            except:
                continue

    def update_miner_stats(self, miner_address):
        """Track how often a miner successfully mines blocks"""
        now = time.time()

        # Initialize miner stats if not exists
        if miner_address not in self.miner_stats:
            self.miner_stats[miner_address] = {
                "blocks": [],
                "multiplier": 1.0,  # Default no multiplier
            }

        # Add this block to miner's history
        self.miner_stats[miner_address]["blocks"].append(now)

        # Always clean up old blocks first (outside our 5-minute window)
        self.miner_stats[miner_address]["blocks"] = [
            t
            for t in self.miner_stats[miner_address]["blocks"]
            if now - t < self.avriguard_window
        ]

        # Add this block to miner's history if it's a new block
        if miner_address != "node":  # Don't track node's mining
            self.miner_stats[miner_address]["blocks"].append(now)

        # Calculate blocks in current window
        blocks_in_window = len(self.miner_stats[miner_address]["blocks"])

        # Reset multiplier if below threshold
        if blocks_in_window <= self.avriguard_threshold:
            self.miner_stats[miner_address]["multiplier"] = 1.0
        else:
            # Apply multiplier if miner is too fast
            excess = blocks_in_window - self.avriguard_threshold
            self.miner_stats[miner_address]["multiplier"] = 1.0 + (excess * 0.5)

    def get_miner_difficulty(self, miner_address):
        """Get adjusted difficulty for a miner"""
        if miner_address not in self.miner_stats:
            return self.diff  # Default difficulty

        # Always check current activity first
        now = time.time()
        recent_blocks = [
            t
            for t in self.miner_stats[miner_address]["blocks"]
            if now - t < self.avriguard_window
        ]

        # If no recent blocks, reset to normal
        if not recent_blocks:
            self.miner_stats[miner_address]["multiplier"] = 1.0
        if self.avriguard:
            return int(self.diff * self.miner_stats[miner_address]["multiplier"])
        else:
            return int(self.diff * 1.0)  # No multiplier if Avris Guard is off

    def calculate_target(self, difficulty):
        """Calculate target as max_target / difficulty"""
        if difficulty <= 0:
            difficulty = 1
        target = self.max_target // difficulty
        return target

    def adjust_difficulty(self):
        """Intelligent difficulty adjustment with proportional response to block time deviations"""
        
        current_height = len(self.chain)
        
        # Track recent block times for better analysis
        if current_height > 1:
            block_time = self.chain[-1].timestamp - self.chain[-2].timestamp
            if not hasattr(self, "recent_block_times"):
                self.recent_block_times = []
            self.recent_block_times.append(block_time)
            # Keep last 100 block times
            if len(self.recent_block_times) > 100:
                self.recent_block_times.pop(0)
        
        # Adjust at every block for maximum responsiveness
        if current_height > 1:
            last_block_time = self.chain[-1].timestamp - self.chain[-2].timestamp
            target_time = self.block_time_target  # 300 seconds
            
            # Calculate deviation percentage (how much faster/slower)
            deviation = (target_time - last_block_time) / target_time
            # Positive deviation = block was faster than target
            # Negative deviation = block was slower than target
            
            # PROPORTIONAL RESPONSE SYSTEM
            # The further from target, the larger the adjustment
            
            if abs(deviation) < 0.05:  # Within 5% (285-315 seconds)
                # Tiny adjustment for fine-tuning
                adjustment = 1 if deviation > 0 else -1
                
            elif abs(deviation) < 0.15:  # Within 15% (255-345 seconds)
                # Small proportional adjustment
                adjustment = int(self.diff * deviation * 0.1)
                if adjustment == 0:
                    adjustment = 1 if deviation > 0 else -1
                    
            elif abs(deviation) < 0.3:  # Within 30% (210-390 seconds)
                # Moderate proportional adjustment
                adjustment = int(self.diff * deviation * 0.3)
                
            elif abs(deviation) < 0.5:  # Within 50% (150-450 seconds)
                # Strong proportional adjustment
                adjustment = int(self.diff * deviation * 0.5)
                
            elif abs(deviation) < 1.0:  # Within 100% (0-600 seconds)
                # Very strong adjustment
                adjustment = int(self.diff * deviation * 0.8)
                
            else:  # Extreme deviation (>2x faster/slower)
                # Emergency adjustment - use exponential response
                if deviation > 0:  # Extremely fast
                    # If block was 2x faster, difficulty needs to 4x (2^2)
                    # If block was 3x faster, difficulty needs to 8x (2^3)
                    speed_factor = target_time / last_block_time
                    exponential_factor = 2 ** min(speed_factor, 5)  # Cap at 32x
                    adjustment = int(self.diff * (exponential_factor - 1))
                else:  # Extremely slow
                    # If block was 2x slower, difficulty needs to 1/4 (0.25x)
                    # If block was 3x slower, difficulty needs to 1/8 (0.125x)
                    slowness_factor = last_block_time / target_time
                    exponential_factor = 1 / (2 ** min(slowness_factor, 5))  # Cap at 1/32
                    adjustment = int(self.diff * (exponential_factor - 1))
            
            # Apply bounds to prevent wild swings
            max_adjustment = self.diff // 2  # Never adjust more than 50% at once
            adjustment = max(-max_adjustment, min(max_adjustment, adjustment))
            
            # Apply adjustment
            old_diff = self.diff
            self.diff = max(1, self.diff + adjustment)
            
            # Update mining target
            self.miningTarget = self.calculate_target(self.diff)
            
            # Only log significant adjustments
            if abs(adjustment) > 0:
                print(colored(
                    f"📈 Block {current_height-1}: {last_block_time:.1f}s "
                    f"(deviation: {deviation*100:+.1f}%) → "
                    f"Difficulty {old_diff} → {self.diff} (Δ: {adjustment:+d})",
                    "green" if last_block_time <= target_time else "yellow"
                ))
        
        # ADDITIONAL: Major recalibration (every 100 blocks)
        if current_height % 100 == 0 and current_height > 100:
            self._perform_major_recalibration()
        
        return self.diff


    def _perform_major_recalibration(self):
        """Major recalibration every 100 blocks to reset any accumulated error"""
        if len(self.chain) < 101:
            return
        
        # Calculate ideal difficulty based on last 100 blocks
        start_time = self.chain[-100].timestamp
        end_time = self.chain[-1].timestamp
        total_time = end_time - start_time
        avg_block_time = total_time / 100
        
        target = self.block_time_target
        perfect_ratio = target / avg_block_time
        
        # Calculate what the difficulty SHOULD have been
        # Based on: expected_hashes = difficulty
        # So if blocks were X times faster/slower, difficulty should be X times different
        old_diff = self.diff
        self.diff = int(self.diff * perfect_ratio)
        
        # Safety bounds
        self.diff = max(1, min(self.diff, old_diff * 10))  # Never more than 10x change
        
        print(colored(
            f"🎯 MAJOR RECALIBRATION: Last 100 blocks average {avg_block_time:.1f}s "
            f"(perfect ratio: {perfect_ratio:.3f}) → Difficulty {old_diff} → {self.diff}",
            "blue", attrs=["bold"]
        ))
        
        # Update mining target
        self.miningTarget = self.calculate_target(self.diff)
        
        # Clear recent tracking for fresh start
        if hasattr(self, "recent_block_times"):
            self.recent_block_times.clear()

    def GetSupply(self):
        return sum(list(self.balances.values()))

    def SaveDB(self):
        """Only save when chain has changed"""
        if not self.save_flag:
            return

        # Use atomic write to prevent corruption
        temp_path = "src/data/blockchain.json.tmp"
        with open(temp_path, "w") as f:
            jsonify.dump([block.to_dict() for block in self.chain], f)

        # Atomic rename (works on Unix/Windows)
        os.replace(temp_path, "src/data/blockchain.json")
        # print(colored("Blockchain Database SAVED!", "green"))

    def LoadDB(self):
        self.save_flag = False
        if os.path.exists("src/data/blockchain.json"):
            print(colored("Blockchain Database FOUND!", "green"))
            db = jsonify.load(open("src/data/blockchain.json", "r"))
            chain = [Block.from_dict(block_dict) for block_dict in db]
            # print(chain)
            self.balances = self.replay_transactions(chain)
            return chain
        else:
            print(colored("Couldnt Find A DB in src/data/ :("))
            return []

    def replay_transactions(self, chain):
        balances = {}
        for block in chain:
            for transaction in block.transactions:
                sender = transaction["sender"]
                recipient = transaction["recipient"]
                amount = transaction["quantity"]

                balances[sender] = balances.get(sender, 0) - amount
                balances[recipient] = balances.get(recipient, 0) + amount

        balances["node"] = 0  # Null the node
        print(colored("PLAYED ALL TX's Successfully", "green"))
        return balances

    def construct_genesis(self):
        if not self.chain:
            print(colored("CREATING THE GENESIS", "green"))
            self.construct_block(proofN=0, prev_hash=0, miner="None")

    def construct_block(self, proofN, prev_hash, miner):
        transactions = self.mempool.get_block_candidates()
        total_fees = sum(tx["fee"] for tx in transactions if "fee" in tx)
        mini_root = self.miniChain.create_merkle_root()

        # Update balances for transaction fees
        if total_fees > 0:
            fee_tx = {
                "sender": "node",
                "recipient": miner,
                "quantity": total_fees,
                "fee": 0,
                "txid": self.calculate_txid(time.time()),
                "timestamp": time.time(),
                "memo": "Total Transaction Fees Payment",
            }
            # fee_tx["txid"] = blake3(
            #     jsonify.dumps(fee_tx.items).encode()
            # ).hexdigest()
            # print(fee_tx)
            transactions.append(fee_tx)
            self.balances[miner] = self.balances.get(miner, 0) + total_fees

        block = Block(
            index=len(self.chain),
            proofN=proofN,
            prev_hash=prev_hash,
            transactions=transactions,
            mini_avr_root=mini_root,
        )
        self.current_transactions = []
        self.chain.append(block)
        try:
            self.block_hash_map[block.calculate_hash] = block  # Add to hash map
        except AttributeError:
            pass

        if self.save_flag:
            self.SaveDB()
            self.miniChain.SaveDB()

        self.adjust_difficulty()  # Adjust difficulty after adding a new block
        self.mempool.remove_confirmed(
            block.transactions
        )  # Remove confirmed transactions
        self.broadcast_block(block)  # Broadcast

        return block

    # @staticmethod
    # def check_validity(block, prev_block):

    #     if prev_block.index + 1 != block.index:
    #         return False

    #     elif prev_block.calculate_hash != block.prev_hash:
    #         return False

    #     elif not BlockChain.verifying_proof(block.proofN,
    #                                         prev_block.proofN):
    #         return False

    #     elif block.timestamp <= prev_block.timestamp:
    #         return False

    #     return True

    # TODO: make funcs that use this actually output the rawtxid
    
    def get_nonce(self, address):
        """Get next transaction nonce for an address"""
        if address not in self.nonces:
            self.nonces[address] = 0
        nonce = self.nonces[address]
        self.nonces[address] += 1
        return nonce   
    
    def wei_to_avri(self, wei_amount):
        """Convert from wei (18 decimals) to AVR"""
        try:
            # Convert from wei (integer) to AVR (float)
            return float(wei_amount) / (10 ** self.DECIMAL)
        except:
            return 0.0
    
    # NEW: Convert from AVR to wei
    def avri_to_wei(self, avri_amount):
        """Convert from AVR to wei (18 decimals)"""
        try:
            # Convert from AVR to wei (integer)
            return int(float(avri_amount) * (10 ** self.DECIMAL))
        except:
            return 0

    def calculate_txid(self, rawtx, web3=None):
        if web3:

            # Remove '0x' prefix if present
            if web3.startswith('0x'):
                web3 = web3[2:]

            k = keccak.new(digest_bits=256)
            k.update(bytes.fromhex(web3))
            return k.hexdigest()
        
        tx_string = "{}{}".format(rawtx, random.randint(0, 100000))
        return blake3(tx_string.encode()).hexdigest()

    def new_transaction(self, rawtx, type, memo=None, web3 = None):
        """Add a signed transaction"""
        decoder = EthTxDecoder()
        tx = decoder.decode_raw_tx(rawtx)
        # 1. Validate addresses
        if (
            not self.AddressGen.Validate(tx["from_"])["status"]
            or not self.AddressGen.Validate(tx["to"])["status"]
        ):
            return {"status": False, "txid": None, "error": "Invalid address(es)"}

        # Verify seed matches sender_address
        # if not self.AddressGen.VerifyTransaction(sender, rawtx)["status"]:
        #     return {
        #         "status": False,
        #         "txid": None,
        #         "error": "Seed does not match sender address",
        #     }

        if not self.AddressGen.VerifyTransaction(tx["from_"], rawtx)["status"]:
            return {
                "status": False,
                "txid": None,
                "error": "Tx does not match address",
            }
        if type == 0:
            status = self.new_data(
                sender=tx["from_"], recipient=tx["to"], quantity=tx["value"], memo=memo
            )
        elif type == 1:
            nNonce = self.get_nonce(tx["from_"])
            status = self.new_data(
                sender=tx["from_"], recipient=tx["to"], quantity=self.wei_to_avri(tx["value"]), memo=memo, web3=web3
            )
        return status

    def new_data(
        self, sender, recipient, quantity, memo, web3= None
    ):  # Used for appending/updating transactions to blc
        current_fee_percent = self.mempool.get_current_fee_percent()
        fee = quantity * current_fee_percent
        totaltxspend = quantity + fee

        pending_spends = sum(
            tx["quantity"] * (1 + self.mempool.get_current_fee_percent())
            for tx in self.mempool.transactions
            if tx["sender"] == sender
        )
        available_balance = self.get_balance(sender) - pending_spends

        if sender != "node" and available_balance < quantity:
            print(
                colored(
                    f"Transaction from {sender} to {recipient} for {quantity} $AVRI rejected due to insufficient funds.",
                    "red",
                )
            )
            return {"status": False, "txid": None, "error": "Insufficient funds"}

        # Update balances
        if sender != "node":
            self.balances[sender] = self.balances.get(sender, 0) - totaltxspend
            self.balances[recipient] = self.balances.get(recipient, 0) + quantity

        # Create Transaction ID
        if web3:
            txid = self.calculate_txid(time.time(), web3)
            
        txid = self.calculate_txid(time.time())
        if sender == "node":
            fee = 0

        if memo != None:
            tx = {
                "sender": sender,
                "recipient": recipient,
                "quantity": quantity,
                "fee": fee,  # Add fee to transaction
                "fee_percent": current_fee_percent,
                "txid": txid,
                "timestamp": time.time(),
                "memo": memo[: self.memo_limit],  # First 64 Charecters
            }
        else:
            tx = {
                "sender": sender,
                "recipient": recipient,
                "quantity": quantity,
                "fee": fee,  # Add fee to transaction
                "fee_percent": current_fee_percent,
                "txid": txid,
                "timestamp": time.time(),
                "memo": "None",
            }

        try:
            self.mempool.add_transaction(tx)
            #print(colored(f"Transaction from {sender} to {recipient} for {quantity} added to mempool.", "green")) #Debug
            self.broadcast_transaction(tx)
            return {"status": True, "txid": txid, "fee": fee}

        except MempoolFullError:
            return {
                "status": False,
                "txid": None,
                "error": "Mempool is full. Try again later",
            }


    def verifying_proof(self, last_proof, proof, difficulty=None):
        """Modified to accept optional custom difficulty"""
        difficulty = difficulty or self.diff
        target = self.calculate_target(difficulty)
        
        guess = blake3(f"{last_proof}{proof}".encode()).hexdigest().encode()
        guess = skein.skein1024(guess).hexdigest()
        guess_hash = getHash(guess.encode(), len(guess)).hex()
        
        hash_int = int(guess_hash, 16)
        return hash_int <= target

    @property
    def latest_block(self):
        return self.chain[-1]

    # def block_mining(self, details_miner):
    #     self.new_data(
    #         sender="node",  #it implies that this node has created a new block
    #         recipient=details_miner,
    #         quantity=
    #         self.rewards,  #creating a new block (or identifying the proof number) is awarded with 1
    #         memo="BLock has been mined (Yay!)"
    #     )

    #     last_block = self.latest_block

    #     last_proofN = last_block.proofN
    #     proofN = self.proof_of_work(last_proofN) # Soon it will be given by some random miner

    #     last_hash = last_block.calculate_hash
    #     block = self.construct_block(proofN, last_hash)
    #     self.balances[details_miner] = self.balances.get(details_miner, 0) + self.rewards

    #     return block

    def submit_mined_block(self, details_miner, proofN, last_hash):
        # Get the last block first
        last_block = self.latest_block

        # Update miner stats and get their current difficulty
        self.update_miner_stats(details_miner)
        current_diff = self.get_miner_difficulty(details_miner)

        # Verify with adjusted difficulty
        if not self.verifying_proof(last_block.proofN, proofN, current_diff):
            return (
                {
                    "status": "error",
                    "message": f"Proof doesn't meet required difficulty (needed: {current_diff})",
                    "required_difficulty": current_diff,
                    "your_difficulty_multiplier": self.miner_stats.get(
                        details_miner, {}
                    ).get("multiplier", 1.0),
                },
                400,
            )

        # Continue with block creation if proof is valid

        # Determine reward for this block (apply halving schedule)
        height = len(self.chain)  # current height (new block will have this index)
        reward = self.get_block_reward(height)

        self.new_data(
            sender="node",
            recipient=details_miner,
            quantity=reward,
            memo="BLock has been mined (Yay!)",
        )
        block = self.construct_block(proofN, last_hash, details_miner)
        self.balances[details_miner] = self.balances.get(details_miner, 0) + reward

        print(
            colored(
                f"\n-----------\nNew Block mined!\nHeight: {len(self.chain)}\nMiner: {details_miner}\nReward: {reward} AVRI\nTX confirmed: {len(block.transactions)} \n-----------\n",
                "green",
            )
        )
        return block

    def create_node(self, address):
        self.nodes.add(address)
        return True

    def get_balance(self, user):
        if user != "node":
            return self.balances.get(Web3.to_checksum_address(user), 0)
        else:
            return self.balances.get(user, 0)

    def diff_at_height(self, height):
        """Get difficulty at specific block height"""
        if height < len(self.chain):
            return (
                self.chain[height].difficulty
                if hasattr(self.chain[height], "difficulty")
                else self.diff
            )
        return self.diff

    def get_block_reward(self, height=None):
        """Compute block reward for given height applying halving schedule.

        If `height` is None, use current chain length (next block index).
        """
        if height is None:
            height = len(self.chain)

        # Number of completed halving periods
        halvings = height // self.halving_interval

        # Apply halving by powers of two
        reward = self.initial_block_reward // (2**halvings)

        # Enforce minimum reward floor
        if reward < self.min_block_reward:
            return self.min_block_reward
        return reward

    def block_by_hash(self, block_hash):
        for block in self.chain:
            if block.calculate_hash == block_hash:
                return block

        return None
        # block = self.block_hash_map.get(block_hash, None)
        # if block:
        #     block.index = block.index
        #     if block.index+1 < len(self.chain):
        #         return self.chain[block.index+1]

        # return None

    def format_hashrate(self, hashes_per_sec):
        # Format the hash rate into human-readable format
        units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s"]
        unit_index = 0
        while hashes_per_sec >= 1000 and unit_index < len(units) - 1:
            hashes_per_sec /= 1000
            unit_index += 1
        return f"{hashes_per_sec:.2f} {units[unit_index]}"

    @staticmethod
    def obtain_block_object(block_data):
        # obtains block object from the block data

        return Block(
            block_data["index"],
            block_data["proofN"],
            block_data["prev_hash"],
            block_data["transactions"],
            timestamp=block_data["timestamp"],
        )

    def GetConfig(self):
        if os.path.exists("src/data/config.json"):
            data = jsonify.load(open("src/data/config.json", "r"))
            return [data["address"], data["seed"]]
        else:
            greeter("src/data/config.json", AddressGen)
    
    # NEW: Find miner of a block
    def find_miner(self, block_hash_or_height):
        """
        Find the miner who mined a specific block
        
        Args:
            block_hash_or_height: Block hash (string) or height (int)
        
        Returns:
            Dictionary with miner info or None if not found
        """
        # Find the block
        block = None
        
        if isinstance(block_hash_or_height, int):
            # Search by height
            if 0 <= block_hash_or_height < len(self.chain):
                block = self.chain[block_hash_or_height]
        elif isinstance(block_hash_or_height, str):
            # Search by hash
            for b in self.chain:
                if b.calculate_hash == block_hash_or_height:
                    block = b
                    break
        else:
            return None
        
        if not block:
            return None
        
        # Look for the coinbase transaction (block reward)
        miner_address = None
        block_reward = 0
        
        for tx in block.transactions:
            # Coinbase transaction: sender is "node" and it's a reward
            if tx.get('sender') == "node" and tx.get('quantity', 0) > 0:
                miner_address = tx.get('recipient')
                block_reward = tx.get('quantity', 0)
                break
        
        # If no coinbase found, check for fee payments
        if not miner_address:
            for tx in block.transactions:
                if tx.get('memo', '').lower() in ['block reward', 'mining reward', 'fee payment']:
                    miner_address = tx.get('recipient')
                    break
        
        # Get miner stats if available
        miner_stats = None
        if miner_address and miner_address in self.miner_stats:
            miner_stats = self.miner_stats[miner_address]
        
        return {
            "block_height": block.index,
            "block_hash": block.calculate_hash,
            "miner_address": miner_address or "unknown",
            "block_reward": block_reward,
            "timestamp": block.timestamp,
            "transaction_count": len(block.transactions),
            "difficulty": self.diff_at_height(block.index),
        }
    
    # NEW: Find all blocks mined by an address
    def find_blocks_by_miner(self, miner_address, limit=100):
        """
        Find all blocks mined by a specific address
        
        Args:
            miner_address: Address to search for
            limit: Maximum number of blocks to return
        
        Returns:
            List of blocks mined by this address
        """
        mined_blocks = []
        
        for block in self.chain:
            for tx in block.transactions:
                if tx.get('sender') == "node" and tx.get('recipient') == miner_address:
                    mined_blocks.append({
                        "block_height": block.index,
                        "block_hash": block.calculate_hash,
                        "reward": tx.get('quantity', 0),
                        "timestamp": block.timestamp,
                        "transactions": len(block.transactions),
                        "difficulty": self.diff_at_height(block.index)
                    })
                    break
            
            if len(mined_blocks) >= limit:
                break
        
        # Add statistics
        if mined_blocks:
            total_rewards = sum(b["reward"] for b in mined_blocks)
            first_block = mined_blocks[-1]["block_height"] if mined_blocks else None
            last_block = mined_blocks[0]["block_height"] if mined_blocks else None
            
            return {
                "miner_address": miner_address,
                "total_blocks": len(mined_blocks),
                "total_rewards": total_rewards,
                "first_block": first_block,
                "last_block": last_block,
                "blocks": mined_blocks
            }
        
        return None
    
    # NEW: Get top miners
    def get_top_miners(self, limit=10):
        """
        Get the top miners by blocks mined
        
        Args:
            limit: Number of top miners to return
        
        Returns:
            List of top miners with stats
        """
        miner_stats = {}
        
        # Count blocks mined by each address
        for block in self.chain:
            for tx in block.transactions:
                if tx.get('sender') == "node" and tx.get('quantity', 0) > 0:
                    miner = tx.get('recipient')
                    if miner:
                        if miner not in miner_stats:
                            miner_stats[miner] = {
                                "blocks_mined": 0,
                                "total_rewards": 0,
                                "first_block": block.index,
                                "last_block": block.index
                            }
                        
                        miner_stats[miner]["blocks_mined"] += 1
                        miner_stats[miner]["total_rewards"] += tx.get('quantity', 0)
                        miner_stats[miner]["last_block"] = block.index
                        break
        
        # Convert to list and sort
        top_miners = []
        for miner, stats in miner_stats.items():
            top_miners.append({
                "miner_address": miner,
                **stats
            })
        
        # Sort by blocks mined (descending)
        top_miners.sort(key=lambda x: x["blocks_mined"], reverse=True)
        
        return {
            "top_miners": top_miners[:limit],
            "total_unique_miners": len(miner_stats),
            "total_blocks_mined": len(self.chain) - 1  # Exclude genesis
        }


app = Sanic(__name__)
app.config.KEEP_ALIVE_TIMEOUT = 3600
blockchain = BlockChain()
blockchain.save_flag = True


@app.middleware("response")
async def add_cors_headers(request, response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


####################### NODE ################################
@app.get("/ping")
@openapi.description("Ping the server")
async def pong(request):
    return json(
        {
            "result": "pong!",
        },
        200,
    )


####################### NETWORK #############################
@app.get("/network/info")
@openapi.description("Get network information")
async def get_network_info(request):
    return json(
        {
            "height": len(blockchain.chain) - 1,
            "total_supply": blockchain.GetSupply(),
            "difficulty": blockchain.diff,
            "mini_difficulty": blockchain.miniChain.mini_difficulty,
            "block_reward": blockchain.get_block_reward(height=(len(blockchain.chain))),
            "node_count": len(blockchain.nodes),
            "threshold": blockchain.avriguard_threshold,
            "window": blockchain.avriguard_window,
            "avriguard": blockchain.avriguard,
            "node": {
                "owner": blockchain.transaction_fee_address,
                "version": blockchain.version,
            },
        }
    )


@app.get("/network/chain")
async def get_chain(request):
    chain_data = []
    for block in blockchain.chain:
        chain_data.append(block.__dict__)
    return json(
        {"length": len(chain_data), "chain": chain_data},
    )


@app.get("/network/minichain")
async def get_minichain(request):
    chain_data = []
    for block in blockchain.miniChain.mini_chain:
        chain_data.append(block.__dict__)
    return json(
        {"length": len(chain_data), "chain": chain_data},
    )


@app.get("/network/latestblock")
@openapi.description("Get the latest block")
async def get_block(request):
    return json(vars(blockchain.latest_block))


@app.get("/network/totalsupply")
@openapi.description("Get the total supply of the blockchain")
async def get_totalsupply(request):
    return json({"TotalSupply": blockchain.GetSupply()})


@app.get("/network/getblockbyhash/<hash>")
@openapi.description("Get block by hash")
def get_block_by_hash(request, hash):
    block = blockchain.block_by_hash(hash)
    print(block)
    if not (block):
        return json({"ERROR": f"{hash} not found"})
    else:
        return json(vars(block))


@app.get("/network/transactionbyid/<txid>")
@openapi.description("Get transaction by ID")
def get_transaction(request, txid):
    for block in blockchain.chain:
        for tx in block.transactions:
            if tx["txid"] == txid:
                return json({"block_height": block.index, "transaction": tx})
    for tx in blockchain.mempool.transactions:
        if tx["txid"] == txid:
            return json(
                {
                    "block_height": None,
                    "status": "unconfirmed in mempool",
                    "transaction": tx,
                }
            )
    return json({"ERROR": f"{txid} not found"}, 404)


@app.get("/network/transactions/<address>")
@openapi.description("Get all transactions for an address")
async def address_transactions(request, address):
    txs = []
    for block in blockchain.chain:
        for tx in block.transactions:
            if tx["sender"] == address or tx["recipient"] == address:
                tx_data = dict(tx)
                tx_data["block_height"] = block.index
                tx_data["timestamp"] = block.timestamp
                txs.append(tx_data)

    return json({"transactions": txs})


@app.get("/network/block/<blocknum>")
@openapi.description("Get block by number")
def get_block_by_num(request, blocknum: int):
    blockc = blockchain.chain
    if len(blockc) < blocknum:
        return json({"ERROR": "Block Doesnt Exist yet"}, 400)

    return json(vars(blockc[blocknum]))


@app.get("/network/blocks")
@openapi.description("Get blocks using ?count=<number>")
async def get_recent_blocks(request):
    count = int(request.args.get("count", 5))
    count = min(count, len(blockchain.chain))
    blocks = []

    for block in blockchain.chain[-count:]:
        blocks.append(
            {
                "index": block.index,
                "hash": block.calculate_hash,
                "timestamp": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(block.timestamp)
                ),
                "transactions": block.transactions,
                "proofN": block.proofN,
                "prev_hash": block.prev_hash,
            }
        )

    return json({"blocks": blocks[::-1]})  # Return newest first


@app.get("/network/transactions")
@openapi.description("Get transactions using ?count=<number>")
async def get_recent_transactions(request):
    count = int(request.args.get("count", 5))
    all_txs = []

    for block in reversed(blockchain.chain):
        for tx in reversed(block.transactions):
            tx_data = dict(tx)
            tx_data["block_height"] = block.index
            tx_data["timestamp"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(block.timestamp)
            )
            all_txs.append(tx_data)
            if len(all_txs) >= count:
                break
        if len(all_txs) >= count:
            break

    return json({"transactions": all_txs})


@app.get("/network/hashrate")
async def get_network_hashrate(request):
    # Get current difficulty
    current_diff = blockchain.diff

    # Calculate average block time (last N blocks, configurable)
    try:
        block_count = int(request.args.get("blocks", 60))
        block_count = min(max(block_count, 2), 1000)  # Between 2 and 1000 blocks
    except:
        block_count = min(60, len(blockchain.chain))
    
    if len(blockchain.chain) < 2:
        return json({"error": "Need at least 2 blocks in chain"}, status=400)
    
    if block_count < 2:
        return json({"error": "Need to analyze at least 2 blocks"}, status=400)
    
    if block_count > len(blockchain.chain):
        block_count = len(blockchain.chain)
    
    # Calculate time span
    oldest_block = blockchain.chain[-block_count]
    newest_block = blockchain.chain[-1]
    time_span = newest_block.timestamp - oldest_block.timestamp
    
    if time_span <= 0:
        return json({"error": "Invalid time span (zero or negative)"}, status=400)
    
    avg_block_time = time_span / (block_count - 1)
    
    # Calculate hashrate using multiple methods for accuracy
    hashrate_results = {}
    
    try:
        # Method 1: Probability-based (most accurate)
        target = blockchain.calculate_target(current_diff)
        if target > 0:
            expected_hashes_per_block = blockchain.max_target / target
            hashrate_prob = expected_hashes_per_block / avg_block_time
            hashrate_results["probability_method"] = hashrate_prob
        else:
            hashrate_results["probability_method"] = None
    except (OverflowError, ZeroDivisionError):
        hashrate_results["probability_method"] = None
    
    try:
        # Method 2: Difficulty-based approximation (good for large numbers)
        # For target-based PoW where target = max_target / difficulty:
        # expected_hashes ≈ difficulty
        hashrate_diff = float(current_diff) / avg_block_time
        hashrate_results["difficulty_method"] = hashrate_diff
    except (OverflowError, ZeroDivisionError):
        hashrate_results["difficulty_method"] = None
    
    try:
        # Method 3: Exponential approximation (handles very large difficulties)
        # log2(expected_hashes) = log2(difficulty)
        # So expected_hashes = 2^(log2(difficulty)) = difficulty
        # But we compute in log space to avoid overflow
        import math
        if current_diff > 0 and avg_block_time > 0:
            # Compute log10 of expected hashes
            log10_expected = math.log10(current_diff)
            # Compute log10 of hashrate
            log10_hashrate = log10_expected - math.log10(avg_block_time)
            # Convert back from log space
            hashrate_log = 10 ** log10_hashrate
            hashrate_results["logarithmic_method"] = hashrate_log
        else:
            hashrate_results["logarithmic_method"] = None
    except (OverflowError, ValueError, ZeroDivisionError):
        hashrate_results["logarithmic_method"] = None
    
    # Choose the best available hashrate
    hashrate = None
    method_used = "unknown"
    
    # Priority: probability > difficulty > logarithmic
    for method in ["probability_method", "difficulty_method", "logarithmic_method"]:
        if hashrate_results.get(method) is not None and not math.isinf(hashrate_results[method]):
            hashrate = hashrate_results[method]
            method_used = method.replace("_method", "")
            break
    
    if hashrate is None or hashrate <= 0:
        return json({"error": "Could not calculate hashrate", "details": hashrate_results}, status=400)
    
    # Calculate additional statistics
    stats = {
        "hashrate": hashrate,
        "hashrate_human": blockchain.format_hashrate(hashrate),
        "difficulty": current_diff,
        "avg_block_time": avg_block_time,
        "blocks_analyzed": block_count,
        "time_span_seconds": time_span,
        "method_used": method_used,
        "target": hex(blockchain.miningTarget)[:50] + "..." if len(hex(blockchain.miningTarget)) > 50 else hex(blockchain.miningTarget),
        "max_target": hex(blockchain.max_target)[:50] + "..." if len(hex(blockchain.max_target)) > 50 else hex(blockchain.max_target),
    }
    
    # Add method comparisons if available
    if len(hashrate_results) > 1:
        stats["method_comparisons"] = {}
        for method, value in hashrate_results.items():
            if value is not None:
                stats["method_comparisons"][method] = blockchain.format_hashrate(value)
    
    # Add block time statistics
    if block_count > 5:
        recent_times = []
        for i in range(1, min(block_count, 20)):
            if len(blockchain.chain) > i:
                block_time = blockchain.chain[-i].timestamp - blockchain.chain[-i-1].timestamp
                recent_times.append(block_time)
        
        if recent_times:
            stats["recent_block_times"] = {
                "min": min(recent_times),
                "max": max(recent_times),
                "median": sorted(recent_times)[len(recent_times)//2],
                "std_dev": math.sqrt(sum((t - avg_block_time) ** 2 for t in recent_times) / len(recent_times)) if len(recent_times) > 1 else 0
            }
    
    return json(stats)
    
@app.get("/network/mini/hashrate")
async def get_network_mini_hashrate(request):
    # Get current difficulty
    current_diff = blockchain.miniChain.mini_difficulty

    # Calculate average block time (last 60 blocks)
    block_count = min(60, len(blockchain.miniChain.mini_chain))
    if block_count < 2:
        return json({"error": "Need at least 2 blocks"}, status=400)

    oldest_block = blockchain.miniChain.mini_chain[-block_count]
    newest_block = blockchain.miniChain.mini_chain[-1]
    time_span = newest_block.timestamp - oldest_block.timestamp
    avg_block_time = time_span / (block_count - 1)

    # Calculate hashrate (fixed formula)
    # For leading zero difficulty: hashrate = (2^difficulty_bits) / avg_block_time
    # For blake2b (256-bit): hashrate = (2^256) / (2^(256-difficulty)) / block_time
    # Simplified to:
    hashrate = (2**current_diff) / avg_block_time

    return json(
        {
            "hashrate": hashrate,
            "hashrate_human": blockchain.format_hashrate(hashrate),
            "difficulty": current_diff,
            "avg_block_time": avg_block_time,
            "blocks_analyzed": block_count,
        }
    )


# @app.get("/network/fee_info")
# @openapi.description("Get information about transaction fees")
# async def get_fee_info(request):
#     return json({
#         "fee_percentage": blockchain.mempool.get_current_fee_percent(),
#         "description": f"Fixed {round(blockchain.mempool.get_current_fee_percent()*100, 2)}% fee on all transactions",
#         "distribution": "Avris Development Fund",
#     })


@app.get("/network/fee_estimate")
@openapi.description("Get current fee estimate")
async def get_fee_estimate(request):
    current_fee = blockchain.mempool.get_current_fee_percent()
    mempool_status = {
        "fee": current_fee,
        "current_fee_percent": current_fee * 100,
        "mempool_utilization": f"{(len(blockchain.mempool.transactions)/blockchain.mempool.max_size)*100:.1f}%",
        "next_block_capacity": blockchain.mempool.block_tx_limit,
        "pending_transactions": len(blockchain.mempool.transactions),
        "total_fees": sum(
            tx["fee"] for tx in blockchain.mempool.transactions if "fee" in tx
        ),  # Total fees in mempool
    }
    return json(mempool_status)


@app.get("/network/fee_chart")
@openapi.description("Visualize fee structure")
async def fee_chart(request):
    steps = 10
    data = []
    for i in range(steps + 1):
        utilization = i / steps
        temp_mempool = Mempool()  # Create temp instance for calculation
        temp_mempool.transactions = [None] * int(utilization * temp_mempool.max_size)
        fee = temp_mempool.get_current_fee_percent() * 100
        data.append(
            {"mempool_utilization": f"{utilization*100:.0f}%", "fee_percent": fee}
        )
    return json({"fee_structure": data})


@app.get("/network/checkaddrdiff/<address>")
@openapi.description("Check if an address is mining under normal or high difficulty")
async def check_address_difficulty(request, address):
    if not blockchain.AddressGen.Validate(address)["status"]:
        return json(
            {"status": "error", "message": "Invalid address format"}, status=400
        )

    # Check if address has mining stats
    if address in blockchain.miner_stats and blockchain.avriguard:
        stats = blockchain.miner_stats[address]
        current_bph = len(stats["blocks"])
        if stats["multiplier"] > 1.0:
            status = "high"
            message = f"Address has high difficulty (mining {current_bph} blocks/hour)"
        else:
            status = "normal"
            message = (
                f"Address has normal difficulty (mining {current_bph} blocks/hour)"
            )

        return json(
            {
                "status": status,
                "message": message,
                "difficulty_multiplier": stats["multiplier"],
                "current_blocks_per_hour": current_bph,
                "threshold": blockchain.avriguard_threshold,
                "base_difficulty": blockchain.diff,
                "effective_difficulty": blockchain.get_miner_difficulty(address),
            }
        )

    elif address not in blockchain.miner_stats and blockchain.avriguard:
        return json(
            {
                "status": "normal",
                "message": "Address has normal difficulty (no mining activity detected)",
                "difficulty_multiplier": 1.0,
                "current_blocks_per_hour": 0,
                "threshold": blockchain.avriguard_threshold,
            }
        )

    elif address in blockchain.miner_stats and blockchain.avriguard == False:
        stats = blockchain.miner_stats[address]
        current_bph = len(stats["blocks"])
        return json(
            {
                "status": "normal",
                "message": "Avris Guard is disabled. No difficulty checks.",
                "difficulty_multiplier": 0,
                "current_blocks_per_hour": current_bph,
                "threshold": blockchain.avriguard_threshold,
                "base_difficulty": blockchain.diff,
                "effective_difficulty": blockchain.get_miner_difficulty(address),
            }
        )

    elif address not in blockchain.miner_stats and blockchain.avriguard == False:
        return json(
            {
                "status": "normal",
                "message": "Avris Guard is disabled. No mining activity detected.",
                "difficulty_multiplier": 0,
                "current_blocks_per_hour": 0,
                "threshold": blockchain.avriguard_threshold,
                "base_difficulty": blockchain.diff,
                "effective_difficulty": blockchain.get_miner_difficulty(address),
            }
        )


####################### Mining ###################################


@app.get("/mining/info")
@openapi.description("Get mining information")
async def get_mining_info(request):
    return json(
        {
            "difficulty": blockchain.diff,
            "target": hex(blockchain.miningTarget),
            "max_target": hex(blockchain.max_target),
            "latestblock": vars(blockchain.latest_block)
        }
    )


@app.get("/mining/<block_identifier>/miner")
@openapi.description("Find miner of a specific block")
async def get_block_miner(request, block_identifier: str):
    # Try as number first
    try:
        block_height = int(block_identifier)
        miner_info = blockchain.find_miner(block_height)
    except ValueError:
        # Try as hash
        miner_info = blockchain.find_miner(block_identifier)
    
    if not miner_info:
        return json({"error": "Block not found"}, status=404)
    
    return json(miner_info)

@app.get("/mining/<address>/blocks")
@openapi.description("Find all blocks mined by an address")
async def get_miner_blocks(request, address):
    limit = int(request.args.get("limit", 100))
    limit = min(limit, 1000)  # Cap at 1000
    
    blocks_info = blockchain.find_blocks_by_miner(address, limit)
    
    if not blocks_info:
        return json({
            "miner_address": address,
            "total_blocks": 0,
            "message": "No blocks found for this miner"
        })
    
    return json(blocks_info)

@app.post("/mining/submitblock")
@openapi.description("Submit a mined block")
async def submit_block(request):
    block_data = request.json
    index = block_data["index"]
    proofN = block_data["proofN"]
    prev_hash = block_data["prev_hash"]
    # transactions = block_data['transactions']
    miner_address = block_data["miner_address"]
    timestamp = block_data["timestamp"]

    last_block = blockchain.latest_block

    if last_block.index + 1 != index:
        return json({"message": "Invalid Index"}, 400)

    if last_block.calculate_hash != prev_hash:
        return json({"message": "Invalid previous hash"}, 400)

    if not blockchain.verifying_proof(last_block.proofN, proofN):
        return json({"message": "Invalid proof"}, 400)

    if timestamp <= last_block.timestamp:
        return json({"message": "Invalid timestamp"}, 400)

    block = blockchain.submit_mined_block(miner_address, proofN, prev_hash)
    try:
        return json(vars(block), 201)
    except Exception as e:
        # If block is a tuple (error response), return the error message
        if (
            isinstance(block, tuple)
            and isinstance(block[0], dict)
            and block[0].get("status") == "error"
        ):
            return json(block[0])
        else:
            return json({"message": "Unknown error occurred"}, 500)


@app.get("/mini/mining/info")
async def get_mini_job(request):
    job = blockchain.miniChain.get_mini_mining_job()
    return json(
        {
            "difficulty": job["difficulty"],
            "latestblock": vars(blockchain.miniChain.latest_block),
        }
    )


@app.post("/mini/mining/submitblock")
async def submit_mini_block(request):
    block_data = request.json
    index = block_data["index"]
    proofN = block_data["proofN"]
    prev_hash = block_data["prev_hash"]
    # transactions = block_data['transactions']
    miner_address = block_data["miner_address"]
    timestamp = block_data["timestamp"]

    last_block = blockchain.miniChain.latest_block

    if last_block.index + 1 != index:
        return json({"message": "Invalid Index"}, 400)

    if last_block.calculate_hash != prev_hash:
        return json({"message": "Invalid previous hash"}, 400)

    if not blockchain.miniChain.verifying_proof(last_block.proofN, proofN):
        print(last_block.proofN)
        return json({"message": "Invalid proof"}, 400)

    if timestamp <= last_block.timestamp:
        return json({"message": "Invalid timestamp"}, 400)

    block = blockchain.miniChain.submit_mini_solution(
        mini_proofN=proofN, prev_hash=prev_hash, miner_address=miner_address
    )
    try:
        return json(vars(block), 201)
    except Exception as e:
        return json({"message": "Unknown error occurred"}, 500)


@app.get("/network/block/<block_identifier>/transactions")
@openapi.description("Get all transactions from a block (by number or hash)")
async def get_block_transactions(request, block_identifier: str):
    # Try to find block by number first
    try:
        block_num = int(block_identifier)
        if block_num >= len(blockchain.chain):
            return json({"error": "Block number out of range"}, status=404)
        block = blockchain.chain[block_num]
    except ValueError:
        # If not a number, try to find by hash
        block = None
        for b in blockchain.chain:
            if b.calculate_hash == block_identifier:
                block = b
                break
        if not block:
            return json({"error": "Block not found"}, status=404)

    # Format transactions with enhanced data
    formatted_txs = []
    for tx in block.transactions:
        formatted_tx = {
            "txid": tx["txid"],
            "sender": tx["sender"],
            "recipient": tx["recipient"],
            "amount": tx["quantity"],
            "fee": tx.get("fee", 0),
            "timestamp": tx["timestamp"],
            "memo": tx.get("memo", ""),
            "position_in_block": block.transactions.index(tx),
            "block_height": block.index,
            "block_hash": block.calculate_hash,
        }
        formatted_txs.append(formatted_tx)

    return json(
        {
            "block_height": block.index,
            "block_hash": block.calculate_hash,
            "timestamp": block.timestamp,
            "transaction_count": len(block.transactions),
            "transactions": formatted_txs,
        }
    )


@app.get("/network/block/<block_identifier>/summary")
@openapi.description("Get key block statistics")
async def get_block_summary(request, block_identifier: str):
    # Same block finding logic as above
    try:
        block_num = int(block_identifier)
        if block_num >= len(blockchain.chain):
            return json({"error": "Block number out of range"}, status=404)
        block = blockchain.chain[block_num]
    except ValueError:
        block = None
        for b in blockchain.chain:
            if b.calculate_hash == block_identifier:
                block = b
                break
        if not block:
            return json({"error": "Block not found"}, status=404)

    # Calculate block statistics
    total_fees = sum(tx.get("fee", 0) for tx in block.transactions)

    return json(
        {
            "block_height": block.index,
            "block_hash": block.calculate_hash,
            "miner": next(
                (
                    tx["recipient"]
                    for tx in block.transactions
                    if tx["sender"] == "node"
                ),
                "unknown",
            ),
            "total_transactions": len(block.transactions),
            "total_value": sum(tx["quantity"] for tx in block.transactions),
            "total_fees": total_fees,
            "miner_reward": blockchain.rewards,
            "timestamp": block.timestamp,
            "previous_block": block.prev_hash,
            "difficulty": blockchain.diff_at_height(block.index),
        }
    )


####################### USERS ####################################
@app.get("/user/balance/<address>")
@openapi.description("Get user balance")
async def get_balance(request, address):
    balance = blockchain.get_balance(address)
    return json({"Address": address, "Balance": balance})


######################### Wallet API #################################


@app.get("/wallet/create")
@openapi.description("Create a new wallet")
async def CreateWallet(request):
    wallet = blockchain.AddressGen.Generate()

    return json(
        {
            "address": wallet["address"],
            "seed": wallet["seed"],
            "message": "Securely store your seed if you want to regenerate this address",
        }
    )


# @app.post("/wallet/import")
# @openapi.description("Import an existing wallet")
# async def ImportWallet(request):
#     seed = request.json.get("seed", None)
#     wallet = blockchain.AddressGen.Load(seed)

#     return json({
#         "address": wallet['address'],
#         "seed": wallet['seed']
#     })


@app.get("/wallet/validate/<address>")
@openapi.description("Validate an address")
async def validate_address(request, address):
    return json(
        {
            "address": address,
            "is_valid": blockchain.AddressGen.Validate(address)["status"],
        }
    )


@app.post("/transaction/create")
@openapi.description("Create a new transaction and submit to mempool")
async def create_transaction(request):
    data = request.json
    # sender = data.get("sender")
    # recipient = data.get("recipient")
    # amount = data.get("amount")
    rawtx = data.get("rawtx")
    try:
        memo = data.get("memo")
    except:
        memo = None

    # if not all([sender, recipient, amount, rawtx]):
    #     return json({"status": False, "error": "Invalid Parameters"}, 400)

    # try:
    #     amount = float(amount)
    # except:
    #     return json({"status": False, "error": "Invalid Amount"}, 400)
    if not all([rawtx]):
        return json({"status": False, "error": "Invalid Parameters"}, 400)

    success = blockchain.new_transaction(rawtx, 0, memo)
    return json(success)


############################## Mempool API #################################
@app.get("/mempool/info")
@openapi.description("Get mempool information")
async def mempool_info(request):
    return json(
        {
            "count": len(blockchain.mempool.transactions),
            "capacity": blockchain.mempool.max_size,
            "next_block_tx_count": min(
                len(blockchain.mempool.transactions), blockchain.mempool.block_tx_limit
            ),
        }
    )


@app.get("/mempool/transactions")
@openapi.description("Get transactions in mempool")
async def mempool_transactions(request):
    count = min(int(request.args.get("count", 100)), 1000)
    return json({"transactions": blockchain.mempool.transactions[:count]})


############################# P2P network ##################################


@app.post("/block/new")
@openapi.description("Receive a new block from the network")
async def new_block(request):
    block_data = request.json
    try:
        block = Block.from_dict(block_data)
    except:
        return json({"status": "error", "message": "Invalid block data"}, 400)

    # Check if we already have this block
    if block.calculate_hash in blockchain.block_hash_map:
        return json({"status": "duplicate"}, 200)

    # Check if block is valid
    if not blockchain.verifying_proof(block.proofN, blockchain.latest_block.proofN):
        return json({"status": "error", "message": "Invalid block"}, 400)

    # Add to our chain
    blockchain.chain.append(block)
    blockchain.block_hash_map[block.calculate_hash] = block
    blockchain.SaveDB()
    blockchain.miniChain.SaveDB()

    # Remove transactions from mempool
    blockchain.mempool.remove_confirmed(block.transactions)
    print(
        colored(
            f"\n-----------\nNew Block mined!\nHeight: {len(blockchain.chain)}\nReward: {blockchain.rewards} AVRI \n-----------\n",
            "green",
        )
    )
    return json({"status": "success"})


@app.get("/network/peers")
@openapi.description("Get list of known peers")
async def get_peers(request):
    return json(
        {
            "Online_Peers": list(blockchain.p2p.connected_peers),
            "Known_Peers": list(blockchain.p2p.peers),
        }
    )


@app.post("/transaction/new")
@openapi.description("Receive a new transaction from the network")
async def new_transaction(request):
    tx = request.json
    try:
        # Basic validation
        required_fields = ["sender", "recipient", "quantity", "txid"]
        if not all(field in tx for field in required_fields):
            return json({"status": "error", "message": "Missing required fields"}, 400)

        # Check if already in mempool
        if any(t["txid"] == tx["txid"] for t in blockchain.mempool.transactions):
            return json({"status": "duplicate"}, 200)

        # Add to mempool
        blockchain.mempool.add_transaction(tx)
        return json({"status": "success"})

    except MempoolFullError:
        return json({"status": "error", "message": "Mempool full"}, 400)
    except Exception as e:
        return json({"status": "error", "message": str(e)}, 400)


async def network_maintenance():
    """Background tasks for network maintenance"""
    while True:
        try:
            # Peer discovery
            blockchain.p2p.discover_peers()

            # Maintain connections
            blockchain.p2p.maintain_connections()

            # Check for chain conflicts periodically
            if random.random() < 0.1:  # 10% chance each run
                blockchain.resolve_conflicts()

        except Exception as e:
            print(f"Network maintenance error: {e}")

        await asyncio.sleep(60)  # Run every minute


app.add_task(network_maintenance())

############################# Web3 Compat layer #############################
# for metamask very broken though


class Web3RPC:
    @staticmethod
    def AVRI_to_eth(address):
        """Convert AVRI-address to 0x-format"""
        if address.startswith("AVRI-"):
            # Take the first part of the AVRI address and pad with zeros
            clean_hex = address.replace("AVRI-", "").replace("-", "")[:40]
            return Web3.to_checksum_address("0x" + clean_hex.ljust(40, "0"))
        return address

    @staticmethod
    def eth_to_AVRI(address):
        """Convert 0x-address to AVRI-format"""
        print(address)
        if address.startswith("0x"):
            clean_hex = address[2:]
            # Reconstruct AVRI address format from the hex
            return f"AVRI-{clean_hex[:8]}-{clean_hex[8:16]}-{clean_hex[16:24]}-{clean_hex[24:32]}"
        print(address)
        return address

    @staticmethod
    def to_hex(value):
        """Convert value to hex string"""
        if isinstance(value, str) and value.startswith("0x"):
            return value
        return hex(int(value))

    @staticmethod
    def handle_web3_request(method, params):
        """Handle Web3 JSON-RPC methods"""
        try:
            if method == "eth_chainId":
                return hex(blockchain.CHAIN_ID)

            elif method == "net_version":
                return hex(blockchain.CHAIN_ID)

            elif method == "eth_blockNumber":
                return hex(blockchain.latest_block.index -1)

            elif method == "eth_getBalance":
                if len(params) < 2:
                    raise ValueError("Missing parameters")
                balance = int(blockchain.get_balance(Web3.to_checksum_address(params[0])))
                balance_in_wei = balance * (10 ** blockchain.DECIMAL)
                print(hex(balance_in_wei))
                return hex(balance_in_wei)

            elif method == "eth_getTransactionCount":
                if len(params) < 2:
                    raise ValueError("Missing parameters")
                address = (params[0])
                # In your system, we'll use the number of outgoing transactions as nonce
                # This is a simplification - you might need to track nonces properly
                nonce = blockchain.get_nonce(address)
                return hex(nonce)

            elif method == "eth_getBlockByNumber":
                if len(params) < 2:
                    raise ValueError("Missing parameters")

                block_num = params[0]
                full_tx = params[1]

                if block_num == "latest":
                    block = blockchain.latest_block
                elif block_num == "earliest":
                    block = blockchain.chain[0]
                else:
                    try:
                        block_num = (
                            int(block_num, 0)
                        )
                        if block_num >= len(blockchain.chain):
                            return None
                        block = blockchain.chain[block_num]
                    except:
                        return None

                # Convert transactions based on full_tx flag
                transactions = []
                if full_tx:
                    for tx in block.transactions:
                        transactions.append(
                            {
                                "hash": tx.get("txid", "0x" + secrets.token_hex(32)),
                                "from": (tx["sender"]),
                                "to": (tx["recipient"]),
                                "value": hex(
                                    int(tx["quantity"] * (10**blockchain.DECIMAL))
                                ),
                                "gas": hex(
                                    21000
                                ),  # Standard gas for simple transfer
                                "gasPrice": hex(1),  # Minimal gas price
                                "nonce": hex(
                                    0
                                ),  # Would need proper nonce tracking
                                "blockHash": "0x" + block.calculate_hash,
                                "blockNumber": hex(block.index),
                                "transactionIndex": hex(0),
                            }
                        )
                else:
                    transactions = [
                        tx.get("txid", "0x" + secrets.token_hex(32))
                        for tx in block.transactions
                    ]

                return {
                    "difficulty": hex(blockchain.diff),
                    "extraData": "0x",
                    "gasLimit": hex(8000000),
                    "gasUsed": hex(21000 * len(block.transactions)),
                    "hash": "0x" + block.calculate_hash,
                    "number": hex(block.index),
                    "logsBloom": "0x" + "0" * 512,
                    "parentHash": (
                        "0x" + block.prev_hash
                        if block.prev_hash != "0"
                        else "0x" + "0" * 64
                    ),
                    "nonce": "0x" + "0" * 16,
                    "sha3Uncles": "0x" + "0" * 64,
                    
                    "transactionsRoot": "0x" + "0" * 64,
                    "stateRoot": "0x" + "0" * 64,
                    "miner": (
                        "0x" + blockchain.find_miner(block.index).get("miner_address", "0") # type: ignore
                        if blockchain.find_miner(block.index)
                        else "0x0"
                    ),  # Your system uses "node" as miner
                    "difficulty": hex(blockchain.diff),
                    "totalDifficulty": hex(
                        blockchain.diff * (block.index + 1)
                    ),
                    "extraData": "0x",
                    "size": hex(1000),  # Approximate
                    "timestamp": hex(int(block.timestamp)),
                    "transactions": transactions,
                    "uncles": [],
                }

            # elif method == "eth_sendTransaction":
            #     if len(params) < 1:
            #         raise ValueError("Missing parameters")

            #     tx_data = params[0]
            #     sender = Web3RPC.eth_to_AVRI(tx_data.get("from"))
            #     recipient = Web3RPC.eth_to_AVRI(tx_data.get("to"))
            #     value = int(tx_data.get("value", "0x0"), 16) / (10**blockchain.DECIMAL)

            #     # In a real implementation, you'd need to:
            #     # 1. Verify the signature (your system currently uses seed)
            #     # 2. Handle nonce properly
            #     # For now, we'll just create a transaction (insecure - for demo only)

            #     # This is a major limitation - your system needs to support signed transactions
            #     # without requiring the seed to be sent to the server
            #     return {
            #         "error": "eth_sendTransaction not fully implemented - use eth_sendRawTransaction with proper signing"
            #     }

            elif method == "eth_sendRawTransaction":
                # This would need proper transaction signing implementation
                rawtx = params[0]
                # decoder = EthTxDecoder()
                # data = decoder.decode_raw_tx(rawtx)
                tx = blockchain.new_transaction(rawtx, 1, "web3 tx", rawtx)
                return tx["txid"]
            
            elif method == "eth_getTransactionReceipt":
                if len(params) < 1:
                    raise ValueError("Missing transaction ID parameter")
                
                gas = 0
                txid = params[0]
                print(txid)
                
                clean_txid = txid[2:] if txid.startswith('0x') else txid
                
                for tx in blockchain.mempool.transactions:
                    if tx.get("txid") == clean_txid or tx.get("txid") == txid:
                        print(f"[eth_getTransactionReceipt] Found in mempool: {txid[:16]}...")
                        return {
                            "transactionHash": txid,
                            "transactionIndex": None,
                            "blockNumber": None,  # null for pending
                            "blockHash": None,  # Zero hash for pending
                            #"from": tx["sender"],
                            #"to": tx["recipient"],
                            "cumulativeGasUsed": "0x5208",  # 21000 in hex
                            "gasUsed": "0x5208",
                            "contractAddress": None,
                            "logs": [],
                            "logsBloom": "0x" + "0" * 512,
                            "status": "0x1",
                            #"effectiveGasPrice": "0x" + hex(int(tx.get("fee", 1) * (10 ** blockchain.DECIMAL)))[2:],
                        }                

                # Search through all blocks for the transaction
                for block in blockchain.chain:
                    for tx in block.transactions:
                        if tx["txid"] == txid:
                            return {
                                "transactionHash": tx["txid"],
                                "transactionIndex": "0x1",
                                "blockNumber": str(hex(block.index)),
                                "blockHash": "0x" + str(block.calculate_hash),
                                "cumulativeGasUsed": hex(int(gas)),
                                #"effectiveGasPrice": hex(int(tx["fee"])),
                                "gasUsed": str(hex(int(tx["fee"]))),
                                "contractAddress": None,
                                "logs": [],
                                "logsBloom": "0x"+"0"*512,
                                #"from": tx["sender"],
                                "status": "0x1",
                                #"to": tx["recipient"],
                            }
                        gas += tx["fee"]

            elif method == "eth_gasPrice":
                #return hex(blockchain.avri_to_wei(int((blockchain.mempool.get_current_fee_percent())))) # Minimal gas price
                return hex(1000000000)

            elif method == "eth_estimateGas":
                return hex(21000000)  # Standard gas for simple transfer

            elif method == "eth_call":
                # For contract calls - your system doesn't support contracts yet
                return "0x"
            
            elif method == "eth_getBlockByHash":
                hash = params[0].lstrip("0x")
                blockc = blockchain.block_by_hash(hash)
                if not blockc:
                    return None
                gas_used = sum(tx.get("fee", 0) for tx in blockc.transactions)
                return {
                    "baseFeePerGas": hex(blockchain.avri_to_wei(int(round(blockchain.mempool.get_current_fee_percent())))),
                    "difficulty": 0x1,
                    "extraData": 0x0,
                    "gasLimit": hex(52),
                    "gasUsed": hex(gas_used),
                    "hash": blockc.hash,
                    "logsBloom": 0x0,
                    "miner": blockchain.find_miner(blockc.hash),
                    "mixHash" : hex(blockc.hash),
                    "nonce": hex(blockc.proofN),
                    "number": hex(blockc.index),
                    "parentHash": blockc.prev_hash,
                    "receiptsRoot": 0x0,
                    "sha3Uncles": 0x0,
                    "size": 0x100,
                    "stateroot": 0x1,
                    "timestamp": blockc.timestamp,
                    "transactions": blockc.transactions,
                }   
                
            # elif method == "getCode":
            #     return "0x"

            else:
                print(f"error method {method}")

        except Exception as e:
            return {"error": str(e)}


@app.post("/web3")
async def handleWeb3Request(request):
    try:
        data = request.json
        print(data)
        if isinstance(data, dict):
            # Single request
            method = data.get("method")
            params = data.get("params", [])
            id = data.get("id", 1)

            result = Web3RPC.handle_web3_request(method, params)
            print(result)
            return json({"id": id, "jsonrpc": "2.0", "result": result})

        elif isinstance(data, list):
            # Batch request
            responses = []
            for item in data:
                method = item.get("method")
                params = item.get("params", [])
                id = item.get("id", 1)

                result = Web3RPC.handle_web3_request(method, params)

                if isinstance(result, dict) and "error" in result:
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": id,
                            "error": {"code": -32602, "message": result["error"]},
                        }
                    )
                else:
                    responses.append({"jsonrpc": "2.0", "id": id, "result": result})

            return json(responses)

        else:
            return json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
                status=400,
            )

    except Exception as e:
        return json(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
            },
            status=500,
        )


@app.route("/openapi.json")
async def serve_openapi_spec(request):
    # Load your custom OpenAPI spec
    with open(os.path.join(os.path.dirname(__file__), "openapi.json"), "r") as f:
        spec = jsonify.load(f)
    return json(spec)


if __name__ == "__main__":
    greeter("src/data/config.json", AddressGen)

    app.run(debug=True, port=4024, single_process=True, host="0.0.0.0")
