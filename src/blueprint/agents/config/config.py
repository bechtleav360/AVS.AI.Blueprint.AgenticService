"""Object-oriented configuration management using Dynaconf."""

import json
import logging
import os
import re
from copy import copy
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf, Validator
from dynaconf.utils.boxing import DynaBox
from dynaconf.validator import ValidationError

from ..models.config import AIConfig, CacheConfig, EventPublishingConfig, ObservabilityConfig, PromptConfig, UsageLimits
from .custom_logging import LoggingManager

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


DEPLOYMENT_IDENTITY_KEYS = frozenset({"blueprint_group", "pod_name", "hostname"})
"""Environment values describing *where* a process runs, and therefore not configuration.

Kept unreadable through ``Config`` because C6 forbids any API reachable from agent code exposing
the deployment group, its membership or its size: an agent that can read them can be written to
depend on them, and regrouping then breaks it. Framework code that needs them reads the
environment directly (``clients/io/nats_client.py``), where no agent can follow.

The list matters most once ``envvar_prefix`` can be disabled, because Dynaconf then absorbs the
whole process environment -- ``BLUEPRINT_GROUP`` and ``POD_NAME`` included -- and this is what
keeps them out of reach.
"""


DEFAULT_ENVVAR_PREFIX = "DYNACONF"
"""The prefix an environment override carries unless the project declares another one.

Kept as Dynaconf's own default so no existing deployment changes: every ``DYNACONF_<KEY>`` in a
Helm chart or ``docker run`` keeps resolving. It is also the one spelling that is *always*
available -- Dynaconf loads ``DYNACONF_*`` in addition to any custom prefix and cannot be told
not to (``loaders/env_loader.py``), so declaring a prefix **adds** a spelling rather than
replacing this one. A custom prefix is loaded second and therefore wins for the same key.
"""

ENVVAR_PREFIX_OVERRIDE = "BLUEPRINT_ENVVAR_PREFIX"
"""Environment variable that overrides the declared ``envvar_prefix``.

The prefix cannot be overridden through Dynaconf, because it decides what Dynaconf reads: an
operator who wants to change it has to be able to say so before the tree exists. Hence a
framework-owned ``BLUEPRINT_`` variable read straight from the process environment, the same
bootstrap channel the deployment group uses.
"""

_ENVVAR_PREFIX_ALPHABET = re.compile(r"^[A-Z][A-Z0-9_]*$")
"""Uppercase only, and validated rather than repaired.

Dynaconf upper-cases the prefix before matching the environment, so a declared ``myapp`` looks
for ``MYAPP_<KEY>``: on Linux the ``myapp_<KEY>`` the author actually exported is ignored, with
nothing to debug. The prefix crosses the process boundary -- a chart, a compose file and a
``docker run`` all encode it -- so it is checked, never rewritten.

Commas are excluded too: Dynaconf reads a comma-separated prefix as a *list* of prefixes, which
is a second way to spell the same override and not something this framework needs.
"""

_ENVVAR_PREFIX_DISABLED = frozenset({"", "false", "0", "no"})
"""Spellings that mean "no prefix at all", matching :func:`blueprint.agents.utils.parse_bool`.

An environment variable carries text, so ``false`` has to mean what TOML's ``false`` means.
"""

_ENVVAR_PREFIX_IDENTITY_COLLISIONS = frozenset(key.split("_", 1)[0].upper() for key in DEPLOYMENT_IDENTITY_KEYS if "_" in key)
"""Prefixes that would smuggle a deployment-identity variable past :data:`DEPLOYMENT_IDENTITY_KEYS`.

Dynaconf strips the prefix to form the key, so ``envvar_prefix = "BLUEPRINT"`` turns
``BLUEPRINT_GROUP`` into the readable key ``group`` -- and the C6 blocklist names
``blueprint_group``, not ``group``. Derived from the blocklist rather than written out, so a new
identity variable closes its own hole.
"""


