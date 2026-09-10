"""Assembling one process out of several agents' declarations.

This module holds what an :class:`~blueprint.agents.app_builder.AppBuilder` deliberately does
not: the knowledge that several agents can share a process, and the rules a group imposes on
each of them.

**An ``AppBuilder`` does not know it can be collected.** It records what one agent is made of
and, asked to, builds that agent alone. Collection happens here, in a class the builder has
never heard of, which is what keeps the standalone shape free of the group's constraints --
*standalone is permissive; the group refuses what it cannot honour*. Every refusal therefore
lives in this file rather than being scattered into the builder, where it would punish the
single-agent case for a situation it is not in.

Three things happen here and nowhere else:

- **Resolution** -- which agents this process runs, and where their declarations live.
  :meth:`AgentGroup.resolve` performs the I/O; :meth:`AgentGroup.from_config` performs only the
  imports, so a test can state an exact composition without touching the environment.
- **Refusal** -- the group's rules, applied at assembly, each message naming the agent and the
  fix (spec sec. 4.2).
- **Replay** -- every agent's recorded declarations re-issued onto one root builder, inside that
  agent's namespace, and built once.
"""

import importlib
import logging
from collections.abc import Mapping

from fastapi import FastAPI

from .app_builder import AppBuilder
from .component.namespace import namespace_scope, validate_namespace
from .config import Config
from .group_config import AgentSpec, GroupConfig, GroupConfigError

logger = logging.getLogger(__name__)


