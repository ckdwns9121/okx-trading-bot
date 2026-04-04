import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Type

from app.core.strategy_base import BaseStrategy
from app.logging_config import get_logger

logger = get_logger(__name__)


class StrategyRegistry:
    """Central registry for trading strategies."""

    def __init__(self) -> None:
        self._registry: dict[str, Type[BaseStrategy]] = {}

    def register(self, strategy_cls: Type[BaseStrategy]) -> None:
        """Register a strategy class, validating it meets the contract."""
        if not (isinstance(strategy_cls, type) and issubclass(strategy_cls, BaseStrategy)):
            raise TypeError(f"{strategy_cls!r} must be a subclass of BaseStrategy")

        name: str = getattr(strategy_cls, "name", None)  # type: ignore[assignment]
        if not name:
            raise ValueError(f"Strategy {strategy_cls.__name__} must define a non-empty `name` class attribute")

        # Validate lookback_period by instantiating enough to check the property.
        # We inspect the class's __dict__ for a concrete descriptor rather than
        # calling the abstract method directly.
        lookback = None
        for klass in strategy_cls.__mro__:
            if "lookback_period" in klass.__dict__:
                prop = klass.__dict__["lookback_period"]
                if isinstance(prop, property):
                    # Try to read the value via a temporary instance.
                    try:
                        instance = object.__new__(strategy_cls)
                        lookback = prop.fget(instance)  # type: ignore[arg-type]
                    except Exception:
                        pass
                break

        if lookback is not None:
            if not isinstance(lookback, int) or lookback <= 0:
                raise ValueError(
                    f"Strategy {strategy_cls.__name__}.lookback_period must be a positive integer, got {lookback!r}"
                )

        if name in self._registry:
            logger.warning("strategy_overwritten", name=name, cls=strategy_cls.__name__)

        self._registry[name] = strategy_cls
        logger.info("strategy_registered", name=name, cls=strategy_cls.__name__)

    def get(self, name: str) -> Type[BaseStrategy]:
        """Retrieve a registered strategy class by name."""
        try:
            return self._registry[name]
        except KeyError:
            raise KeyError(f"No strategy registered with name={name!r}. Available: {self.list_all()}")

    def list_all(self) -> list[str]:
        """Return names of all registered strategies."""
        return sorted(self._registry.keys())


# Module-level singleton
registry = StrategyRegistry()


def auto_discover(strategies_dir: str | Path) -> None:
    """Scan *strategies_dir* for Python files and register any BaseStrategy subclasses found."""
    strategies_path = Path(strategies_dir).resolve()
    if not strategies_path.is_dir():
        raise NotADirectoryError(f"strategies_dir does not exist: {strategies_path}")

    # Ensure the parent of strategies_dir is on sys.path so imports work.
    parent = str(strategies_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for py_file in sorted(strategies_path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"{strategies_path.name}.{py_file.stem}"
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    logger.warning("auto_discover_skip_no_spec", file=str(py_file))
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]

            for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    obj is not BaseStrategy
                    and issubclass(obj, BaseStrategy)
                    and obj.__module__ == module_name
                ):
                    try:
                        registry.register(obj)
                    except (TypeError, ValueError) as exc:
                        logger.warning(
                            "auto_discover_skip_invalid",
                            cls=obj.__name__,
                            reason=str(exc),
                        )

        except Exception as exc:
            logger.error("auto_discover_import_error", file=str(py_file), error=str(exc))
