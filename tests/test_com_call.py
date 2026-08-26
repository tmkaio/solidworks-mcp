"""
Tests for _com_call().

This helper encodes a non-obvious pywin32 rule, and getting it wrong is not
hypothetical: two of this project's tests were silently broken for exactly
this reason, and the analysis/file_ops modules once shipped without the
import at all.

The rule: invoke the attribute only when it is a real Python method or
builtin. Everything else is returned untouched, because pywin32 may have
already auto-evaluated a zero-argument COM property on attribute access.
Crucially the check must NOT be `callable()`, because win32com CDispatch
objects are callable — they forward to the COM default member — so calling
one would re-dispatch instead of returning the value.
"""

import pytest

from solidworks_mcp.solidworks_bridge import _com_call


class WithMethods:
    """An object whose COM-ish members are real bound methods."""

    def GetTitle(self):
        return "bracket"

    def GetTypeName2(self):
        return "SheetMetal"

    def SelectByID2(self, name, kind, x, y, z):
        return (name, kind, x, y, z)


class AutoEvaluated:
    """
    An object as pywin32 leaves it after auto-evaluating a zero-argument
    method: the attribute IS the result, not a callable returning it.
    """

    GetTitle = "bracket"
    GetType = 1
    FirstFeature = None


class CallableValue:
    """
    Stands in for a CDispatch: the value is callable but is not a Python
    method. _com_call must return it rather than invoking it.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return "SHOULD NOT BE REACHED"


# ---------------------------------------------------------------------------
# Real methods are invoked
# ---------------------------------------------------------------------------


def test_bound_method_is_invoked():
    assert _com_call(WithMethods(), "GetTitle") == "bracket"


def test_bound_method_receives_arguments():
    obj = WithMethods()
    assert _com_call(obj, "SelectByID2", "Face1", "FACE", 0.0, 1.0, 2.0) == (
        "Face1",
        "FACE",
        0.0,
        1.0,
        2.0,
    )


def test_builtin_function_is_invoked():
    # str.upper on an instance is a builtin method, not a Python function.
    assert _com_call("bracket", "upper") == "BRACKET"


# ---------------------------------------------------------------------------
# Auto-evaluated properties are returned as-is
# ---------------------------------------------------------------------------


def test_auto_evaluated_value_is_returned_untouched():
    assert _com_call(AutoEvaluated(), "GetTitle") == "bracket"


def test_auto_evaluated_int_is_returned_untouched():
    """The 'int object is not callable' case the docstring calls out."""
    assert _com_call(AutoEvaluated(), "GetType") == 1


def test_auto_evaluated_none_is_returned_untouched():
    """Feature traversal relies on None terminating the chain."""
    assert _com_call(AutoEvaluated(), "FirstFeature") is None


def test_callable_non_method_is_not_invoked():
    """
    The reason the implementation cannot use callable(): a CDispatch is
    callable, and invoking it would trigger COM default-member re-dispatch.
    """
    value = CallableValue()
    obj = AutoEvaluated()
    obj.SomeDispatch = value

    assert _com_call(obj, "SomeDispatch") is value
    assert value.calls == 0


# ---------------------------------------------------------------------------
# Misuse is reported, not silently swallowed
# ---------------------------------------------------------------------------


def test_arguments_against_a_non_method_raise_type_error():
    with pytest.raises(TypeError) as excinfo:
        _com_call(AutoEvaluated(), "GetType", 42)

    message = str(excinfo.value)
    assert "GetType" in message
    assert "int" in message  # names the type it actually resolved to


def test_missing_attribute_propagates():
    """No attribute means the caller asked for the wrong thing — surface it."""
    with pytest.raises(AttributeError):
        _com_call(AutoEvaluated(), "NoSuchMember")
