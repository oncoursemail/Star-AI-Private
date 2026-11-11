"""PortAudio stream-clock mapping tests without opening a physical audio device."""
from types import SimpleNamespace

import pytest

from star.voice.devices import _device_output_monotonic


def test_portaudio_dac_time_maps_to_host_monotonic_clock():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=10.024)
    assert _device_output_monotonic(50.0, info) == pytest.approx(50.024)


def test_small_negative_dac_offset_is_clamped_to_callback_time():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=9.99)
    assert _device_output_monotonic(50.0, info) == pytest.approx(50.0)


@pytest.mark.parametrize(
    "info",
    [
        None,
        SimpleNamespace(currentTime=float("nan"), outputBufferDacTime=10.0),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=float("inf")),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=12.0),
        SimpleNamespace(currentTime=10.0, outputBufferDacTime=9.0),
        SimpleNamespace(currentTime="bad", outputBufferDacTime=10.0),
    ],
)
def test_invalid_or_implausible_portaudio_clock_mapping_is_unknown(info):
    assert _device_output_monotonic(50.0, info) is None


def test_nonfinite_host_clock_is_rejected():
    info = SimpleNamespace(currentTime=10.0, outputBufferDacTime=10.01)
    assert _device_output_monotonic(float("nan"), info) is None
