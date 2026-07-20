"""A library of reusable migration **mechanisms** ([[plugins#plugin-blocks]]).

Generic, parameterized transforms with no version and no field set of their own -- the reusable *how* that
more than one plugin's migration builds on. A plugin's own migration supplies the frozen specifics (which
fields, which key, at which version) and calls in; nothing here is hardcoded to a version or a plugin, so
the mechanism stays a library while every historical fact stays frozen in the migration that owns it.
"""
