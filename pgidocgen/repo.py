# -*- coding: utf-8 -*-
# Copyright 2013,2014 Christoph Reiter
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.

import re

from gi.repository import GObject

from .namespace import get_namespace
from . import util
from .util import unindent, gtype_to_rest

from .gtkstock import parse_stock_icon
from .funcsig import FuncSignature
from .parser import docstring_to_rest


class Property(object):

    def __init__(self, name, attr_name, type_desc, readable, writable,
                 construct, short_desc, desc):
        self.name = name
        self.attr_name = attr_name
        self.type_desc = type_desc

        self.readable = readable
        self.writable = writable
        self.construct = construct

        self.short_desc = short_desc
        self.desc = desc

    @property
    def flags_string(self):
        flags = []
        if self.readable:
            flags.append("r")
        if self.writable:
            flags.append("w")
        if self.construct:
            flags.append("c")
        return "/".join(flags)


class Signal(object):

    def __init__(self, name, params, ret, desc, short_desc):
        self.name = name
        self.params = params
        self.ret = ret

        self.desc = desc
        self.short_desc = short_desc


class Repository(object):
    """Takes gi objects and gives documented code"""

    def __init__(self, namespace, version):
        self.namespace = namespace
        self.version = version

        self._ns = ns = get_namespace(namespace, version)

        # Gtk.foo_bar.arg1 -> "some doc"
        self._parameters = {}

        # Gtk.foo_bar -> "some doc"
        # Gtk.Foo.foo_bar -> "some doc"
        self._returns = {}

        # Gtk.foo_bar -> "some doc"
        # Gtk.Foo.foo_bar -> "some doc"
        # Gtk.FooBar -> "some doc"
        self._all = {}

        # Gtk.Foo.some-signal -> "some doc"
        self._signals = {}

        # Gtk.Foo.some-prop -> "some doc"
        self._properties = {}

        a, pa, r, s, pr = ns.parse_docs()
        self._all.update(a)
        self._parameters.update(pa)
        self._returns.update(r)
        self._signals.update(s)
        self._properties.update(pr)

        self._private = ns.parse_private()

        loaded = {}
        to_load = ns.get_dependencies()
        while to_load:
            key = to_load.pop()
            if key in loaded:
                continue
            sub_ns = get_namespace(*key)
            loaded[key] = sub_ns
            to_load.extend(sub_ns.get_dependencies())

        # merge all type mappings
        self._types = {}
        for sub_ns in loaded.values():
            self._types.update(sub_ns.get_types())
        self._types.update(ns.get_types())

    def lookup_attr_docs(self, name, current=None):
        """Get docs for a namespace attribute.

        e.g. 'GObject.Value'
        """

        if name in self._all:
            docs, version = self._all[name]
            return self._fix_docs(docs, version, current)
        return ""

    def lookup_return_docs(self, name, current=None):
        """Get docs for the return value by function name.

        e.g. 'GObject.Value.set_char'
        """

        if name in self._returns:
            docs, version = self._returns[name]
            return self._fix_docs(docs, version, current)
        return ""

    def lookup_parameter_docs(self, name, current=None):
        """Get docs for a function parameter by function name + parameter name.

        e.g. 'GObject.Value.set_char.v_char'
        """

        if name in self._parameters:
            docs, version = self._parameters[name]
            return self._fix_docs(docs, version, current)
        return ""

    def lookup_signal_docs(self, name, short=False, current=None):
        if name in self._signals:
            docs, version = self._signals[name]
            if short:
                parts = re.split("\.[\s$]", docs, 1, re.MULTILINE)
                if len(parts) > 1:
                    return self._fix_docs(parts[0] + ".", "", current)
                else:
                    return self._fix_docs(docs, "", current)
            else:
                docs, version = self._signals[name]
                return self._fix_docs(docs, version, current)
        return ""

    def lookup_prop_docs(self, name, current=None):
        if name in self._properties:
            docs, version = self._properties[name]
            return self._fix_docs(docs, version, current)
        return ""

    def get_dependencies(self):
        return self._ns.get_dependencies()

    def is_private(self, name):
        """is_private('Gtk.ViewportPrivate')"""

        assert "." in name

        return name in self._private

    def _fix_docs(self, d, version=None, current=None):
        rest = docstring_to_rest(self._types, current, d)
        if version:
            rest += "\n\n.. versionadded:: %s\n" % version
        return rest

    def parse_constant(self, name):
        # FIXME: broken escaping in pgi
        if name.split(".")[-1][:1].isdigit():
            return

        docs = self.lookup_attr_docs(name)

        # Add images for stock icon constants
        if name.startswith("Gtk.STOCK_"):
            docs += parse_stock_icon(name)

        # sphinx gets confused by empty docstrings
        return """
%s = %s
r'''
.. fake comment to help sphinx

%s
'''

""" % (name.split(".")[-1], name, docs)

    def parse_class(self, name, obj, add_bases=False):
        names = []

        current_rst_target = obj.__module__ + "." + obj.__name__

        if add_bases:
            mro_bases = util.merge_in_overrides(obj)

            # prefix with the module if it's an external class
            for base in mro_bases:
                base_name = base.__name__
                if base.__module__ != self.namespace and base_name != "object":
                    base_name = base.__module__ + "." + base_name
                names.append(base_name)

        if not names:
            names = ["object"]

        bases = ", ".join(names)

        docs = self.lookup_attr_docs(name, current=current_rst_target)

        return """
class %s(%s):
    r'''
%s
    '''

    __init__ = %s.__init__

""" % (name.split(".")[-1], bases, docs.encode("utf-8"), name)

    def parse_signals(self, obj):

        current_rst_target = obj.__module__ + "." + obj.__name__

        if not hasattr(obj, "signals"):
            return ""

        sigs = []
        for attr in dir(obj.signals):
            if attr.startswith("_"):
                continue

            sig = getattr(obj.signals, attr)
            sigs.append(sig)

        result = []
        for sig in sigs:
            name = sig.name
            doc_key = obj.__module__ + "." + obj.__name__ + "." + name
            desc = self.lookup_signal_docs(doc_key, current=current_rst_target)
            short_desc = self.lookup_signal_docs(
                doc_key, short=True, current=current_rst_target)
            params = ", ".join([gtype_to_rest(t) for t in sig.param_types])
            ret = gtype_to_rest(sig.return_type)

            result.append(Signal(name, params, ret, desc, short_desc))

        return result

    def parse_properties(self, obj):

        current_rst_target = obj.__module__ + "." + obj.__name__

        if not hasattr(obj, "props"):
            return []

        # get all specs owned by the class
        specs = []
        for attr in dir(obj.props):
            if attr.startswith("_"):
                continue
            spec = getattr(obj.props, attr, None)
            if not spec or spec.owner_type.pytype is not obj:
                continue
            specs.append((attr, spec))

        props = []
        for attr_name, spec in specs:
            name = spec.name
            type_desc = gtype_to_rest(spec.value_type)
            readable = spec.flags & GObject.ParamFlags.READABLE
            writable = spec.flags & GObject.ParamFlags.WRITABLE
            construct = spec.flags & GObject.ParamFlags.CONSTRUCT
            if spec.blurb is not None:
                short_desc = self._fix_docs(
                    spec.blurb, current=current_rst_target)
            else:
                short_desc = ""
            doc_name = obj.__module__ + "." + obj.__name__ + "." + name
            desc = self.lookup_prop_docs(
                doc_name, current=current_rst_target) or short_desc

            props.append(Property(name, attr_name, type_desc, readable,
                                  writable, construct, short_desc, desc))

        return props

    def parse_flags(self, name, obj):
        from gi.repository import GObject

        # the base classes themselves: reference the real ones
        if obj in (GObject.GFlags, GObject.GEnum):
            return "%s = GObject.%s" % (obj.__name__, obj.__name__)

        base = obj.__bases__[0]
        base_name = base.__module__ + "." + base.__name__

        code = """
class %s(%s):
    r'''
%s
    '''
""" % (obj.__name__, base_name, self.lookup_attr_docs(name))

        escaped = []

        values = []
        for attr_name in dir(obj):
            if attr_name.upper() != attr_name:
                continue
            attr = getattr(obj, attr_name)
            # hacky.. if there is an escaped one, ignore this one
            # and add it later with setattr
            if hasattr(obj, "_" + attr_name):
                escaped.append(attr_name)
                continue
            if not isinstance(attr, obj):
                continue
            values.append((int(attr), attr_name))

        values.sort()

        for val, n in values:
            code += "    %s = %r\n" % (n, val)
            doc_key = name + "." + n.lower()
            docs = self.lookup_attr_docs(doc_key)
            code += "    r'''\n%s\n'''\n" % docs

        name = obj.__name__
        for v in escaped:
            code += "setattr(%s, '%s', %s)\n" % (name, v, "%s._%s" % (name, v))

        return code

    def parse_function(self, name, owner, obj):
        """Returns python code for the object"""

        is_method = owner is not None

        if is_method:
            current_rst_target = owner.__module__ + "." + owner.__name__
        else:
            current_rst_target = None

        def get_sig(obj):
            doc = str(obj.__doc__)
            first_line = doc and doc.splitlines()[0] or ""
            return FuncSignature.from_string(name.split(".")[-1], first_line)

        # FIXME: "GLib.IConv."
        if name.split(".")[-1] == "":
            return

        func_name = name.split(".")[-1]
        sig = get_sig(obj)

        # no valid sig, but still a docstring, probably new function
        # or an override with a new docstring
        if not sig and obj.__doc__:
            return "%s = %s\n" % (func_name, name)

        # no docstring, try to get the signature from base classes
        if not sig and owner:
            for base in owner.__mro__[1:]:
                try:
                    base_obj = getattr(base, func_name, None)
                except NotImplementedError:
                    # function not implemented in pgi
                    continue
                sig = get_sig(base_obj)
                if sig:
                    break

        # still nothing, try making the best out of it
        if not sig:
            if not self.lookup_attr_docs(name, current=current_rst_target):
                # no gir docs, let sphinx handle it
                return "%s = %s\n" % (func_name, name)
            elif is_method:
                # INFO: this probably only happens if there is an override
                # for something pgi doesn't support. The base class
                # is missing the real one, but the gir docs are still there

                # for methods, add the docstring after
                return """
%s = %s
r'''
%s
'''
""" % (func_name, name,
       self.lookup_attr_docs(name, current=current_rst_target))
            else:
                # for toplevel functions, replace the introspected one
                # since sphinx ignores docstrings on the module level
                # and replacing __doc__ for normal functions is possible
                return """
%s = %s
%s.__doc__ = r'''
%s
'''
""" % (func_name, name, func_name,
       self.lookup_attr_docs(name, current=current_rst_target))

        # we got a valid signature here
        assert sig

        docstring = str(obj.__doc__)
        # the docstring contains additional text, propably an override
        # or internal function (GObject.Object methods for example)
        lines = docstring.splitlines()[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        user_docstring = "\n".join(lines)

        # create sphinx lists for the signature we found
        docs = sig.to_rest_listing(
            self, name, current=current_rst_target).splitlines()

        # if we have a user docstring, use it, otherwise use the gir one
        if user_docstring:
            docs.append("")
            docs.append(unindent(user_docstring))
        elif self.lookup_attr_docs(name, current=current_rst_target):
            docs.append("")
            docs.append(
                self.lookup_attr_docs(name, current=current_rst_target))

        docs = "\n".join(docs)

        # in case the function is overriden, let sphinx get the funcspec
        # but still keep around the old docstring (sphinx seems to understand
        # the string under attribute thing.. good, since we can't change
        # a docstring in py2)

        if is_method:
            # Rewrap them here so spinx knows that they static and
            # we can use that information in the autosummary extension.
            # If we wrap a classmethod in another one sphinx doesn't
            # pick up the function signature.. so only use staticmethod.
            if util.is_staticmethod(obj) or util.is_classmethod(obj):
                name = "staticmethod(%s)" % name

            return """
%s = %s
r'''
%s
'''
""" % (func_name, name, docs.encode("utf-8"))

        return """
%s = %s
%s.__doc__ = \
r'''
%s
'''
""" % (func_name, name ,name, docs.encode("utf-8"))