class Config:
    """A class to manage the application's configuration using dynaconf."""

    def __init__(
        self,
        settings_files: list[str] | str | None = None,
        root_path: str | None = None,
        agent_scope: str | None = None,
    ) -> None:
        """Initialize the configuration manager.

        When ``agent_scope`` is set, every key lookup performed via :meth:`get`
        and the typed helpers tries ``<agent_scope>.<key>`` first and falls back
        to ``<key>`` at root. This allows a single repo to host multiple agents
        whose settings live under ``[default.<scope>]`` namespaces in the same
        TOML files.

        Raw access via ``self.settings`` remains unscoped.

        Which environment variables count as overrides is decided here too, before the tree is
        built: see :meth:`_resolve_envvar_prefix`. The prefix is a property of the process, not
        of a namespace, so a view built by :meth:`for_namespace` shares it.
        """

        self._validation_errors: list[str] = []
        self._root_path = Path(root_path) if root_path else Path.cwd()
        self._agent_scope = agent_scope
        self._is_view = False
        self._views: dict[str, Config] = {}

        # First pass: load config to get envvar_prefix and app_environment.
        #
        # The prefix has to be known before the tree that uses it can be built, and it is declared
        # in the same files -- so this pass reads them through Dynaconf's default prefix, the one
        # spelling that is always available (see DEFAULT_ENVVAR_PREFIX).
        temp_settings = Dynaconf(
            settings_files=settings_files, environments=False, load_dotenv=False, merge_enabled=True, root_path=root_path
        )
        self._envvar_prefix = self._resolve_envvar_prefix(temp_settings)
        if self._envvar_prefix != DEFAULT_ENVVAR_PREFIX:
            # Repeat the pass through the resolved prefix. Without this, `<PREFIX>_APP_ENVIRONMENT`
            # is invisible to the only read that consumes it: the second pass would load the
            # default environment's section while every other key honoured the override, and
            # nothing would report the mismatch.
            temp_settings = Dynaconf(
                settings_files=settings_files,
                environments=False,
                load_dotenv=False,
                merge_enabled=True,
                root_path=root_path,
                envvar_prefix=self._envvar_prefix,
            )
        app_env = temp_settings.get("app_environment", "development")
        logger.info(
            "Loading configuration properties for environment: %s (environment overrides read from %s)",
            app_env,
            f"{self._envvar_prefix}_*" if self._envvar_prefix else "the whole process environment, unprefixed",
        )

        # Validators differ when scoped: app_name is per agent, app_port is not.
        #
        # A group is one process behind one HTTP server, so only one port can be bound no
        # matter how many agents share it. Requiring `<scope>.app_port` would make every
        # agent declare a value that all but one of them cannot have, so the port stays a
        # root key and is validated as one.
        if agent_scope:
            validators = [
                Validator(f"{agent_scope}.app_name", must_exist=True),
                Validator("app_port", must_exist=True, is_type_of=int, default=8000),
                Validator("app_environment", must_exist=True, default="development"),
            ]
        else:
            validators = [
                Validator("app_name", must_exist=True, default="agent_blueprint"),
                Validator("app_port", must_exist=True, is_type_of=int, default=8000),
                Validator("app_environment", must_exist=True, default="development"),
            ]

        # Second pass: load with the correct environment
        self._settings = Dynaconf(
            settings_files=settings_files,
            environments=True,
            current_env=app_env,
            load_dotenv=False,
            merge_enabled=True,
            root_path=root_path,
            envvar_prefix=self._envvar_prefix,
            validators=validators,
        )

        # Validate first. Dynaconf's lazy _setup() triggers validators on the
        # first attribute access, so this needs to run before any other access
        # to self._settings to ensure ValidationError is converted to ConfigError
        # by validate()'s exception handler.
        self.validate()

        # Replace DOT placeholders
        dot_placeholder = self._settings.get("dot_placeholder", "")
        if dot_placeholder:
            # Process the entire settings object
            processed = self._process_dynabox(self._settings, dot_placeholder, ".")
            # Update settings with processed values
            for key, value in processed.items():
                self._settings[key] = value

    @staticmethod
    def _resolve_envvar_prefix(bootstrap_settings: Any) -> str | bool:
        """Decide which prefix environment overrides must carry, before the real tree is loaded.

        Precedence, highest first: the :data:`ENVVAR_PREFIX_OVERRIDE` environment variable, the
        ``envvar_prefix`` key in the settings files, then :data:`DEFAULT_ENVVAR_PREFIX`. An
        unset prefix therefore behaves exactly as before this existed.

        Args:
            bootstrap_settings: The first-pass Dynaconf object, read through the default prefix.

        Returns:
            The prefix to hand Dynaconf, or ``False`` to read the environment unprefixed.

        Raises:
            ConfigError: if the declared value is not a usable prefix. Every rejection is a
                mistake that would otherwise be silent -- an ignored override, or an identity
                variable turned into a readable key.
        """
        raw: Any = os.environ.get(ENVVAR_PREFIX_OVERRIDE)
        source = f"environment variable {ENVVAR_PREFIX_OVERRIDE}"
        if raw is None:
            raw = bootstrap_settings.get("envvar_prefix")
            source = "key 'envvar_prefix' in the settings files"
        if raw is None:
            Config._reject_sectioned_envvar_prefix(bootstrap_settings)
            return DEFAULT_ENVVAR_PREFIX

        if isinstance(raw, bool):
            if raw:
                raise ConfigError(
                    f"envvar_prefix ({source}) is true, which names no prefix. Use a string such as "
                    f"'{DEFAULT_ENVVAR_PREFIX}', or false to read the environment with no prefix."
                )
            return False
        if not isinstance(raw, str):
            raise ConfigError(f"envvar_prefix ({source}) must be a string or false, got {raw!r}.")

        candidate = raw.strip()
        if candidate.lower() in _ENVVAR_PREFIX_DISABLED:
            return False
        if not _ENVVAR_PREFIX_ALPHABET.match(candidate):
            raise ConfigError(
                f"envvar_prefix ({source}) is {candidate!r}, which cannot be used as a prefix: it must match "
                "[A-Z][A-Z0-9_]*. Dynaconf upper-cases the prefix before matching the environment, so a "
                "lowercase prefix silently looks for the upper-cased spelling and the variable that was "
                "actually exported is never read. Declare the prefix in the case it will be exported in, or "
                "use false to read the environment with no prefix."
            )
        if candidate in _ENVVAR_PREFIX_IDENTITY_COLLISIONS:
            raise ConfigError(
                f"envvar_prefix ({source}) is {candidate!r}, which collides with deployment identity: Dynaconf "
                f"strips the prefix to form the key, so {candidate}_<NAME> would become the readable key '<name>' "
                "and bypass the C6 blocklist that keeps the deployment group and the pod out of reach of agent "
                "code. Choose another prefix."
            )
        return candidate

    @staticmethod
    def _reject_sectioned_envvar_prefix(bootstrap_settings: Any) -> None:
        """Fail if ``envvar_prefix`` was declared inside a section, where nothing can read it.

        The prefix must be a **top-level** key. The pass that resolves it runs with
        ``environments=False``, so a section such as ``[default]`` is still one opaque value to it
        and the key inside is invisible -- and it has to run that way, because the prefix is what
        decides how ``app_environment`` is read in the first place. A prefix cannot live in the
        section that its own resolution selects.

        The natural mistake is therefore to put it next to ``app_name`` under ``[default]``, where
        it would do nothing at all. That is the failure this raises for: an ignored prefix means
        every environment override is silently ignored with it.

        Raises:
            ConfigError: naming each section the key was found in.
        """

        def find(node: Any, path: str) -> list[str]:
            if not hasattr(node, "items"):
                return []
            found = []
            for key, value in node.items():
                where = f"{path}.{key}".lstrip(".").lower()
                if str(key).lower() == "envvar_prefix":
                    found.append(where)
                else:
                    found.extend(find(value, where))
            return found

        sectioned = find(bootstrap_settings.as_dict(), "")
        if sectioned:
            raise ConfigError(
                f"'envvar_prefix' is declared as {', '.join(sorted(sectioned))}, inside a section, where nothing "
                "reads it: the prefix is resolved before any environment section is selected, so it must be a "
                f"top-level key in the settings file (or set as {ENVVAR_PREFIX_OVERRIDE} in the environment). "
                "Left where it is, it names no prefix and every environment override that relies on it is ignored."
            )

    @property
    def envvar_prefix(self) -> str | bool:
        """The prefix an environment override must carry, or ``False`` when none is required.

        Read by the actuator environment endpoint and worth logging at startup: "my variable is
        ignored" is otherwise indistinguishable from "my variable is misspelled".
        """
        return self._envvar_prefix

    @property
    def settings(self) -> Any:
        """The raw, unscoped settings tree -- the deliberate escape hatch.

        Everything a component should need is on ``get`` and the typed getters, which resolve
        ``<namespace>.<key>`` before the root key. This property is what stays reachable when that
        is not enough, and **every use of it is logged**, so reaching around a namespace view is
        visible rather than merely discouraged.

        Isolation between agents is therefore *audited, not enforced*. Enforcing it would mean
        making the tree unreachable, which breaks the actuator environment endpoint and any project
        reading a key the typed getters do not model. The trade is deliberate: a hatch that leaves
        a trace beats a wall with a hole in it.

        The level distinguishes the two cases. The loader is the application's own object and owns
        the tree, so its access is DEBUG. A **namespaced view** handing out the whole tree is an
        agent reading past its own subsection, which is the case worth seeing, so that is WARNING.
        """
        if self._is_view:
            logger.warning(
                "Namespace '%s' read the raw settings tree, which is not scoped to it: it can see every other "
                "agent's configuration. Prefer get() or a typed getter, which resolve '%s.<key>' before the root key.",
                self._agent_scope,
                self._agent_scope,
            )
        else:
            logger.debug("Raw settings tree read from the root configuration")
        return self._settings

    def for_namespace(self, namespace: str) -> "Config":
        """Return a view of this configuration scoped to one agent (C5).

        The view shares this object's loaded tree -- the files are parsed once per process, not
        once per agent -- and differs only in which scope its lookups try first. So
        ``for_namespace("orders").get("model_name")`` resolves ``orders.model_name`` and falls back
        to the root ``model_name``, while infrastructure keys stay shared at the root.

        Views are cached, so a component asking twice gets the same object.

        Args:
            namespace: The agent to scope to. ``""`` returns this object unchanged, because the
                root namespace *is* the unscoped configuration.

        Raises:
            RuntimeError: if called on a view. A view is one agent's window on the configuration,
                not a factory for other agents' windows -- allowing it would hand every namespace
                an unlogged route to its neighbours' keys, which is exactly what ``settings``
                exists to make visible.
        """
        if self._is_view:
            raise RuntimeError(
                f"Namespace '{self._agent_scope}' asked its own configuration view for a view of namespace "
                f"'{namespace}'. Views are created from the application's configuration, not from another "
                "agent's view."
            )
        if not namespace:
            return self

        cached = self._views.get(namespace)
        if cached is not None:
            return cached

        view = copy(self)
        view._agent_scope = namespace
        view._is_view = True
        view._views = {}
        self._views[namespace] = view
        return view

    @property
    def agent_scope(self) -> str | None:
        """The namespace whose keys this object resolves first; ``None`` at the root."""
        return self._agent_scope

    @property
    def is_view(self) -> bool:
        """Whether this is a per-namespace view rather than the application's own configuration."""
        return self._is_view

    def get_package_root(self) -> Path:
        """Return the root path where configuration files are located."""

        return self._root_path

    def configure_logging(self) -> None:
        """Configure the root logger from ``log_level``, ``log_format`` and ``suppress_noisy_loggers``.

        **Called by the application, not by this constructor.** Configuring logging is the
        application's decision: a library that does it on import steals the root logger from
        whatever imported it, and cannot be silenced by the caller. ``AppBuilder.__init__``
        makes the call, so an existing ``main.py`` that builds an app is unaffected.

        It also has to leave the constructor for the namespace work: one ``Config`` per
        namespace means N constructions in one process, and each one re-ran this. It is
        idempotent in the sense that matters -- ``LoggingManager`` only touches the root
        logger when it has no handlers -- but it re-attached filters and logged
        "Logging configured" once per namespace, and the last namespace's level won.
        """
        log_level = self._settings.get("log_level", "INFO")
        log_format = self._settings.get("log_format", "text")
        suppress_noisy = self._settings.get("suppress_noisy_loggers", True)

        manager = LoggingManager()
        manager.configure(log_level=log_level, log_format=log_format, suppress_noisy_loggers=suppress_noisy)

    def _process_dynabox(self, box: Any, placeholder: str, replacement: str) -> Any:
        """Recursively process a DynaBox to replace placeholders in keys and convert to lowercase.
        Also attempts to parse string values as JSON if they appear to be JSON objects/arrays.
        """

        def _try_parse_json(possible_json_value: Any) -> Any:
            """Try to parse a string value as JSON, return original if not valid JSON."""
            if not isinstance(possible_json_value, str):
                return possible_json_value
            try:
                parsed = json.loads(possible_json_value)
                # Only return parsed if it's a dict or list, otherwise keep original
                return parsed if isinstance(parsed, (dict, list)) else possible_json_value
            except (json.JSONDecodeError, TypeError):
                return possible_json_value

        def _convert_keyed_list_to_dict(items: Any) -> Any:
            """Convert a list of dicts with 'key' field to a dictionary.

            Args:
                items: List of dictionaries, where each dict has a 'key' field

            Returns:
                Dictionary with keys from the 'key' field and values as the remaining dict items
            """
            if not isinstance(items, list):
                return items

            # Only convert if all items are dicts with a 'key' field
            if not all(isinstance(item, dict) and "key" in item for item in items):
                return items

            list_to_keys_result = {}
            for item in items:
                key = item.pop("key")
                list_to_keys_result[key] = item
            return list_to_keys_result

        if isinstance(box, dict) or hasattr(box, "items"):
            result = {}
            for key, value in list(box.items()):
                # Process the key - replace placeholder and convert to lowercase
                new_key = key.replace(placeholder, replacement).lower()

                # Process the value
                if isinstance(value, str):
                    # Try to parse as JSON first
                    value = _try_parse_json(value)

                # Convert lists with 'key' fields to dictionaries
                if isinstance(value, list):
                    value = _convert_keyed_list_to_dict(value)

                if isinstance(value, (dict, DynaBox)) or hasattr(value, "items"):
                    new_value = self._process_dynabox(value, placeholder, replacement)
                elif isinstance(value, list):
                    new_value = [
                        (
                            self._process_dynabox(item, placeholder, replacement)
                            if isinstance(item, (dict, DynaBox)) or hasattr(item, "items")
                            else _try_parse_json(item)
                            if isinstance(item, str)
                            else item
                        )
                        for item in value
                    ]
                else:
                    new_value = value

                # Only update if key changed to avoid unnecessary updates
                if new_key != key and hasattr(box, "pop"):
                    box.pop(key, None)  # Remove old key if it exists
                result[new_key] = new_value  # Always use the new (lowercase) key
            return result
        return box

    def _scoped_get(self, key: str, default: Any = None) -> Any:
        """Resolve a key with scope-first, root-fallback semantics.

        When ``agent_scope`` is set, tries ``<scope>.<key>`` first; if missing or
        ``None``, falls back to ``<key>`` at root. When ``agent_scope`` is None,
        behaves exactly like a plain unscoped lookup in the tree.

        ``None`` from a scoped lookup is treated as "not set" so the root
        fallback fires. Empty containers (``[]``, ``{}``, ``""``) at the scoped
        key are returned as-is — only ``None`` triggers fallback.
        """
        if self._agent_scope:
            scoped = self._settings.get(f"{self._agent_scope}.{key}")
            if scoped is not None:
                return scoped
        return self._settings.get(key, default)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, scope-aware when ``agent_scope`` is set.

        Raises:
            ValueError: for a key in :data:`DEPLOYMENT_IDENTITY_KEYS`. Raised rather than answered
                with ``None``, because ``None`` reads as "not configured" and would send the caller
                hunting for a missing setting instead of telling them the value is deliberately out
                of reach (C6). Every typed getter funnels through here, so one check covers them all.
        """
        if key.lower() in DEPLOYMENT_IDENTITY_KEYS:
            raise ValueError(
                f"'{key}' is deployment identity, not configuration, and is deliberately unreadable through "
                "Config (C6): code that can read the group or the pod can be written to depend on them, and "
                "moving the agent to another group then breaks it. Framework code reads these from the "
                "environment directly."
            )

        env_var = self._scoped_get(key, default)
        # Convert DynaBox to dict
        if isinstance(env_var, DynaBox):
            return env_var.to_dict()
        return env_var

    def get_runtime_config(self, runtime_name: str = "default") -> dict[str, Any]:
        """Get runtime-specific configuration merged with global defaults.

        Args:
            runtime_name: Name of the runtime to get config for.

        Returns:
            Merged configuration dictionary with runtime-specific overrides.
        """
        # Start with empty config
        config = {}

        # Add global defaults for common keys (using new model_* pattern)
        global_keys = [
            "model_provider",
            "model_base_url",
            "model_api_key",
            "model_max_tokens",
            "model_temperature",
            "concurrent_requests",
            "prompt_directory",
            "prompt_search_paths",
        ]

        for key in global_keys:
            value = self.get(key)
            if value is not None:
                config[key] = value

        # Try to find runtime-specific config (scope-aware)
        runtime_config = self._scoped_get(f"runtimes.{runtime_name}")
        if not runtime_config:
            runtime_config = self._scoped_get(f"runtimes.{runtime_name.upper()}")
        if not runtime_config:
            runtimes = self._scoped_get("runtimes")
            if runtimes and hasattr(runtimes, "get"):
                runtime_config = runtimes.get(runtime_name) or runtimes.get(runtime_name.upper())
        if not runtime_config:
            runtime_config = self._scoped_get(f"runtime.{runtime_name}")
        if not runtime_config:
            runtime_config = self._scoped_get(f"runtime.{runtime_name.upper()}")

        # Process runtime-specific config if found
        if runtime_config:
            # Convert uppercase keys to lowercase for consistency
            normalized_config = {}
            for key, value in runtime_config.items():
                normalized_key = key.lower() if isinstance(key, str) else key
                normalized_config[normalized_key] = value

            config.update(normalized_config)
            logger.debug(
                "Loaded runtime-specific config for '%s': %d settings",
                runtime_name,
                len(normalized_config),
            )
        else:
            logger.debug(
                "No runtime-specific config found for '%s', using global defaults",
                runtime_name,
            )
        return config

    def get_ai_config(self, runtime_name: str = "default") -> AIConfig:
        """Get AI-related configuration for a specific runtime.

        Supports both old (ai_model_*) and new (model_*) configuration patterns.
        The new pattern is preferred for runtime-specific configs.

        Args:
            runtime_name: Name of the runtime to get AI config for.

        Returns:
            AIConfig model with runtime-specific overrides.
        """

        # Get runtime-specific settings (scope-aware)
        runtime_settings = self._scoped_get(f"runtimes.{runtime_name}")
        if not runtime_settings:
            runtime_settings = {}

        # Helper to get config value with fallback from runtime-specific to global
        def get_with_fallback(key: str) -> Any:
            """Get config value, trying runtime-specific first, then global.

            Priority order:
            1. Runtime-specific (e.g., model_api_key in runtimes.evaluator)
            2. Global (e.g., model_api_key at root level)
            """
            # Try runtime-specific first
            value = runtime_settings.get(key)
            if value is not None:
                return value
            # Fall back to global
            return self.get(key)

        provider = get_with_fallback("model_provider")
        model_name = get_with_fallback("model_name")
        api_key = get_with_fallback("model_api_key")
        base_url = get_with_fallback("model_base_url")

        model_settings = self._scoped_get(f"runtimes.{runtime_name}.model_settings")
        if not model_settings:
            model_settings = {}

        # Log configuration resolution for debugging
        logger.debug(
            "AI config for runtime '%s': provider=%s, model=%s, has_api_key=%s, base_url=%s",
            runtime_name,
            provider,
            model_name,
            "yes" if api_key else "no",
            base_url,
        )

        return AIConfig(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            model_settings=model_settings,
            max_tokens=get_with_fallback("model_max_tokens"),
            temperature=get_with_fallback("model_temperature"),
            concurrency_limit=get_with_fallback("concurrent_requests"),
            usage_limits=UsageLimits(
                request_limit=get_with_fallback("usage_request_limit"),
                input_tokens_limit=get_with_fallback("usage_input_tokens_limit"),
                output_tokens_limit=get_with_fallback("usage_output_tokens_limit"),
                total_tokens_limit=get_with_fallback("usage_total_tokens_limit"),
            ),
        )

    def get_prompt_config(self, runtime_name: str | None = None) -> PromptConfig:
        """Get prompt-related configuration for a specific runtime.

        Args:
            runtime_name: Name of the runtime to get prompt config for.

        Returns:
            PromptConfig model with prompt configuration.
        """
        runtime_config = self.get_runtime_config(runtime_name or "default")

        return PromptConfig(
            custom_path=runtime_config.get("prompt_directory", self.get("prompt_directory")),
            search_paths=runtime_config.get("prompt_search_paths", self.get("prompt_search_paths", [])),
            system_prompt_name=runtime_config.get("system_prompt_name", self.get("system_prompt_name", "system")),
            instruction_prompt_name=runtime_config.get(
                "instruction_prompt_name",
                self.get("instruction_prompt_name", "instruction"),
            ),
        )

    def get_observability_config(self) -> ObservabilityConfig:
        """Get observability-related configuration."""
        return ObservabilityConfig(
            otel_enabled=self.get("otel_enabled", False),
            otel_endpoint=self.get("otel_endpoint"),
            otel_service_name=self.get("otel_service_name", self.get("app_name", "agent-service")),
            log_level=self.get("log_level", "INFO"),
        )

    def get_event_publishing_config(self) -> EventPublishingConfig:
        """Get complete event publishing configuration.

        Returns:
            EventPublishingConfig model with event publishing configuration.
        """

        logger.info(self.get("event_publishing.topic_mapping", {}))

        return EventPublishingConfig(
            default_pubsub_name=self.get("event_publishing.default_pubsub_name", "pubsub"),
            topic_mapping=self.get("event_publishing.topic_mapping", {}),
        )

    def get_nats_subscription_config(self) -> list[str]:
        """Return NATS topics to auto-subscribe to from the ``nats_subscriptions`` config key.

        Returns an empty list if the key is absent or misconfigured.

        Example settings.toml::

            nats_subscriptions = ["governance.>", "orders.created"]
        """

        raw = self.get("nats_subscriptions", [])
        if not isinstance(raw, list):
            logger.warning("nats_subscriptions must be a list; got %s — ignoring", type(raw).__name__)
            return []
        return [str(t) for t in raw if t]

    def get_cache_config(self) -> CacheConfig:
        """Get cache-related configuration.

        Returns:
            CacheConfig model with cache configuration.
        """

        return CacheConfig(
            cache_dir=self.get("cache.cache_dir", ".cache/blueprint"),
            size_limit=self.get("cache.size_limit", 1_000_000_000),
            eviction_policy=self.get("cache.eviction_policy", "least-recently-used"),
            default_ttl=self.get("cache.default_ttl", 3600),
            backend=self.get("cache.backend", "disk"),
            key_prefix=self.get("cache.key_prefix", ""),
            redis_url=self.get("cache.redis_url"),
            redis_password=self.get("cache.redis_password"),
            redis_db=self.get("cache.redis_db", 0),
            redis_tls=self.get("cache.redis_tls", False),
            fallback_to_local=self.get("cache.fallback_to_local", False),
        )

    def validate(self) -> bool:
        """Validate the configuration."""
        self._validation_errors.clear()
        try:
            self._settings.validators.validate()
            if not 1 <= self.get("app_port") <= 65535:
                raise ConfigError(f"Invalid app port: {self.get('app_port')}")

            ai_config = self.get_ai_config()
            if ai_config.provider == "vllm" and not ai_config.api_key:
                raise ConfigError("Missing API key for vLLM provider")

            return True
        except ValidationError as exc:
            # Handle Dynaconf validation errors without stack trace
            error_msg = str(exc)
            logger.error("Configuration validation failed: %s", error_msg)
            self._validation_errors.append(error_msg)
            raise ConfigError(error_msg) from None
        except ConfigError as exc:
            # Re-raise ConfigError without stack trace
            logger.error("Configuration validation failed: %s", exc)
            self._validation_errors.append(str(exc))
            raise
        except Exception as exc:
            # Catch any other unexpected errors with stack trace for debugging
            logger.error("Unexpected configuration error: %s", exc, exc_info=True)
            self._validation_errors.append(str(exc))
            raise ConfigError(str(exc)) from exc

    def has_validation_errors(self) -> bool:
        """Return True if configuration validation detected errors."""

        return bool(self._validation_errors)

    def get_validation_errors(self) -> list[str]:
        """Return collected configuration validation errors."""

        return list(self._validation_errors)
