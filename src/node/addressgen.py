import hashlib
import secrets

from eth_account import Account
from mnemonic import Mnemonic
from web3 import Web3


# class AddressGen:
#     """Address Generation for Avris"""
#     def __init__(self, wordlist):
#         self.WORDLIST = wordlist

#     #@staticmethod
#     def generate(self, seed=None):
#         """Create a beautiful deterministic address"""
#         seed = seed or secrets.token_hex(16)  # 16 random bytes if no seed

#         # Hash the seed
#         seed_hash = hashlib.sha256(seed.encode()).digest()
#         # Convert to 4 words
#         word_indices = [
#             int.from_bytes(seed_hash[i:i+2], 'big') % len(self.WORDLIST)
#             for i in range(0, 8, 2)
#         ]
#         words = [self.WORDLIST[i] for i in word_indices]

#         # Generate checksum (first 4 chars of hash)
#         phrase = "-".join(words)
#         checksum = hashlib.sha256(phrase.encode()).hexdigest()[:4]

#         return {
#             "address": f"AVRI-{phrase}-{checksum}",
#             "seed": seed,  # Keep this secret!
#         }

#     #@staticmethod
#     def validate(self, address):
#         """Check if an address is valid"""
#         if not address.startswith("AVRI-"):
#             return False

#         parts = address.split("-")
#         if len(parts) != 6:  # AVRI + 4 words + checksum
#             return False

#         checksum = parts[-1]
#         phrase = "-".join(parts[1:-1])

#         # Verify checksum
#         expected_checksum = hashlib.sha256(phrase.encode()).hexdigest()[:4]
#         return checksum == expected_checksum

#     #@staticmethod
#     def verify_ownership(self, claimed_address, seed):
#         """Verify that seed generates the claimed address"""
#         generated_address = self.generate(seed)["address"]
#         return generated_address == claimed_address

Account.enable_unaudited_hdwallet_features()


class AddressGen:
    def __init__(self) -> None:
        pass

    def Generate(self):
        mn = Mnemonic("english")
        words = mn.generate()
        priv_key = self.WordtoKey(words)
        pub_key = priv_key.address

        return {"address": pub_key, "seed": priv_key.key.hex(), "status": True}

    def WordtoKey(self, words):
        priv_key = Account.from_mnemonic(words)
        return priv_key

    def Load(self, key):
        try:
            account = Account.from_key(key)
            return {
                "address": account.address,
                "seed": account.key.hex(),
                "status": True,
            }
        except:
            return {"error": "Failed to load key", "status": False}

    def Validate(self, address):
        if Web3.is_address(address):
            return {"status": True}
        else:
            return {"status": False}

    def VerifyTransaction(self, address, rawTX):
        recievedA = Account.recover_transaction(rawTX)
        print(recievedA)
        if address == recievedA:
            return {"status": True}
        else:
            return {"status": False}
