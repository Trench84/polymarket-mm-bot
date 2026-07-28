from __future__ import annotations

from typing import Protocol

from web3 import Web3

# Standard Gnosis Conditional Tokens Framework interface, used unmodified by
# Polymarket's ConditionalTokens contract. Selector 0x01b7037c was confirmed
# present in the deployed contract's runtime bytecode on Polygon
# (0x4D97DCd97eC945f40cF65F87097ACe5EA0476045) while building this module.
REDEEM_POSITIONS_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "collateralToken", "type": "address"},
            {"internalType": "bytes32", "name": "parentCollectionId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
            {"internalType": "uint256[]", "name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

ZERO_BYTES32 = "0x" + "00" * 32
# Binary market outcome index sets: outcome 0 (Up) = bit 0 = 1, outcome 1
# (Down) = bit 1 = 2. Passing both redeems whichever side the wallet actually
# holds in one transaction; a zero balance on either side pays out zero
# rather than reverting - verified by simulating this exact call against the
# live contract with a zero-balance address (no funds moved, read-only call).
BINARY_INDEX_SETS = [1, 2]


def should_attempt_redemption(up_shares: float, down_shares: float) -> bool:
    return up_shares > 0 or down_shares > 0


def build_redeem_transaction(
    conditional_tokens_address: str,
    collateral_address: str,
    condition_id: str,
    from_address: str,
    nonce: int,
    gas: int,
    gas_price: int,
    chain_id: int = 137,
) -> dict:
    """Pure ABI-encoding step - no network access, takes gas/nonce as inputs
    rather than estimating them, so it's fully unit-testable offline."""
    w3 = Web3()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(conditional_tokens_address),
        abi=REDEEM_POSITIONS_ABI,
    )
    function_call = contract.functions.redeemPositions(
        Web3.to_checksum_address(collateral_address),
        Web3.to_bytes(hexstr=ZERO_BYTES32),
        Web3.to_bytes(hexstr=condition_id),
        BINARY_INDEX_SETS,
    )
    return function_call.build_transaction(
        {
            "from": Web3.to_checksum_address(from_address),
            "nonce": nonce,
            "chainId": chain_id,
            "gas": gas,
            "gasPrice": gas_price,
        }
    )


class RedeemerProtocol(Protocol):
    def redeem(self, condition_id: str) -> str: ...


class DryRunRedeemer:
    """Logs intended redemptions instead of sending a real transaction."""

    def __init__(self) -> None:
        self.redeemed_log: list[str] = []

    def redeem(self, condition_id: str) -> str:
        self.redeemed_log.append(condition_id)
        return f"dryrun-redeem-{len(self.redeemed_log)}"


class RedemptionClient:
    """Submits a real redeemPositions transaction to the ConditionalTokens
    contract. This is a raw on-chain call, not part of Polymarket's REST/CLOB
    API surface. Gas and nonce are fetched live from the connected RPC at
    call time; the ABI-encoding itself is the pure, tested
    build_redeem_transaction() above."""

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        conditional_tokens_address: str,
        collateral_address: str,
        chain_id: int = 137,
    ) -> None:
        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._account = self._w3.eth.account.from_key(private_key)
        self._conditional_tokens_address = conditional_tokens_address
        self._collateral_address = collateral_address
        self._chain_id = chain_id
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(conditional_tokens_address),
            abi=REDEEM_POSITIONS_ABI,
        )

    def redeem(self, condition_id: str) -> str:
        nonce = self._w3.eth.get_transaction_count(self._account.address)
        gas_price = self._w3.eth.gas_price
        function_call = self._contract.functions.redeemPositions(
            Web3.to_checksum_address(self._collateral_address),
            Web3.to_bytes(hexstr=ZERO_BYTES32),
            Web3.to_bytes(hexstr=condition_id),
            BINARY_INDEX_SETS,
        )
        gas = function_call.estimate_gas({"from": self._account.address})
        transaction = build_redeem_transaction(
            conditional_tokens_address=self._conditional_tokens_address,
            collateral_address=self._collateral_address,
            condition_id=condition_id,
            from_address=self._account.address,
            nonce=nonce,
            gas=gas,
            gas_price=gas_price,
            chain_id=self._chain_id,
        )
        signed = self._account.sign_transaction(transaction)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()
