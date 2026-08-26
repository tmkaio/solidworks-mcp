"""
COM test doubles.

The single most important thing to know when writing tests here:

    _com_call(obj, "Foo") does NOT necessarily call obj.Foo().

It reads the attribute and only invokes it when it is a genuine Python
method or builtin. Anything else is returned as-is, because that is how
pywin32 surfaces an auto-evaluated zero-argument COM property.

So a double must expose `GetTypeName2` as the *string itself*, not as a
callable returning it. MagicMock gets this wrong in a way that silently
produces nonsense: `mock.GetTypeName2.return_value = "SheetMetal"` leaves
the attribute as a MagicMock child, which _com_call hands straight back,
so the comparison against "SheetMetal" fails and traversal never ends.

FakeCom below models the COM side faithfully: plain attributes.
"""

from types import SimpleNamespace


class FakeCom(SimpleNamespace):
    """
    A stand-in for a COM object as pywin32 late-binding presents it.

    Every value is a plain attribute, so _com_call() returns it directly.
    Attributes that are simply absent raise AttributeError, which is what
    the production code's per-attribute try/except blocks expect when a
    given SolidWorks feature type does not carry that property.
    """


def feature(type_name, *, name=None, next_feature=None, sub_feature=None, definition=None):
    """Build a fake IFeature for feature-tree traversal tests."""
    return FakeCom(
        Name=name if name is not None else f"{type_name}1",
        GetTypeName2=type_name,
        GetNextFeature=next_feature,
        GetFirstSubFeature=sub_feature,
        GetDefinition=definition,
    )


def chain(*features):
    """Link features into a sibling chain and return the first one."""
    for current, following in zip(features, features[1:]):
        current.GetNextFeature = following
    features[-1].GetNextFeature = None
    return features[0]


def get_tool(mcp_instance, name: str):
    """Retrieve a registered tool function from a FastMCP instance by name."""
    tools_dict = getattr(mcp_instance, "_tools", None)
    if tools_dict and name in tools_dict:
        fn = tools_dict[name]
        return fn.fn if hasattr(fn, "fn") else fn

    tool_manager = getattr(mcp_instance, "_tool_manager", None)
    if tool_manager:
        mgr_tools = getattr(tool_manager, "_tools", {})
        if name in mgr_tools:
            fn = mgr_tools[name]
            return fn.fn if hasattr(fn, "fn") else fn

    raise KeyError(f"Tool '{name}' not found in FastMCP instance")
