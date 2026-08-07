# -*- coding: utf-8 -*-
"""Reverse final A2UI NDJSON to Design Compact DSL and verify roundtrips.

The reverse converter intentionally reads the frozen forward converter's private
protocol tables.  Keeping the two files together makes the token vocabulary and
normalization rules a single versioned unit instead of duplicating those rules.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Package import.
    from . import compact_dsl_a2ui_converter as forward
except ImportError:  # Direct script execution.
    import compact_dsl_a2ui_converter as forward


_MESSAGE_KINDS = ("createSurface", "updateComponents", "updateDataModel")
_BINDING_RE = re.compile(r"^\{\{ \$\{(/[^{}]+)\} \}\}$", re.DOTALL)
_EXPRESSION_BINDING_RE = re.compile(r"^\{\{ (.+) \}\}$", re.DOTALL)
_GENERATED_TEXT_DEFAULTS = {"maxLines": 1, "textOverflow": "ellipsis"}
_GENERATED_ICON_STYLES = {
    "width": 16,
    "height": 16,
    "objectFit": "contain",
    "flexShrink": 0,
}


class A2uiReverseConversionError(ValueError):
    """Raised when final A2UI is invalid or outside the reversible subset."""


@dataclass(frozen=True)
class ParsedA2ui:
    """Validated three-message A2UI document."""

    version: str
    surface_id: str
    create_surface: dict[str, Any]
    update_components: dict[str, Any]
    update_data_model: dict[str, Any]
    components_by_id: dict[str, dict[str, Any]]
    component_order: tuple[str, ...]


@dataclass(frozen=True)
class RoundtripResult:
    """Artifacts produced by one successful reverse/forward execution."""

    compact_dsl: str
    roundtrip_a2ui: str
    report: dict[str, Any]


def convert_a2ui_to_compact_dsl(
    a2ui: str,
    *,
    size: str | None = None,
    collapse_design_tokens: bool = True,
    collapse_color_tokens: bool = False,
    collapse_action_units: bool = True,
) -> str:
    """Convert one final A2UI document into deterministic Compact DSL.

    ``size`` may be omitted only when the Surface dimensions select exactly one
    forward-converter size.  The current 2x4 and 4x2 dimensions are identical,
    so callers must disambiguate those two sizes explicitly.
    """

    parsed = parse_a2ui(a2ui)
    resolved_size = _resolve_size(parsed, size)
    rows = _reverse_component_rows(
        parsed,
        resolved_size,
        collapse_design_tokens=collapse_design_tokens,
        collapse_color_tokens=collapse_color_tokens,
        collapse_action_units=collapse_action_units,
    )
    rows.append(["/", copy.deepcopy(parsed.update_data_model["value"])])
    compact_dsl = _serialize_rows(rows)
    _validate_compact_output(compact_dsl, resolved_size)
    return compact_dsl


def reverse_and_verify(
    a2ui: str,
    *,
    size: str | None = None,
    protocol_profile: dict[str, Any] | None = None,
    task_spec: dict[str, Any] | None = None,
    card_spec: dict[str, Any] | None = None,
    case_id: str | None = None,
    collapse_design_tokens: bool = True,
    collapse_color_tokens: bool = False,
    collapse_action_units: bool = True,
) -> RoundtripResult:
    """Reverse, validate, forward-convert, and compare one A2UI document."""

    parsed = parse_a2ui(a2ui)
    resolved_size = _resolve_size(parsed, size)
    compact_dsl = convert_a2ui_to_compact_dsl(
        a2ui,
        size=resolved_size,
        collapse_design_tokens=collapse_design_tokens,
        collapse_color_tokens=collapse_color_tokens,
        collapse_action_units=collapse_action_units,
    )

    context_status = "not_run"
    warnings: list[str] = []
    if task_spec is not None or card_spec is not None:
        if task_spec is None or card_spec is None:
            raise A2uiReverseConversionError(
                "TaskSpec and CardSpec must be supplied together for context validation."
            )
        validation = forward.validate_compact_dsl_context(
            compact_dsl,
            task_spec=task_spec,
            card_spec=card_spec,
        )
        context_status = "pass"
        warnings.extend(validation.warnings)

    profile = _roundtrip_profile(parsed, protocol_profile)
    roundtrip_a2ui = forward.convert_compact_dsl_to_a2ui(
        compact_dsl,
        size=resolved_size,
        protocol_profile=profile,
        surface_id=parsed.surface_id,
    )
    source_value = _canonical_a2ui(parsed)
    roundtrip_value = _canonical_a2ui(parse_a2ui(roundtrip_a2ui))
    differences: list[dict[str, Any]] = []
    _collect_differences(source_value, roundtrip_value, "$", differences)

    report = {
        "caseId": case_id,
        "size": resolved_size,
        "reverse": "pass",
        "compactValidation": "pass",
        "contextValidation": context_status,
        "forward": "pass",
        "roundtrip": "pass" if not differences else "fail",
        "differences": differences,
        "warnings": warnings,
        "sourceSha256": _sha256_text(a2ui),
        "compactSha256": _sha256_text(compact_dsl),
        "roundtripSha256": _sha256_text(roundtrip_a2ui),
    }
    return RoundtripResult(compact_dsl, roundtrip_a2ui, report)


def parse_a2ui(a2ui: str) -> ParsedA2ui:
    """Parse and strictly validate the forward converter's A2UI envelope."""

    body = _strip_optional_genui_fence(a2ui)
    messages: dict[str, dict[str, Any]] = {}
    versions: list[str] = []
    for line_number, raw_line in enumerate(body.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise A2uiReverseConversionError(
                f"A2UI line {line_number} is invalid JSON: {exc.msg}."
            ) from exc
        if not isinstance(message, dict):
            raise A2uiReverseConversionError(
                f"A2UI line {line_number} must contain a JSON object."
            )
        unknown_keys = set(message) - {"version", *_MESSAGE_KINDS}
        if unknown_keys:
            raise A2uiReverseConversionError(
                f"A2UI line {line_number} has unsupported fields: "
                f"{_names(unknown_keys)}."
            )
        kinds = [kind for kind in _MESSAGE_KINDS if kind in message]
        if len(kinds) != 1 or set(message) != {"version", *kinds}:
            raise A2uiReverseConversionError(
                f"A2UI line {line_number} must contain version and one message payload."
            )
        version = message["version"]
        if not isinstance(version, str) or not version:
            raise A2uiReverseConversionError("A2UI version must be a non-empty string.")
        kind = kinds[0]
        if kind in messages:
            raise A2uiReverseConversionError(f"Duplicate A2UI {kind} message.")
        payload = message[kind]
        if not isinstance(payload, dict):
            raise A2uiReverseConversionError(f"A2UI {kind} payload must be an object.")
        messages[kind] = copy.deepcopy(payload)
        versions.append(version)

    if set(messages) != set(_MESSAGE_KINDS):
        missing = set(_MESSAGE_KINDS) - set(messages)
        raise A2uiReverseConversionError(
            f"A2UI must contain exactly three messages; missing: {_names(missing)}."
        )
    if len(set(versions)) != 1:
        raise A2uiReverseConversionError("All A2UI messages must use the same version.")

    create = messages["createSurface"]
    update = messages["updateComponents"]
    data = messages["updateDataModel"]
    _require_create_surface_fields(create)
    _require_exact_fields(
        update,
        {"surfaceId", "root", "components"},
        "updateComponents",
    )
    _require_exact_fields(
        data,
        {"surfaceId", "path", "value"},
        "updateDataModel",
    )

    surface_ids = [create["surfaceId"], update["surfaceId"], data["surfaceId"]]
    if any(not isinstance(value, str) or not value for value in surface_ids):
        raise A2uiReverseConversionError("surfaceId must be a non-empty string.")
    if len(set(surface_ids)) != 1:
        raise A2uiReverseConversionError("All A2UI messages must target one surfaceId.")
    if create["catalogId"] != forward._A2UI_FORM_CATALOG_ID:
        raise A2uiReverseConversionError(
            f'Unsupported A2UI catalogId "{create["catalogId"]}".'
        )
    for name in ("width", "height"):
        if name not in create:
            continue
        value = create[name]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise A2uiReverseConversionError(f"createSurface.{name} must be positive integer.")
    if data["path"] != "/":
        raise A2uiReverseConversionError('updateDataModel.path must be "/".')
    if not isinstance(data["value"], dict):
        raise A2uiReverseConversionError("updateDataModel.value must be an object.")

    components_by_id = _parse_components(update["components"])
    order = _validate_component_tree(update["root"], components_by_id)
    return ParsedA2ui(
        version=versions[0],
        surface_id=surface_ids[0],
        create_surface=create,
        update_components=update,
        update_data_model=data,
        components_by_id=components_by_id,
        component_order=order,
    )


def _strip_optional_genui_fence(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise A2uiReverseConversionError("A2UI input is empty.")
    lines = value.strip().splitlines()
    if not lines[0].strip().startswith("```"):
        if any(line.strip().startswith("```") for line in lines):
            raise A2uiReverseConversionError("A2UI contains a malformed code fence.")
        return value
    if lines[0].strip().lower() not in {"```", "```genui", "```jsonl", "```json"}:
        raise A2uiReverseConversionError("Unsupported A2UI code fence language.")
    if len(lines) < 2 or lines[-1].strip() != "```":
        raise A2uiReverseConversionError("A2UI code fence is not closed.")
    inner = lines[1:-1]
    if any(line.strip().startswith("```") for line in inner):
        raise A2uiReverseConversionError("A2UI contains nested code fences.")
    return "\n".join(inner)


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], context: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {_names(missing)}")
        if unknown:
            details.append(f"unsupported {_names(unknown)}")
        raise A2uiReverseConversionError(f"{context} fields are invalid: {'; '.join(details)}.")


def _require_create_surface_fields(value: Mapping[str, Any]) -> None:
    required = {"surfaceId", "catalogId"}
    allowed = {*required, "width", "height"}
    missing = required - set(value)
    unknown = set(value) - allowed
    has_width = "width" in value
    has_height = "height" in value
    if missing or unknown or has_width != has_height:
        details = []
        if missing:
            details.append(f"missing {_names(missing)}")
        if unknown:
            details.append(f"unsupported {_names(unknown)}")
        if has_width != has_height:
            details.append("width and height must appear together")
        raise A2uiReverseConversionError(
            f"createSurface fields are invalid: {'; '.join(details)}."
        )


def _parse_components(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise A2uiReverseConversionError("updateComponents.components must be non-empty array.")
    components: dict[str, dict[str, Any]] = {}
    for index, component in enumerate(value):
        context = f"component[{index}]"
        if not isinstance(component, dict):
            raise A2uiReverseConversionError(f"{context} must be an object.")
        component_id = component.get("id")
        component_type = component.get("component")
        if not isinstance(component_id, str) or not component_id:
            raise A2uiReverseConversionError(f"{context}.id must be non-empty string.")
        if component_id in components:
            raise A2uiReverseConversionError(f'Duplicate A2UI component id "{component_id}".')
        if component_type not in forward._COMPONENT_TYPES - {"ActionUnit"}:
            raise A2uiReverseConversionError(
                f'{component_id}: unsupported A2UI component "{component_type}".'
            )
        allowed = {"id", "component", "children", "styles", "onClick"}
        allowed.update(forward._SEMANTIC_FIELDS.get(component_type, frozenset()))
        if component_type in {"Row", "Column"}:
            allowed.add("itemMargin")
        if component_type == "List":
            allowed.add("space")
        unknown = set(component) - allowed
        if unknown:
            raise A2uiReverseConversionError(
                f"{component_id}: unsupported A2UI fields: {_names(unknown)}."
            )
        children = component.get("children", [])
        if not isinstance(children, list) or any(
            not isinstance(child, str) or not child for child in children
        ):
            raise A2uiReverseConversionError(
                f"{component_id}: children must be an array of non-empty strings."
            )
        if len(children) != len(set(children)):
            raise A2uiReverseConversionError(f"{component_id}: children contains duplicates.")
        styles = component.get("styles", {})
        if not isinstance(styles, dict):
            raise A2uiReverseConversionError(f"{component_id}: styles must be an object.")
        allowed_styles = set(forward._COMMON_STYLE_PROPERTIES)
        allowed_styles.update(
            forward._COMPONENT_STYLE_PROPERTIES.get(component_type, frozenset())
        )
        # These properties are legal Compact props but are emitted outside styles.
        allowed_styles.discard("itemMargin")
        allowed_styles.discard("space")
        unsupported_styles = set(styles) - allowed_styles
        if unsupported_styles:
            raise A2uiReverseConversionError(
                f"{component_id}: unsupported A2UI styles: {_names(unsupported_styles)}."
            )
        if component_type in forward._CONTAINER_TYPES and "children" not in component:
            raise A2uiReverseConversionError(
                f"{component_id}: container must contain the children field."
            )
        if component_type not in forward._CONTAINER_TYPES and not children:
            if "children" in component:
                raise A2uiReverseConversionError(
                    f"{component_id}: empty children is not emitted for a leaf component."
                )
        if component_type not in {*forward._CONTAINER_TYPES, "Button"} and children:
            raise A2uiReverseConversionError(
                f"{component_id}: {component_type} cannot contain children."
            )
        if "onClick" in component:
            on_click = component["onClick"]
            if not isinstance(on_click, list) or not on_click or any(
                not isinstance(handler, dict) for handler in on_click
            ):
                raise A2uiReverseConversionError(
                    f"{component_id}: onClick must be a non-empty array of objects."
                )
        components[component_id] = copy.deepcopy(component)
    return components


def _validate_component_tree(
    root_id: Any,
    components: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    if root_id != "root":
        raise A2uiReverseConversionError('updateComponents.root must be "root".')
    root = components.get("root")
    if root is None or root.get("component") != "Column":
        raise A2uiReverseConversionError("The root Column component is missing.")
    parent_by_child: dict[str, str] = {}
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(component_id: str) -> None:
        if component_id in visiting:
            raise A2uiReverseConversionError(f"Component tree contains cycle at {component_id}.")
        if component_id in visited:
            raise A2uiReverseConversionError(f"Component {component_id} has multiple parents.")
        component = components.get(component_id)
        if component is None:
            raise A2uiReverseConversionError(f"Missing child component {component_id}.")
        visiting.add(component_id)
        order.append(component_id)
        for child_id in component.get("children", []):
            existing = parent_by_child.get(child_id)
            if existing is not None:
                raise A2uiReverseConversionError(
                    f"Component {child_id} is referenced by both {existing} and {component_id}."
                )
            parent_by_child[child_id] = component_id
            visit(child_id)
        visiting.remove(component_id)
        visited.add(component_id)

    visit("root")
    unreachable = set(components) - visited
    if unreachable:
        raise A2uiReverseConversionError(
            f"A2UI contains unreachable components: {_names(unreachable)}."
        )
    return tuple(order)


def _resolve_size(parsed: ParsedA2ui, requested: str | None) -> str:
    supported = tuple(forward._COMPACT_ROOT_DIMENSIONS)
    if requested is not None:
        if requested not in supported:
            raise A2uiReverseConversionError(f'Unsupported Form size "{requested}".')
        _validate_surface_dimensions(parsed, requested)
        return requested
    if "width" not in parsed.create_surface:
        raise A2uiReverseConversionError(
            "Surface has no dimensions; pass size explicitly or provide it via TaskSpec."
        )
    width = parsed.create_surface["width"]
    height = parsed.create_surface["height"]
    matches = [
        name
        for name in supported
        if forward._surface_dimensions(name, {}) == {"width": width, "height": height}
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise A2uiReverseConversionError(
            f"Surface {width}x{height} does not match a supported Form size."
        )
    raise A2uiReverseConversionError(
        f"Surface {width}x{height} is ambiguous ({', '.join(matches)}); pass size explicitly."
    )


def _validate_surface_dimensions(parsed: ParsedA2ui, size: str) -> None:
    if "width" not in parsed.create_surface:
        return
    expected = forward._surface_dimensions(size, {})
    actual = {
        "width": parsed.create_surface["width"],
        "height": parsed.create_surface["height"],
    }
    if actual != expected:
        raise A2uiReverseConversionError(
            f"Surface dimensions {actual['width']}x{actual['height']} do not match "
            f"size {size} ({expected['width']}x{expected['height']})."
        )


def _reverse_component_rows(
    parsed: ParsedA2ui,
    size: str,
    *,
    collapse_design_tokens: bool,
    collapse_color_tokens: bool,
    collapse_action_units: bool,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    skipped: set[str] = set()
    for component_id in parsed.component_order:
        if component_id in skipped:
            continue
        component = parsed.components_by_id[component_id]
        if collapse_action_units:
            icon_action = _match_icon_round_action_unit(component, parsed.components_by_id)
            if icon_action is not None:
                props, icon_id = icon_action
                rows.append([component_id, "ActionUnit", props])
                skipped.add(icon_id)
                continue
            capsule_action = _match_capsule_action_unit(component)
            if capsule_action is not None:
                rows.append([component_id, "ActionUnit", capsule_action])
                continue
        row = _reverse_regular_component(
            component,
            size,
            collapse_design_tokens=collapse_design_tokens,
            collapse_color_tokens=collapse_color_tokens,
        )
        rows.append(row)
    return rows


def _match_icon_round_action_unit(
    component: dict[str, Any],
    components: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str] | None:
    component_id = component["id"]
    icon_id = f"{component_id}_icon"
    if set(component) != {"id", "component", "children", "onClick", "styles"}:
        return None
    if component["component"] != "Stack" or component["children"] != [icon_id]:
        return None
    expected_styles = forward._resolved_design_styles(
        component_id, forward._BUTTON_DESIGNS["icon-round"]
    )
    forward._normalize_icon_button_stack(expected_styles)
    if component["styles"] != expected_styles:
        return None
    icon = components.get(icon_id)
    if icon is None or set(icon) != {"id", "component", "src", "styles"}:
        return None
    if icon["component"] != "Image" or icon["styles"] != _GENERATED_ICON_STYLES:
        return None
    source = icon["src"]
    if not isinstance(source, str) or not source.startswith("resources/base/media/"):
        return None
    return (
        {
            "state": "icon-round",
            "icon": source,
            "onClick": _reverse_bindings(component["onClick"], component_id),
        },
        icon_id,
    )


def _match_capsule_action_unit(component: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"id", "component", "label", "onClick", "styles", "enabled"}
    if set(component) - allowed:
        return None
    required = {"id", "component", "label", "onClick", "styles"}
    if not required.issubset(component) or component["component"] != "Button":
        return None
    label = component["label"]
    if not isinstance(label, str) or not label.strip():
        return None
    styles = component["styles"]
    expected = forward._resolved_design_styles(
        component["id"], forward._BUTTON_DESIGNS["capsule"]
    )
    if not isinstance(styles, dict) or set(styles) != set(expected):
        return None
    if any(
        styles[name] != value
        for name, value in expected.items()
        if name != "fontColor"
    ):
        return None
    props: dict[str, Any] = {
        "state": "capsule",
        "label": label,
        "onClick": _reverse_bindings(component["onClick"], component["id"]),
    }
    if styles.get("fontColor") != expected.get("fontColor"):
        props["actionInk"] = copy.deepcopy(styles["fontColor"])
    if "enabled" in component:
        props["enabled"] = _reverse_bindings(component["enabled"], component["id"])
    return props


def _reverse_regular_component(
    component: dict[str, Any],
    size: str,
    *,
    collapse_design_tokens: bool,
    collapse_color_tokens: bool,
) -> list[Any]:
    component_id = component["id"]
    component_type = component["component"]
    props: dict[str, Any] = {}
    semantic = forward._SEMANTIC_FIELDS.get(component_type, frozenset())
    for name in semantic:
        if name in component:
            props[name] = _reverse_bindings(component[name], component_id)
    if "onClick" in component:
        props["onClick"] = _reverse_bindings(component["onClick"], component_id)
    if component_type in {"Row", "Column"} and "itemMargin" in component:
        props["itemMargin"] = _reverse_bindings(component["itemMargin"], component_id)
    if component_type == "List" and "space" in component:
        props["space"] = _reverse_bindings(component["space"], component_id)
    for name, value in component.get("styles", {}).items():
        if name in props:
            raise A2uiReverseConversionError(
                f"{component_id}: property {name} appears both as field and style."
            )
        props[name] = _reverse_bindings(value, component_id)

    if component_id == "root":
        _reverse_root_defaults(props, size)
    if component_type == "Text":
        _reverse_text_defaults(props, component_id)
    if collapse_design_tokens:
        _collapse_design(component_type, component_id, props)
    if collapse_color_tokens:
        props = _collapse_colors(props)

    row: list[Any] = [component_id, component_type, props]
    children = component.get("children", [])
    if component_type in forward._CONTAINER_TYPES or children:
        row.append(list(children))
    return row


def _reverse_root_defaults(props: dict[str, Any], size: str) -> None:
    for name in ("width", "height"):
        if props.get(name) != "matchParent":
            raise A2uiReverseConversionError(
                f"root: generated styles.{name} must be matchParent."
            )
        props.pop(name)
    dimensions = forward._COMPACT_ROOT_DIMENSIONS[size]
    props["width"] = dimensions["width"]
    props["height"] = dimensions["height"]
    if not any(
        name in props for name in ("linearGradient", "backgroundColor", "backgroundImage")
    ):
        raise A2uiReverseConversionError(
            "root: forward conversion always emits a background; source has none."
        )
    if size != "2x2":
        return
    generated = {
        "padding": 12,
        "borderRadius": 20,
        "clip": True,
        "itemMargin": 8,
    }
    for name, expected in generated.items():
        if props.get(name) != expected:
            raise A2uiReverseConversionError(
                f"root: generated {name} must equal {expected!r}."
            )
        props.pop(name)
    if props.get("justifyContent") == "spaceBetween":
        props.pop("justifyContent")


def _reverse_text_defaults(props: dict[str, Any], component_id: str) -> None:
    for name, expected in _GENERATED_TEXT_DEFAULTS.items():
        if props.get(name) != expected:
            raise A2uiReverseConversionError(
                f"{component_id}: generated Text.{name} must equal {expected!r}."
            )
        props.pop(name)


def _collapse_design(
    component_type: str,
    component_id: str,
    props: dict[str, Any],
) -> None:
    designs = forward._COMPONENT_DESIGNS.get(component_type)
    if not designs:
        return
    for design_name, design_props in designs.items():
        resolved = forward._resolved_design_styles(component_id, design_props)
        if all(name in props and props[name] == value for name, value in resolved.items()):
            for name in resolved:
                props.pop(name)
            props["design"] = design_name
            return


def _collapse_colors(value: Any, property_name: str | None = None) -> Any:
    reverse_tokens: dict[str, str] = {}
    for token, color in forward._COLOR_TOKENS.items():
        reverse_tokens.setdefault(color, token)
    if isinstance(value, dict):
        return {
            key: _collapse_colors(child, key)
            for key, child in value.items()
        }
    if isinstance(value, list):
        if property_name == "colors":
            collapsed = []
            for stop in value:
                if isinstance(stop, list) and len(stop) == 2:
                    collapsed.append([reverse_tokens.get(stop[0], stop[0]), stop[1]])
                else:
                    collapsed.append(copy.deepcopy(stop))
            return collapsed
        return [_collapse_colors(child, property_name) for child in value]
    if property_name in forward._COLOR_PROPERTIES and isinstance(value, str):
        return reverse_tokens.get(value, value)
    return copy.deepcopy(value)


def _reverse_bindings(value: Any, context: str) -> Any:
    if isinstance(value, str):
        match = _BINDING_RE.fullmatch(value)
        if match is not None:
            path = match.group(1)
            try:
                forward._decode_json_pointer(path)
            except forward.CompactDslConversionError as exc:
                raise A2uiReverseConversionError(
                    f"{context}: invalid A2UI binding path {path}."
                ) from exc
            return {"path": path}
        expression_match = _EXPRESSION_BINDING_RE.fullmatch(value)
        if expression_match is not None:
            binding = {"expression": expression_match.group(1)}
            try:
                forward._expression_binding_paths(binding, context)
            except forward.CompactDslConversionError as exc:
                raise A2uiReverseConversionError(
                    f"{context}: unsupported A2UI binding expression {value!r}: {exc}"
                ) from exc
            return binding
        if "{{" in value or "$__dataModel" in value or "$item" in value:
            raise A2uiReverseConversionError(
                f"{context}: unsupported A2UI binding expression {value!r}."
            )
        return value
    if isinstance(value, dict):
        return {key: _reverse_bindings(child, context) for key, child in value.items()}
    if isinstance(value, list):
        return [_reverse_bindings(child, context) for child in value]
    return copy.deepcopy(value)


def _validate_compact_output(compact_dsl: str, size: str) -> None:
    try:
        rows = forward._parse_compact_rows(compact_dsl)
        components, _ = forward._validate_component_tree(rows)
        forward._validate_compact_root_dimensions(components[0], size)
        normalized = [forward._normalize_component(component) for component in components]
        data_rows = [row for row in rows if isinstance(row, forward.DataRow)]
        data_model = forward._build_data_model(data_rows)
        forward._validate_binding_paths(normalized, data_model)
    except forward.CompactDslConversionError as exc:
        raise A2uiReverseConversionError(
            f"Generated Compact DSL does not satisfy the frozen converter: {exc}"
        ) from exc


def _roundtrip_profile(
    parsed: ParsedA2ui,
    supplied: dict[str, Any] | None,
) -> dict[str, Any]:
    if supplied is not None and not isinstance(supplied, dict):
        raise A2uiReverseConversionError("protocol_profile must be an object.")
    profile = copy.deepcopy(supplied or {})
    supplied_version = profile.get("version")
    if supplied_version is not None and str(supplied_version) != parsed.version:
        raise A2uiReverseConversionError(
            "Protocol profile version does not match source A2UI version."
        )
    profile["version"] = parsed.version
    return profile


def _canonical_a2ui(parsed: ParsedA2ui) -> dict[str, Any]:
    update = copy.deepcopy(parsed.update_components)
    update["components"] = [
        copy.deepcopy(parsed.components_by_id[component_id])
        for component_id in parsed.component_order
    ]
    return {
        "version": parsed.version,
        "createSurface": copy.deepcopy(parsed.create_surface),
        "updateComponents": update,
        "updateDataModel": copy.deepcopy(parsed.update_data_model),
    }


def _collect_differences(
    source: Any,
    roundtrip: Any,
    path: str,
    differences: list[dict[str, Any]],
    *,
    limit: int = 200,
) -> None:
    if len(differences) >= limit:
        return
    if isinstance(source, dict) and isinstance(roundtrip, dict):
        for key in sorted(set(source) | set(roundtrip)):
            child_path = f"{path}.{key}"
            if key not in source:
                differences.append(
                    {"path": child_path, "kind": "added", "roundtrip": roundtrip[key]}
                )
            elif key not in roundtrip:
                differences.append(
                    {"path": child_path, "kind": "removed", "source": source[key]}
                )
            else:
                _collect_differences(
                    source[key], roundtrip[key], child_path, differences, limit=limit
                )
        return
    if isinstance(source, list) and isinstance(roundtrip, list):
        for index in range(max(len(source), len(roundtrip))):
            child_path = f"{path}[{index}]"
            if index >= len(source):
                differences.append(
                    {"path": child_path, "kind": "added", "roundtrip": roundtrip[index]}
                )
            elif index >= len(roundtrip):
                differences.append(
                    {"path": child_path, "kind": "removed", "source": source[index]}
                )
            else:
                _collect_differences(
                    source[index], roundtrip[index], child_path, differences, limit=limit
                )
        return
    if source != roundtrip:
        differences.append(
            {"path": path, "kind": "changed", "source": source, "roundtrip": roundtrip}
        )


def _serialize_rows(rows: list[list[Any]]) -> str:
    return "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for row in rows
    )


def _names(values: set[str] | Sequence[str]) -> str:
    return ", ".join(sorted(values)) or "none"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json_object(path: str | None, label: str) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise A2uiReverseConversionError(f"{label} must contain a JSON object.")
    return value


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_text(path: str | None, value: str) -> None:
    if path is None:
        return
    output = value.rstrip("\n") + "\n"
    if path == "-":
        sys.stdout.write(output)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")


def _extract_size(
    explicit: str | None,
    task_spec: dict[str, Any] | None,
    card_spec: dict[str, Any] | None,
) -> str | None:
    if explicit is not None:
        return explicit
    candidates: list[str] = []
    for document in (card_spec, task_spec):
        if document is None:
            continue
        for key in ("suggestSize", "size"):
            value = document.get(key)
            if isinstance(value, str):
                candidates.append(value)
        nested = document.get("cardSpec")
        if isinstance(nested, dict):
            value = nested.get("suggestSize") or nested.get("size")
            if isinstance(value, str):
                candidates.append(value)
    unique = list(dict.fromkeys(candidates))
    if len(unique) > 1:
        raise A2uiReverseConversionError(
            f"TaskSpec/CardSpec contain conflicting sizes: {', '.join(unique)}."
        )
    return unique[0] if unique else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reverse final A2UI to Compact DSL and verify a forward roundtrip."
    )
    parser.add_argument("--source-a2ui", required=True, help="A2UI file, or - for stdin.")
    parser.add_argument("--size", choices=tuple(forward._COMPACT_ROOT_DIMENSIONS))
    parser.add_argument("--task-spec")
    parser.add_argument("--card-spec")
    parser.add_argument("--protocol-profile")
    parser.add_argument("--case-id")
    parser.add_argument("--compact-out", default="-")
    parser.add_argument("--roundtrip-out")
    parser.add_argument("--report-out")
    parser.add_argument(
        "--collapse-color-tokens",
        action="store_true",
        help="Replace known Hex colors with deterministic semantic color tokens.",
    )
    parser.add_argument(
        "--no-design-tokens",
        action="store_true",
        help="Keep all design styles explicit.",
    )
    parser.add_argument(
        "--no-action-units",
        action="store_true",
        help="Do not collapse strict generated action structures to ActionUnit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report: dict[str, Any] | None = None
    try:
        source = _read_text(args.source_a2ui)
        task_spec = _read_json_object(args.task_spec, "TaskSpec")
        card_spec = _read_json_object(args.card_spec, "CardSpec")
        if card_spec is None and isinstance(task_spec, dict):
            nested = task_spec.get("cardSpec")
            if isinstance(nested, dict):
                card_spec = nested
        size = _extract_size(args.size, task_spec, card_spec)
        result = reverse_and_verify(
            source,
            size=size,
            protocol_profile=_read_json_object(
                args.protocol_profile, "protocol profile"
            ),
            task_spec=task_spec if card_spec is not None else None,
            card_spec=card_spec,
            case_id=args.case_id,
            collapse_design_tokens=not args.no_design_tokens,
            collapse_color_tokens=args.collapse_color_tokens,
            collapse_action_units=not args.no_action_units,
        )
        report = result.report
        _write_text(args.compact_out, result.compact_dsl)
        _write_text(args.roundtrip_out, result.roundtrip_a2ui)
        if args.report_out:
            _write_text(
                args.report_out,
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            )
        if report["roundtrip"] != "pass":
            print("roundtrip verification failed", file=sys.stderr)
            return 1
        return 0
    except (
        A2uiReverseConversionError,
        forward.CompactDslConversionError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        report = {
            "caseId": args.case_id,
            "reverse": "fail",
            "compactValidation": "not_run",
            "contextValidation": "not_run",
            "forward": "not_run",
            "roundtrip": "fail",
            "differences": [],
            "errors": [str(exc)],
        }
        if args.report_out:
            try:
                _write_text(
                    args.report_out,
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                )
            except OSError:
                pass
        print(f"reverse conversion failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
