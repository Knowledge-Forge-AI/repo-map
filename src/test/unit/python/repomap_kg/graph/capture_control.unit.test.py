"""Real callback identity and exact iterator custody at the capture boundary."""
import pytest
from common_lore_index.graph._capture_control import CaptureControl, controlled_capture


class OwnedIterator:
    def __init__(self, values=(), *, close_error=None, read_error=None):
        self.values = iter(values)
        self.close_error = close_error
        self.read_error = read_error
        self.closes = 0
        self.reads = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        return next(self.values)

    def close(self):
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


@pytest.mark.parametrize("error", [OSError("callback"), ValueError("callback"), RuntimeError("callback"), KeyboardInterrupt(), SystemExit(3)])
def test_callback_keeps_exact_primary_across_normalizers_and_failed_release(error):
    iterator = OwnedIterator([1, 2], close_error=OSError("release"))
    checks = []
    previous_context, previous_cause = LookupError("context"), TypeError("cause")
    error.__context__, error.__cause__ = previous_context, previous_cause

    def check():
        checks.append(True)
        if len(checks) == 3:
            raise error

    def operation(guarded):
        try:
            return CaptureControl(guarded).collect(iterator)
        except (OSError, ValueError) as normalized:
            raise RuntimeError("incorrect normalization") from normalized

    with pytest.raises(type(error)) as caught:
        controlled_capture(check, operation)
    assert caught.value is error and iterator.closes == 1 and iterator.reads == 1
    assert error.__context__ is previous_context and error.__cause__ is previous_cause


@pytest.mark.parametrize("mode", ["normal", "read-error", "body-error", "release-error", "body-and-release"])
def test_each_acquired_iterator_is_closed_once_with_actual_primary(mode):
    primary, release = ValueError("body"), OSError("release")
    iterator = OwnedIterator([1], read_error=primary if mode == "read-error" else None,
                             close_error=release if mode in {"release-error", "body-and-release"} else None)
    reached = None
    try:
        with CaptureControl(lambda: None).iterating(iterator) as controlled:
            if mode in {"body-error", "body-and-release"}:
                next(controlled)
                raise primary
            assert tuple(controlled) == (1,)
    except BaseException as error:
        reached = error
    expected = None if mode == "normal" else release if mode == "release-error" else primary
    assert reached is expected and iterator.closes == 1


def test_pre_consumption_refusal_and_iter_failure_have_exact_ownership():
    failure = ValueError("acquisition")
    iterator = OwnedIterator([1])

    def check():
        raise failure

    with pytest.raises(ValueError) as caught:
        controlled_capture(check, lambda guarded: CaptureControl(guarded).collect(iterator))
    assert caught.value is failure and iterator.reads == 0 and iterator.closes == 1

    class NoIterator:
        closes = 0

        def __iter__(self):
            raise failure

        def close(self):
            self.closes += 1

    no_iterator = NoIterator()
    with pytest.raises(ValueError) as caught:
        CaptureControl(lambda: None).collect(no_iterator)
    assert caught.value is failure and no_iterator.closes == 0


def test_distinct_iterable_not_closed_and_default_does_not_acquire_new_custody():
    owned = OwnedIterator([1, 2])

    class Container:
        def __iter__(self):
            return owned

        def close(self):
            raise AssertionError("unowned iterable was closed")

    assert CaptureControl(lambda: None).collect(Container()) == (1, 2)
    assert owned.closes == 1
    legacy = OwnedIterator([3])
    assert CaptureControl().collect(legacy) == (3,) and legacy.closes == 0
    assert CaptureControl().keywords == {}


@pytest.mark.parametrize("release", [KeyboardInterrupt(), SystemExit(4)])
def test_process_control_from_release_is_not_suppressed(release):
    owned = OwnedIterator([1], close_error=release)
    with pytest.raises(type(release)) as caught:
        with CaptureControl(lambda: None).iterating(owned):
            raise ValueError("body")
    assert caught.value is release and owned.closes == 1


def test_legacy_cleanup_winner_retains_original_callback_in_public_chain():
    primary, release = ValueError("callback"), OSError("legacy writer cleanup")

    def check():
        raise primary

    def operation(guarded):
        try:
            guarded()
        finally:
            raise release

    with pytest.raises(OSError) as caught:
        controlled_capture(check, operation)
    assert caught.value is release and release.__context__ is primary
    assert primary.__context__ is primary.__cause__ is None


def test_handled_caller_exception_cannot_hide_normal_path_release_failure():
    release = OSError("normal release")
    owned = OwnedIterator([1], close_error=release)
    try:
        raise ValueError("handled caller exception")
    except ValueError:
        with pytest.raises(OSError) as caught:
            with CaptureControl(lambda: None).iterating(owned) as controlled:
                assert tuple(controlled) == (1,)
        assert caught.value is release and owned.closes == 1


def test_public_exception_projection_preserves_non_carrier_cycles():
    first, second = ValueError("first"), OSError("second")
    first.__cause__ = second
    second.__context__ = first

    def check():
        raise first

    with pytest.raises(ValueError) as caught:
        controlled_capture(check, lambda guarded: CaptureControl(guarded).check())
    assert caught.value is first and first.__cause__ is second and second.__context__ is first
