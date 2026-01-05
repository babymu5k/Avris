import rlp
from dataclasses import asdict, dataclass
from typing import Optional
from eth_utils.conversions import to_bytes

from eth_typing import HexStr
from eth_utils.crypto import keccak
from rlp.sedes import Binary, big_endian_int, binary
from web3 import Web3
from web3.auto import w3


class EthTxDecoder(object):
    class Transaction(rlp.Serializable):
        fields = [
            ("nonce", big_endian_int),
            ("gas_price", big_endian_int),
            ("gas", big_endian_int),
            ("to", Binary.fixed_length(20, allow_empty=True)),
            ("value", big_endian_int),
            ("data", binary),
            ("v", big_endian_int),
            ("r", big_endian_int),
            ("s", big_endian_int),
        ]

    @dataclass
    class DecodedTx:
        hash_tx: str
        from_: str
        to: Optional[str]
        nonce: int
        gas: int
        gas_price: int
        value: int
        data: str
        chain_id: int
        r: str
        s: str
        v: int

    def hex_to_bytes(self, data: str) -> bytes:
        return to_bytes(hexstr=HexStr(data))

    def decode_raw_tx(self, raw_tx: str):
        tx = rlp.decode(self.hex_to_bytes(raw_tx), self.Transaction)
        tx = self.Transaction(*tx) if isinstance(tx, list) else tx
        hash_tx = Web3.to_hex(keccak(self.hex_to_bytes(raw_tx)))
        from_ = w3.eth.account.recover_transaction(raw_tx)
        to = Web3.to_checksum_address(tx.to) if tx.to else None
        data = w3.to_hex(tx.data)
        r = hex(tx.r)
        s = hex(tx.s)
        chain_id = (tx.v - 35) // 2 if tx.v % 2 else (tx.v - 36) // 2
        return asdict(
            self.DecodedTx(
                hash_tx,
                from_,
                to,
                tx.nonce,
                tx.gas,
                tx.gas_price,
                tx.value,
                data,
                chain_id,
                r,
                s,
                tx.v,
            )
        )

