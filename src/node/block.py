import time
from blake3 import blake3
import hashlib
from groestlcoin_hash import getHash


class Block:
    def __init__(
        self,
        index,
        proofN,
        prev_hash,
        transactions,
        timestamp=None,
        hash=None,
        mini_avr_root=None,
    ):
        self.index = index
        self.proofN = proofN
        self.prev_hash = prev_hash
        self.transactions = transactions
        self.timestamp = timestamp or time.time()
        self.mini_avr_root = mini_avr_root  # Merkle root of Mini-AVR blocks
        self.hash = self.calculate_hash

    @property
    def calculate_hash(self):
        block_of_string = "{}{}{}{}{}{}".format(
            self.index,
            self.proofN,
            self.prev_hash,
            self.transactions,
            self.timestamp,
            self.mini_avr_root or "",
        )

        return getHash(block_of_string.encode(), len(block_of_string)).hex()

    def __repr__(self):
        return "{} - {} - {} - {} - {} - {} - {}".format(
            self.index,
            self.proofN,
            self.prev_hash,
            self.transactions,
            self.timestamp,
            self.hash,
            self.mini_avr_root,
        )

    def to_dict(self):
        return {
            "index": self.index,
            "proofN": self.proofN,
            "prev_hash": self.prev_hash,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "hash": self.hash,
            "mini_avr_root": self.mini_avr_root,
        }

    @classmethod
    def from_dict(cls, block_dict):
        return cls(
            index=block_dict["index"],
            proofN=block_dict["proofN"],
            prev_hash=block_dict["prev_hash"],
            transactions=block_dict["transactions"],
            timestamp=block_dict["timestamp"],
            hash=block_dict["hash"],
            mini_avr_root=block_dict["mini_avr_root"],
        )


class MiniAVRBlock:
    def __init__(
        self, index, proofN, prev_hash, miner_address, timestamp=None, hash=None
    ):
        self.index = index
        self.proofN = proofN
        self.prev_hash = prev_hash
        self.miner_address = miner_address
        self.timestamp = timestamp or time.time()
        self.hash = self.calculate_hash

    @property
    def calculate_hash(self):
        """Arduino/ESP uses SHA1 for mini-blocks"""
        block_string = f"{self.index}{self.proofN}{self.prev_hash}{self.miner_address}{self.timestamp}"
        return hashlib.sha1(block_string.encode()).hexdigest()

    def __repr__(self):
        return "{} - {} - {} - {} - {} - {}".format(
            self.index,
            self.proofN,
            self.prev_hash,
            self.miner_address,
            self.timestamp,
            self.hash,
        )

    def to_dict(self):
        return {
            "index": self.index,
            "proofN": self.proofN,
            "prev_hash": self.prev_hash,
            "miner_address": self.miner_address,
            "timestamp": self.timestamp,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, block_dict):
        return cls(
            index=block_dict["index"],
            proofN=block_dict["proofN"],
            prev_hash=block_dict["prev_hash"],
            miner_address=block_dict["miner_address"],
            timestamp=block_dict["timestamp"],
            hash=block_dict["hash"],
        )
