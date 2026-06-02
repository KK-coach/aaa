"""Discovery Agent (AAA-17): reactive multi-tool single-URL audit."""

# AAA-31 S3a — lazy package export. Eagerly doing `from .agent import ...` here
# drags the whole audit pipeline (agent -> tools -> crawler -> playwright) into
# anything that merely touches the package, e.g.
# `from discovery_agent.output_schema import AuditOutput` (used by
# memory.firestore_archive, which the dispatcher Agent Engine bundle imports).
# PEP 562 lazy attributes keep the package import lean while preserving the
# `from discovery_agent import discovery_agent` / `root_agent` API. Consumers
# that need the agent can also import `from discovery_agent.agent import ...`
# directly (unchanged).

__all__ = ["discovery_agent", "root_agent"]


def __getattr__(name):
    if name in ("discovery_agent", "root_agent"):
        from .agent import discovery_agent, root_agent
        globals()["discovery_agent"] = discovery_agent
        globals()["root_agent"] = root_agent
        return globals()[name]
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
