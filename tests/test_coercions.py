import pytest

from zippering import UnsafeCoercion, normalize, register_coercer


def test_identity_passthrough():
    assert normalize("hello", "text", "text") == "hello"


def test_text_to_integer():
    assert normalize("42", "text", "integer") == 42


def test_text_to_integer_unsafe():
    with pytest.raises(UnsafeCoercion):
        normalize("not-a-number", "text", "integer")


def test_text_to_numeric():
    assert normalize("3.14", "text", "numeric") == pytest.approx(3.14)


def test_text_to_boolean():
    assert normalize("yes", "text", "boolean") is True
    assert normalize("0", "text", "boolean") is False
    with pytest.raises(UnsafeCoercion):
        normalize("maybe", "text", "boolean")


def test_integer_to_timestamp_roundtrip():
    ts = normalize(0, "integer", "timestamp")
    assert ts == "1970-01-01T00:00:00.000Z"
    assert normalize(ts, "timestamp", "integer") == 0


def test_text_to_string_array():
    assert normalize("x", "text", "string[]") == ["x"]


def test_unregistered_pair_is_unsafe():
    with pytest.raises(UnsafeCoercion):
        normalize(True, "boolean", "timestamp")


def test_register_custom_coercer():
    def to_cents(v):
        try:
            return round(float(v) * 100)
        except (TypeError, ValueError):
            raise UnsafeCoercion("text", "cents", v) from None

    register_coercer("text", "cents", to_cents)
    assert normalize("1.5", "text", "cents") == 150
    with pytest.raises(UnsafeCoercion):
        normalize("nope", "text", "cents")
