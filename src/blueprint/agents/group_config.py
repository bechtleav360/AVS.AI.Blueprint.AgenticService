"""Which agents this process hosts, resolved from the deployment rather than from the image.

An agent's *code* says nothing about which other agents it runs beside: that is a deployment
decision, and the whole point of the namespace model is that changing it is invisible to the
agents (spec sec. 3). So the composition arrives at container start, from two sources that
compose, and this module is the only place that reads either of them.

Two files, with different lifetimes, and the difference is the reason there are two:

- **The agent map** (``agents.toml``) says what agents *exist* in this image and where their
  declarations live. It changes only when an agent is added or removed, which is a rebuild
  anyway, so it is baked in.
- **The group file** (``deployment-groups.yaml``) says which of them *this* process runs. It is
  never baked in -- one image serves every group -- so it arrives as a mount, or is replaced
  entirely by environment variables.

Read **before** any ``Config`` view exists, and deliberately not through Dynaconf: group
composition decides which agents get a configuration view at all, so it cannot itself come from
one. That is why these are plain environment reads plus one parse each, and why the variables
carry an explicit ``BLUEPRINT_`` prefix rather than Dynaconf's override mechanism (spec sec. 5.1).

Environment variables
~~~~~~~~~~~~~~~~~~~~~
============================== ============================ ====================================
Variable                       Default                      Meaning
============================== ============================ ====================================
``BLUEPRINT_GROUP_CONFIG``     ``./deployment-groups.yaml``  Path to the group file. An absent
                                                             file is not an error when the
                                                             environment supplies the group.
``BLUEPRINT_GROUP``            --                           Which group to load. May be omitted
                                                             when the file declares exactly one.
``BLUEPRINT_AGENTS``           --                           Comma-separated agent names, which
                                                             supply the group with no file at all.
``BLUEPRINT_CRITICAL_AGENTS``  --                           Comma-separated subset to mark
                                                             critical. See :attr:`AgentSpec.critical`.
``BLUEPRINT_AGENT_MAP``        ``./agents.toml``            Path to the agent map.
============================== ============================ ====================================

**Environment variables override the file key by key** (spec sec. 5.1), so one Deployment can
change the agent list without editing or duplicating the file. Every resolved value is logged
with the source it came from, because "which agents did this pod actually start" is the first
question asked of a group that misbehaves.
"""

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .component.namespace import validate_namespace
from .config import Config

logger = logging.getLogger(__name__)

GROUP_CONFIG_ENV = "BLUEPRINT_GROUP_CONFIG"
GROUP_ENV = "BLUEPRINT_GROUP"
AGENTS_ENV = "BLUEPRINT_AGENTS"
CRITICAL_AGENTS_ENV = "BLUEPRINT_CRITICAL_AGENTS"
AGENT_MAP_ENV = "BLUEPRINT_AGENT_MAP"

DEFAULT_GROUP_CONFIG = "deployment-groups.yaml"
DEFAULT_AGENT_MAP = "agents.toml"


class GroupConfigError(Exception):
    """A group could not be resolved, and the process must not start.

    Its own type rather than ``ValueError`` because the entry point treats it differently from
    every other failure: it is turned into a readable message and a non-zero exit *before the
    port is bound*, so Kubernetes crash-loops with something an operator can act on rather than
    reporting a healthy pod that is silently short-staffed (spec sec. 9.1).
    """


@dataclass(frozen=True)
class AgentSpec:
    """One agent this process is asked to host.

    Attributes:
        name: The agent's name, which becomes its namespace -- and with it its registry key
            prefix, queue group, durable name, cache partition and telemetry service name. Held
            to the namespace alphabet, so a group file cannot name an agent the rest of the
            system could not identify.
        module: Where the agent's ``AgentRegistration`` lives, as ``"module.path:attribute"``.
            Comes from the agent map, never from the group file: what an agent *is* belongs to
            the image, and only which agents run belongs to the deployment.
        critical: Whether this agent failing to load must stop the process. Defaults to
            ``True``, because a partially loaded group whose missing agent's queue has no
            consumer is a worse failure than no pod at all (spec sec. 9.1) -- the pod would pass
            its probes while a queue silently backed up. ``False`` is the deliberate choice to
            run the rest without it.
    """

    name: str
    module: str
    critical: bool = True


