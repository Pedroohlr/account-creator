from automate_accounts.ui.estimate import (
    DEFAULT_ACCOUNT_SECONDS,
    FIRST_DEVICE_SECONDS,
    ROTATE_NOWIPE_SECONDS,
    ROTATE_WIPE_SECONDS,
    devices_needed,
    estimate_seconds,
    fmt_duration,
)


def test_devices_needed():
    assert devices_needed(20, 5) == 4
    assert devices_needed(21, 5) == 5
    assert devices_needed(1, 5) == 1


def test_estimate_20_accounts_5_per_device():
    expected = FIRST_DEVICE_SECONDS + 3 * ROTATE_WIPE_SECONDS + 20 * DEFAULT_ACCOUNT_SECONDS
    assert estimate_seconds(20, 5) == expected


def test_estimate_without_wipe_and_with_measured_average():
    assert estimate_seconds(10, 5, wipe=False, account_seconds=60) == (
        FIRST_DEVICE_SECONDS + ROTATE_NOWIPE_SECONDS + 600
    )


def test_fmt_duration():
    assert fmt_duration(None) == "—"
    assert fmt_duration(45) == "45s"
    assert fmt_duration(142) == "2min22s"
    assert fmt_duration(3900) == "1h05min"