class AgentGroup:
    """The agents one process hosts, and the single application they become.

    Constructed from named, **unbuilt** ``AppBuilder`` declarations::

        group = AgentGroup("finance", {"orders": orders_builder, "billing": billing_builder})
        app = group.assemble(config)

    or resolved from the deployment::

        app = AgentGroup.resolve(config).assemble(config)

    A group of one is an ordinary group: nothing about it is special, and it is how an agent
    gets a process to itself while still being deployed by the group mechanism.
    """

    def __init__(self, name: str, agents: Mapping[str, AppBuilder]) -> None:
        """Declare a group.

        Args:
            name: The deployment group's name, for logging. Not a namespace: it names the
                process, and C6 keeps it out of reach of agent code.
            agents: The agents to host, keyed by the name each one runs under. The key becomes
                the agent's namespace, and with it its registry key prefix, queue group,
                durable name, cache partition and telemetry service name. A mapping rather
                than a list because two agents cannot share a name, and a mapping says so
                structurally instead of needing a check.

        Raises:
            ValueError: if an agent's name is not a legal namespace, or is the root.
        """
        self._name = name
        self._agents: dict[str, AppBuilder] = {}
        for agent_name, builder in agents.items():
            namespace = validate_namespace(agent_name)
            if not namespace:
                raise ValueError(
                    "An agent in a group cannot be named '': that is the root namespace, which is where a "
                    "standalone application's components live and where the framework's own root components go. "
                    "Give the agent the name it is deployed under."
                )
            self._agents[namespace] = builder

    @property
    def name(self) -> str:
        """The deployment group's name."""
        return self._name

    @property
    def agents(self) -> Mapping[str, AppBuilder]:
        """The agents this group hosts, keyed by namespace, in declaration order."""
        return dict(self._agents)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, config: Config, *, environ: dict[str, str] | None = None) -> "AgentGroup":
        """Work out which agents this process runs, and load their declarations.

        The one entry point here that reaches outside the process: ``GroupConfig.resolve``
        reads the environment and the group file. Separated from :meth:`from_config` for that
        reason -- a test that wants an exact composition uses the half that performs no I/O.

        Args:
            config: The application's configuration.
            environ: The environment to resolve from, for tests.

        Returns:
            The group this process is asked to host.

        Raises:
            GroupConfigError: if the group cannot be resolved, or a critical agent cannot be
                loaded.
        """
        return cls.from_config(GroupConfig.resolve(config, environ=environ))

    @classmethod
    def from_config(cls, group: GroupConfig) -> "AgentGroup":
        """Import each agent named by ``group``, and return the group they form.

        **Reads no environment and no files.** Importing an agent's module is the one thing
        here that reaches outside, and it is driven entirely by the ``module`` strings the
        group carries -- so a test points them at test modules and controls neither the
        environment nor the filesystem to do it. Imports happen per group, so cold start is
        proportional to the number of agents this process actually hosts rather than to the
        number the image contains.

        A critical agent that cannot be loaded raises, which the entry point turns into a
        non-zero exit before the port is bound. A non-critical one is skipped with an ERROR:
        that flag is the deployment saying it would rather run the rest (spec sec. 9.1). The
        flag is read *before* the agent is wired rather than after an exception, because there
        is no partial build to unwind -- one process, one ``assemble()``.

        Args:
            group: The resolved group.

        Returns:
            The group, with every loadable agent's declaration in hand.

        Raises:
            GroupConfigError: if a critical agent's module or declaration cannot be loaded.
        """
        logger.info("Resolving group '%s': %d agent(s)", group.name, len(group.agents))

        agents: dict[str, AppBuilder] = {}
        for spec in group.agents:
            builder = cls._load_declaration(spec)
            if builder is None:
                continue
            agents[spec.name] = builder

        return cls(group.name, agents)

    @staticmethod
    def _load_declaration(spec: AgentSpec) -> AppBuilder | None:
        """Import an agent's declaration, or report why it could not be loaded.

        Returns:
            The agent's unbuilt ``AppBuilder``, or ``None`` when a non-critical agent could not
            be loaded and is to be skipped.

        Raises:
            GroupConfigError: if a critical agent cannot be loaded. The message names the agent
                and the module path it came from, because the two are declared in different
                files -- the agent name in the group file or an environment variable, the
                module in the image's agent map -- and which of them is wrong is the first
                thing to establish.
        """
        module_path, _, attribute = spec.module.partition(":")
        if not module_path or not attribute:
            return AgentGroup._skip_or_raise(
                spec,
                f"'{spec.module}' is not a valid declaration path. Write it as 'package.module:attribute', naming the "
                "AppBuilder the module assigns.",
            )

        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            # Every exception, not only ImportError: importing a module runs it, so anything its
            # top level does can fail here, and an agent whose declaration raises on import is
            # exactly as unloadable as one whose module is absent.
            return AgentGroup._skip_or_raise(spec, f"importing '{module_path}' raised {type(exc).__name__}: {exc}", exc)

        declaration = getattr(module, attribute, None)
        if declaration is None:
            return AgentGroup._skip_or_raise(
                spec, f"module '{module_path}' has no attribute '{attribute}', so its declaration cannot be read."
            )
        if not isinstance(declaration, AppBuilder):
            return AgentGroup._skip_or_raise(
                spec,
                f"'{spec.module}' is a {type(declaration).__name__}, not an AppBuilder. An agent's declaration is the "
                "builder its components are declared on, handed over without build() having been called.",
            )
        logger.debug("Loaded the declaration for agent '%s' from '%s'", spec.name, spec.module)
        return declaration

    @staticmethod
    def _skip_or_raise(spec: AgentSpec, reason: str, cause: BaseException | None = None) -> None:
        """Raise for a critical agent, or log and skip a non-critical one.

        Raises:
            GroupConfigError: when ``spec`` is critical.
        """
        if spec.critical:
            raise GroupConfigError(f"Agent '{spec.name}' could not be loaded and is critical: {reason}") from cause
        logger.error("Agent '%s' could not be loaded and is not critical, so it is skipped: %s", spec.name, reason)
        return None

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def assemble(self, config: Config) -> FastAPI:
        """Build one application out of every agent's declarations.

        One root builder, one ``build()``, one FastAPI application -- because a group *is* one
        process. Each agent's recorded calls are re-issued onto that builder inside
        :func:`namespace_scope`, so every component it creates reads the agent's name from the
        ambient scope and no component, and no ``main.py``, ever mentions a namespace.

        The refusals run before anything is replayed, so a group that cannot be honoured fails
        without half-populating a registry.

        Args:
            config: The process's configuration. One tree for the whole group -- which is why
                an agent that brought its own is refused below.

        Returns:
            The application.

        Raises:
            ValueError: if an agent's declaration is one a group cannot honour. See
                :meth:`_refuse_what_a_group_cannot_honour`.
        """
        logger.info("Assembling group '%s': %s", self._name, ", ".join(self._agents) or "no agents")

        for namespace, builder in self._agents.items():
            self._refuse_what_a_group_cannot_honour(namespace, builder)

        root = AppBuilder(config)
        for namespace, builder in self._agents.items():
            # Recorded before anything is replayed, so that an agent declaring no component is
            # still an agent this process hosts: build() wires one transport per hosted agent
            # and asks each one's own configuration whether it publishes, and neither of those
            # can be derived from a declaration list that may be empty.
            root.host_agent(namespace)
            with namespace_scope(namespace):
                for declaration in builder.declarations:
                    declaration.replay(root)

        return root.build()

    @staticmethod
    def _refuse_what_a_group_cannot_honour(namespace: str, builder: AppBuilder) -> None:
        """Refuse a declaration a group cannot place, naming the agent and the fix.

        These are the rules of spec sec. 4.2's table, and they live here rather than in
        ``AppBuilder`` because they are the *group's* rules: everything refused below works
        perfectly well in a standalone application, and will go on working, because sec. 10
        makes that shape supported indefinitely.

        Args:
            namespace: The agent being checked, for the message.
            builder: Its declaration.

        Raises:
            ValueError: if the builder has already been built, carries its own configuration,
                or declares an already-constructed component.

        Note:
            The already-built check comes first on purpose: ``build()`` adopts whatever
            configuration it resolved, so a built builder always reports one too, and the
            configuration message would otherwise be the only one anybody ever saw.
        """
        if builder.is_built:
            raise ValueError(
                f"Agent '{namespace}' has already been built, so its components exist and belong to the root "
                "namespace: a component's namespace and registry key are fixed at construction, and build() also "
                "injects the configuration process-wide, which can happen once. Hand the group the builder before "
                "build() is called, and let the group build it."
            )

        if builder.has_config:
            raise ValueError(
                f"Agent '{namespace}' was declared as AppBuilder(config), and a group cannot honour that: one "
                "process has one settings tree, one logging configuration and one HTTP port, and the group supplies "
                "all three. Declare it as AppBuilder() with no argument -- a declaration, not an application -- and "
                "the group hands each agent its own scoped view of the process's configuration when it builds it."
            )

        for declaration in builder.declarations:
            if not declaration.is_built:
                continue
            raise ValueError(
                f"{type(declaration.target).__name__} was passed to with_{declaration.kind}() as an instance by "
                f"agent '{namespace}', and a group cannot place it: it was constructed at that line, before the "
                "group existed, so its namespace and its registry key are already the root's -- and two agents "
                f"declaring one would collide on that key. Pass the class -- with_{declaration.kind}("
                f"{type(declaration.target).__name__}, ...) with its constructor arguments as keyword arguments -- "
                "or a callable returning it, so the group builds it inside this agent's namespace."
            )
