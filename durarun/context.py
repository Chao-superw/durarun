"""Context object for passing state between steps."""

from __future__ import annotations

from typing import Any


class Context:
    """Holds step results and custom key-value state for a single run.

    *task* and *run_id* are set at construction time and exposed as
    read-only properties.  Step results are stored via :meth:`set` /
    :meth:`get`; arbitrary user data lives in the ``_custom`` namespace
    accessed through :meth:`set_custom` / :meth:`get_custom`.
    """

    def __init__(self, task: str = "", run_id: str = "") -> None:
        self._task = task
        self._run_id = run_id
        self._results: dict[str, Any] = {}
        self._custom: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def task(self) -> str:
        """The task description for this run."""
        return self._task

    @property
    def run_id(self) -> str:
        """The unique identifier for this run."""
        return self._run_id

    # ------------------------------------------------------------------
    # Step results
    # ------------------------------------------------------------------

    def get(self, step_name: str) -> Any:
        """Return the result of a previously completed step.

        Raises :class:`KeyError` if *step_name* has not been recorded.
        """
        try:
            return self._results[step_name]
        except KeyError:
            raise KeyError(
                f"No result found for step '{step_name}'. "
                "Ensure the step has been executed or restored from the WAL."
            ) from None

    def set(self, key: str, value: Any) -> None:
        """Store a step result (or any keyed value) in the results dict."""
        self._results[key] = value

    # ------------------------------------------------------------------
    # Custom key-value store
    # ------------------------------------------------------------------

    def get_custom(self, key: str, default: Any = None) -> Any:
        """Return a custom value, or *default* if the key is absent."""
        return self._custom.get(key, default)

    def set_custom(self, key: str, value: Any) -> None:
        """Store an arbitrary key-value pair in the custom namespace."""
        self._custom[key] = value