@dataclass(frozen=True)
class GroupConfig:
    """A resolved group: which agents run in this process, and under what name.

    A value object. :meth:`resolve` performs every read this module does; once constructed,
    nothing here touches the environment or the filesystem, so a test builds one literally
    rather than arranging files and variables around the code under test.

    Attributes:
        name: The group's name. Reaches the NATS connection name for attribution and the
            telemetry ``deployment.group`` resource attribute, and **nothing else** -- no
            broker-side identifier may derive from it, or moving an agent between groups would
            be visible to the broker (C1).
        agents: The agents to host, in the order the group declared them.
        cache_names: Caches to register for the process, beyond the default one. A cache is
            process-wide (spec sec. 8), so it is the group's to declare rather than any single
            agent's.
    """

    name: str
    agents: tuple[AgentSpec, ...]
    cache_names: tuple[str, ...] = field(default=())

    @property
    def agent_names(self) -> tuple[str, ...]:
        """The agent names, in declaration order."""
        return tuple(agent.name for agent in self.agents)

    @classmethod
    def resolve(cls, config: Config, *, environ: dict[str, str] | None = None) -> "GroupConfig":
        """Read the group from the environment and the group file, and validate it.

        The only member that touches the environment or the filesystem. Order of operations:

        1. Read the group file, if there is one, and take the requested group's slice.
        2. Apply environment overrides key by key -- so a Deployment can change the agent list
           without editing a mounted file.
        3. Resolve every agent name against the in-image agent map, which is what turns a typo
           into a crash-loop with a readable message instead of a pod missing one consumer.

        Args:
            config: The application's configuration, used for the project root that relative
                paths resolve against -- the same root its settings files resolved against, so
                a project whose files live outside the working directory behaves consistently.
            environ: The environment to read, for tests. Defaults to the process environment.

        Returns:
            The resolved group.

        Raises:
            GroupConfigError: if no group can be determined, if the file is unreadable or
                malformed, if a named group is absent, or if an agent is not in the agent map
                and is critical.
        """
        env = os.environ if environ is None else environ
        root = config.get_package_root()

        declared = cls._read_group_file(env, root)
        name, agent_names, critical_names, cache_names = cls._apply_env_overrides(env, declared)

        if not agent_names:
            raise GroupConfigError(
                f"No agents were resolved for this process. Either mount a group file and name the group with "
                f"'{GROUP_ENV}', or set '{AGENTS_ENV}' to a comma-separated list of agent names. Looked for a group "
                f"file at {cls._group_file_path(env, root)}."
            )

        agent_map = cls._read_agent_map(env, root)
        agents = cls._resolve_agents(agent_names, critical_names, agent_map, name)

        group = cls(name=name, agents=tuple(agents), cache_names=tuple(cache_names))
        logger.info(
            "Resolved group '%s' with %d agent(s): %s%s",
            group.name,
            len(group.agents),
            ", ".join(f"{agent.name}{'' if agent.critical else ' (non-critical)'}" for agent in group.agents),
            f"; caches: {', '.join(group.cache_names)}" if group.cache_names else "",
        )
        return group

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @staticmethod
    def _group_file_path(env: dict[str, str] | Any, root: Path) -> Path:
        """Return where the group file is looked for, whether or not it exists."""
        configured = str(env.get(GROUP_CONFIG_ENV, "") or "").strip()
        path = Path(configured) if configured else root / DEFAULT_GROUP_CONFIG
        return path if path.is_absolute() else root / path

    @classmethod
    def _read_group_file(cls, env: dict[str, str] | Any, root: Path) -> dict[str, Any]:
        """Return the requested group's slice of the group file, or an empty mapping.

        An absent file is not an error: the environment alone can supply a group, which is the
        ``docker run`` and CI shape. A file that exists and cannot be parsed *is* an error --
        somebody mounted it meaning it to be used.

        Raises:
            GroupConfigError: if the file cannot be read or parsed, if it does not declare
                ``groups``, if the named group is absent, or if it declares several groups and
                the environment names none.
        """
        requested_group = str(env.get(GROUP_ENV, "") or "").strip()
        if not requested_group and str(env.get(AGENTS_ENV, "") or "").strip():
            # The environment supplies the whole group, so the file is not consulted at all --
            # this is the `docker run` and CI shape from spec sec. 5.1. Reading it anyway would
            # make an unrelated multi-group file mounted in the image ambiguous, and there is
            # nothing to be ambiguous *about*: with no group named, no slice of that file
            # applies, and the agent list that would have come from it is already overridden.
            logger.debug("'%s' supplies the group and '%s' names none, so no group file is read", AGENTS_ENV, GROUP_ENV)
            return {}

        path = cls._group_file_path(env, root)
        if not path.is_file():
            logger.debug("No group file at %s; the group must come from the environment", path)
            return {}

        document = cls._parse_group_file(path)
        groups = document.get("groups")
        if not isinstance(groups, list) or not groups:
            raise GroupConfigError(f"Group file {path} declares no 'groups' list, so no group can be resolved from it.")

        by_name = {str(entry.get("name", "")): entry for entry in groups if isinstance(entry, dict)}
        requested = requested_group

        if not requested:
            if len(by_name) != 1:
                raise GroupConfigError(
                    f"Group file {path} declares {len(by_name)} groups ({', '.join(sorted(by_name))}) and "
                    f"'{GROUP_ENV}' is not set, so which one to run is ambiguous. Set '{GROUP_ENV}'."
                )
            only = next(iter(by_name.values()))
            logger.info("Group file %s declares one group ('%s'), so it is the one loaded", path, only.get("name"))
            return only

        if requested not in by_name:
            raise GroupConfigError(
                f"Group '{requested}' is not declared in {path} (it has: {', '.join(sorted(by_name)) or 'nothing'}). "
                f"Either the group file mounted here is the wrong one, or '{GROUP_ENV}' is misspelt."
            )
        logger.info("Loaded group '%s' from %s", requested, path)
        return by_name[requested]

    @staticmethod
    def _parse_group_file(path: Path) -> dict[str, Any]:
        """Parse the group file as YAML.

        Raises:
            GroupConfigError: if the file is unreadable or is not a YAML mapping.
        """
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise GroupConfigError(f"Group file {path} could not be read: {exc}") from exc

        if document is None:
            return {}
        if not isinstance(document, dict):
            raise GroupConfigError(f"Group file {path} must contain a mapping with a 'groups' key, got {type(document).__name__}.")
        return document

    @classmethod
    def _read_agent_map(cls, env: dict[str, str] | Any, root: Path) -> dict[str, str]:
        """Return ``{agent name: "module:attribute"}`` from the in-image agent map.

        An explicit map rather than scanning for modules by convention. Discovery by convention
        makes the set of agents in an image depend on what happens to be importable, so a
        renamed directory silently removes an agent and a stray one silently adds it; the map
        makes both a diff in a file that has to be edited on purpose.

        Raises:
            GroupConfigError: if the map is missing, unparseable, or malformed.
        """
        configured = str(env.get(AGENT_MAP_ENV, "") or "").strip()
        path = Path(configured) if configured else root / DEFAULT_AGENT_MAP
        if not path.is_absolute():
            path = root / path

        if not path.is_file():
            raise GroupConfigError(
                f"No agent map at {path}, so no agent name can be resolved to code. This file is part of the image "
                "and lists every agent it contains, as [agents.<name>] with module = 'pkg.mod:registration'. Set "
                f"'{AGENT_MAP_ENV}' if it lives elsewhere."
            )

        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise GroupConfigError(f"Agent map {path} could not be read: {exc}") from exc

        agents = document.get("agents")
        if not isinstance(agents, dict) or not agents:
            raise GroupConfigError(f"Agent map {path} declares no [agents.<name>] entries, so this image contains no agents.")

        resolved: dict[str, str] = {}
        for agent_name, entry in agents.items():
            module = entry.get("module") if isinstance(entry, dict) else None
            if not module or not isinstance(module, str):
                raise GroupConfigError(
                    f"Agent '{agent_name}' in {path} has no 'module', so its declaration cannot be found. Write it as "
                    'module = "pkg.mod:registration".'
                )
            resolved[str(agent_name)] = module
        logger.debug("Agent map %s contains %d agent(s): %s", path, len(resolved), ", ".join(sorted(resolved)))
        return resolved

    # ------------------------------------------------------------------
    # Overriding and validating
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_env_overrides(env: dict[str, str] | Any, declared: dict[str, Any]) -> tuple[str, list[str], set[str], list[str]]:
        """Overlay environment variables on the file's slice, key by key, logging each source.

        Key by key rather than all-or-nothing (spec sec. 5.1): a Deployment that wants a
        different agent list should not have to restate the group's name and caches to get it.
        The log line per value is what answers "where did this pod's agent list come from",
        which is the first question asked of a group that started with the wrong contents.
        """

        def _split(raw: str) -> list[str]:
            return [part.strip() for part in raw.split(",") if part.strip()]

        name = str(declared.get("name", "") or "").strip()
        agents = [str(agent).strip() for agent in declared.get("agents", []) or [] if str(agent).strip()]
        critical = {str(agent).strip() for agent in declared.get("critical_agents", []) or [] if str(agent).strip()}
        caches = [str(cache).strip() for cache in declared.get("cache_names", []) or [] if str(cache).strip()]
        sources = {"name": "file", "agents": "file", "critical_agents": "file", "cache_names": "file"}

        if override := str(env.get(GROUP_ENV, "") or "").strip():
            if not name:
                name, sources["name"] = override, f"${GROUP_ENV}"
        if override := str(env.get(AGENTS_ENV, "") or "").strip():
            agents, sources["agents"] = _split(override), f"${AGENTS_ENV}"
        if override := str(env.get(CRITICAL_AGENTS_ENV, "") or "").strip():
            critical, sources["critical_agents"] = set(_split(override)), f"${CRITICAL_AGENTS_ENV}"

        if not name:
            # A group has to be called something: the name reaches the connection name and the
            # telemetry resource, where an empty segment reads as a bug rather than as "no group".
            name, sources["name"] = "ungrouped", "default"

        for key, source in sources.items():
            if source != "file" or declared:
                logger.info("Group value '%s' resolved from %s", key, source)
        return name, agents, critical, caches

    @staticmethod
    def _resolve_agents(agent_names: list[str], critical_names: set[str], agent_map: dict[str, str], group_name: str) -> list[AgentSpec]:
        """Turn names into specs, refusing a name the image does not contain.

        A name absent from the map is refused **here**, before anything is built, which is the
        seam the plan asks for: a typo in a mounted group file becomes a crash-loop naming the
        group and the agent, rather than a pod that passes its probes with one queue unconsumed.

        A name marked non-critical is *skipped* instead, with an ERROR, because that flag is the
        deployment saying it would rather run the rest.

        The name is also held to the namespace alphabet, since it becomes a namespace: rejecting
        it here names the group file, while letting it through would surface as a validation
        error from inside some component's constructor.

        Raises:
            GroupConfigError: if a critical agent is not in the map, if a name is not a legal
                namespace, or if the group names the same agent twice.
        """
        specs: list[AgentSpec] = []
        seen: set[str] = set()
        for name in agent_names:
            if name in seen:
                raise GroupConfigError(
                    f"Group '{group_name}' names agent '{name}' more than once. Two agents cannot share a name -- it "
                    "is what identifies one in every log line, queue group, durable and cache partition -- and one "
                    "agent named twice is a group whose size does not match its contents."
                )
            seen.add(name)

            try:
                validate_namespace(name)
            except ValueError as exc:
                raise GroupConfigError(f"Group '{group_name}' names an agent that cannot be a namespace: {exc}") from exc

            critical = name in critical_names if critical_names else True
            module = agent_map.get(name)
            if module is None:
                if critical:
                    raise GroupConfigError(
                        f"Group '{group_name}' names agent '{name}', which this image does not contain (it has: "
                        f"{', '.join(sorted(agent_map))}). Either the agent map is out of date, or the group file "
                        f"names an agent that was removed."
                    )
                logger.error(
                    "Agent '%s' of group '%s' is not in this image's agent map and is not critical, so it is skipped",
                    name,
                    group_name,
                )
                continue
            specs.append(AgentSpec(name=name, module=module, critical=critical))
        return specs
