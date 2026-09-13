"""Cross-cutting infrastructure: settings and the database engine.

Everything in here is depended on by routes, services and models alike, and
depends on none of them. That one-way relationship is what makes it "core"
rather than just another package.
"""
