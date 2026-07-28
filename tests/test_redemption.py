from web3 import Web3

from polymarket_mm_bot.redemption import (
    BINARY_INDEX_SETS,
    DryRunRedeemer,
    RedemptionRetryQueue,
    build_redeem_transaction,
    should_attempt_redemption,
)

CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
COLLATERAL_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CONDITION_ID = "0x624ef2c097ae683c51c76d61a5dfbfbfa31509ce3cbef05496097ef0b5c0382e"
FROM_ADDRESS = "0x1111111111111111111111111111111111111111"


def test_should_attempt_redemption_true_when_up_shares_positive():
    assert should_attempt_redemption(up_shares=10.0, down_shares=0.0) is True


def test_should_attempt_redemption_true_when_down_shares_positive():
    assert should_attempt_redemption(up_shares=0.0, down_shares=5.0) is True


def test_should_attempt_redemption_false_when_flat():
    assert should_attempt_redemption(up_shares=0.0, down_shares=0.0) is False


def test_build_redeem_transaction_encodes_expected_selector_and_fields():
    tx = build_redeem_transaction(
        conditional_tokens_address=CONDITIONAL_TOKENS_ADDRESS,
        collateral_address=COLLATERAL_ADDRESS,
        condition_id=CONDITION_ID,
        from_address=FROM_ADDRESS,
        nonce=7,
        gas=130_000,
        gas_price=30_000_000_000,
        chain_id=137,
    )
    # 0x01b7037c is redeemPositions(address,bytes32,bytes32,uint256[])'s real
    # 4-byte selector, confirmed present in the deployed contract's bytecode.
    assert tx["data"].startswith("0x01b7037c")
    assert tx["to"] == Web3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS)
    assert tx["from"] == Web3.to_checksum_address(FROM_ADDRESS)
    assert tx["nonce"] == 7
    assert tx["gas"] == 130_000
    assert tx["gasPrice"] == 30_000_000_000
    assert tx["chainId"] == 137


def test_build_redeem_transaction_is_deterministic():
    kwargs = dict(
        conditional_tokens_address=CONDITIONAL_TOKENS_ADDRESS,
        collateral_address=COLLATERAL_ADDRESS,
        condition_id=CONDITION_ID,
        from_address=FROM_ADDRESS,
        nonce=1,
        gas=100_000,
        gas_price=1,
        chain_id=137,
    )
    assert build_redeem_transaction(**kwargs)["data"] == build_redeem_transaction(**kwargs)["data"]


def test_binary_index_sets_cover_both_outcomes():
    assert BINARY_INDEX_SETS == [1, 2]


def test_dry_run_redeemer_logs_and_returns_placeholder_hash():
    redeemer = DryRunRedeemer()
    tx_hash = redeemer.redeem(CONDITION_ID)
    assert redeemer.redeemed_log == [CONDITION_ID]
    assert tx_hash == "dryrun-redeem-1"


def test_dry_run_redeemer_logs_each_call_separately():
    redeemer = DryRunRedeemer()
    redeemer.redeem(CONDITION_ID)
    redeemer.redeem(CONDITION_ID)
    assert redeemer.redeemed_log == [CONDITION_ID, CONDITION_ID]


def test_retry_queue_starts_with_nothing_pending():
    queue = RedemptionRetryQueue(max_attempts=3)
    assert queue.pending() == []
    assert queue.exhausted() == []
    assert queue.attempt_count(CONDITION_ID) == 0


def test_retry_queue_record_failure_tracks_attempt_count():
    queue = RedemptionRetryQueue(max_attempts=3)
    queue.record_failure(CONDITION_ID)
    assert queue.attempt_count(CONDITION_ID) == 1
    assert queue.pending() == [CONDITION_ID]


def test_retry_queue_record_failure_returns_false_before_max_attempts():
    queue = RedemptionRetryQueue(max_attempts=3)
    assert queue.record_failure(CONDITION_ID) is False
    assert queue.record_failure(CONDITION_ID) is False


def test_retry_queue_record_failure_returns_true_on_crossing_max_attempts():
    queue = RedemptionRetryQueue(max_attempts=2)
    assert queue.record_failure(CONDITION_ID) is False
    assert queue.record_failure(CONDITION_ID) is True


def test_retry_queue_exhausted_items_excluded_from_pending():
    queue = RedemptionRetryQueue(max_attempts=2)
    queue.record_failure(CONDITION_ID)
    queue.record_failure(CONDITION_ID)
    assert queue.pending() == []
    assert queue.exhausted() == [CONDITION_ID]


def test_retry_queue_record_success_clears_condition():
    queue = RedemptionRetryQueue(max_attempts=3)
    queue.record_failure(CONDITION_ID)
    queue.record_success(CONDITION_ID)
    assert queue.pending() == []
    assert queue.attempt_count(CONDITION_ID) == 0


def test_retry_queue_record_success_on_untracked_condition_is_a_noop():
    queue = RedemptionRetryQueue(max_attempts=3)
    queue.record_success("never-failed")  # should not raise
    assert queue.pending() == []


def test_retry_queue_persists_across_reload(tmp_path):
    state_path = tmp_path / "redemption_queue.json"
    queue = RedemptionRetryQueue(max_attempts=5, state_path=state_path)
    queue.record_failure(CONDITION_ID)

    reloaded = RedemptionRetryQueue(max_attempts=5, state_path=state_path)
    assert reloaded.attempt_count(CONDITION_ID) == 1
    assert reloaded.pending() == [CONDITION_ID]


def test_retry_queue_persists_success_removal_across_reload(tmp_path):
    state_path = tmp_path / "redemption_queue.json"
    queue = RedemptionRetryQueue(max_attempts=5, state_path=state_path)
    queue.record_failure(CONDITION_ID)
    queue.record_success(CONDITION_ID)

    reloaded = RedemptionRetryQueue(max_attempts=5, state_path=state_path)
    assert reloaded.pending() == []
    assert reloaded.attempt_count(CONDITION_ID) == 0


def test_retry_queue_with_no_state_path_does_not_touch_disk(tmp_path):
    queue = RedemptionRetryQueue(max_attempts=5, state_path=None)
    queue.record_failure(CONDITION_ID)
    assert list(tmp_path.iterdir()) == []
