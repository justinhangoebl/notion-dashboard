"""Notion side of the first-start setup: list what the integration can see,
create a fresh PhD dashboard page with its databases, or work out the
config for databases the user already has.

No Qt in here - setup_wizard.py calls these from a worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_client import APIResponseError, Client


DEFAULT_COMPLETED_STATUSES = ["Done", "Completed", "Cancelled"]

DEFAULT_APP = {
    "refresh_minutes": 5,
    "max_todos": 12,
    "max_meetings": 10,
    "open_notion_on_start": True,
    "start_minimized": False,
    "window_width": 520,
    "window_height": 760,
}

# Property names used for databases this app creates. They match the
# defaults in README.md, so an existing workspace built by hand the same
# way is detected by name too.
CALENDAR_PROPS = {
    "title": "Name",
    "start": "StartDate",
    "end": "EndDate",
    "location": "Location",
    "description": "Description",
    "link": "Link",
    "tags": "Tags",
    "hours": "WorkHours",
}
TODO_PROPS = {
    "title": "Name",
    "due": "Due",
    "status": "Status",
    "priority": "Priority",
}
WORKDAY_TAG = "Workday"

WORK_HOURS_FORMULA = (
    'if(empty(prop("EndDate")), 0, '
    'round(dateBetween(prop("EndDate"), prop("StartDate"), "minutes") / 6) / 10)'
)


@dataclass
class NotionItem:
    id: str
    title: str
    url: str = ""


@dataclass
class Workspace:
    pages: list[NotionItem]
    data_sources: list[NotionItem]
    bot_name: str = ""


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, APIResponseError):
        if exc.code == "unauthorized":
            return "Notion rejected the token. Check that you copied the whole integration secret."
        if exc.code == "restricted_resource":
            return "The integration is missing a capability. Enable Read, Update and Insert content."
        if exc.code == "object_not_found":
            return "The integration has no access to that page. Add it under ••• → Connections."
        return f"Notion: {exc}"
    return str(exc) or exc.__class__.__name__


def _plain(rich_text: list[dict[str, Any]] | None) -> str:
    return "".join(x.get("plain_text", "") for x in rich_text or [])


def _page_title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title"))
    return ""


def _search_all(client: Client, object_type: str, limit: int = 500) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor = None

    while len(results) < limit:
        kwargs: dict[str, Any] = {
            "filter": {"property": "object", "value": object_type},
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor

        response = client.search(**kwargs)
        results.extend(response.get("results", []))

        cursor = response.get("next_cursor")
        if not response.get("has_more") or not cursor:
            break

    return results


def load_workspace(token: str) -> Workspace:
    """Checks the token and lists the pages and databases shared with it."""

    client = Client(auth=token)
    me = client.users.me()

    pages = [
        NotionItem(page["id"], _page_title(page) or "Untitled", page.get("url", ""))
        for page in _search_all(client, "page")
        # Rows of a database are pages too, but not useful as a parent.
        if page.get("parent", {}).get("type") in ("page_id", "workspace", "block_id")
        and not page.get("in_trash") and not page.get("archived")
    ]
    data_sources = [
        NotionItem(ds["id"], _plain(ds.get("title")) or "Untitled", ds.get("url", ""))
        for ds in _search_all(client, "data_source")
        if not ds.get("in_trash") and not ds.get("archived")
    ]

    pages.sort(key=lambda x: x.title.casefold())
    data_sources.sort(key=lambda x: x.title.casefold())
    return Workspace(pages, data_sources, me.get("name") or "")


# ---------------------------------------------------------------------------
# Create a new dashboard
# ---------------------------------------------------------------------------


def _title(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


def _options(*names_colors: tuple[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "color": color} for name, color in names_colors]


def create_workspace(token: str, parent_page_id: str, name: str) -> dict:
    """Creates `name` under the parent page with an inline Calendar and TODO
    database, and returns the notion/calendar/todo config sections."""

    client = Client(auth=token)
    c, t = CALENDAR_PROPS, TODO_PROPS

    page = client.pages.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        icon={"type": "emoji", "emoji": "🎓"},
        properties={"title": {"title": _title(name)}},
    )

    calendar_db = client.databases.create(
        parent={"type": "page_id", "page_id": page["id"]},
        title=_title("Calendar"),
        icon={"type": "emoji", "emoji": "📅"},
        is_inline=True,
        initial_data_source={
            "properties": {
                c["title"]: {"title": {}},
                c["start"]: {"date": {}},
                c["end"]: {"date": {}},
                c["location"]: {"rich_text": {}},
                c["description"]: {"rich_text": {}},
                c["link"]: {"url": {}},
                c["tags"]: {"multi_select": {"options": _options((WORKDAY_TAG, "green"), ("Meeting", "blue"))}},
            }
        },
    )
    calendar_id = calendar_db["data_sources"][0]["id"]

    # A formula can only reference properties that already exist, so it is
    # added afterwards. Without it the dashboard works out the hours from
    # the start and end dates, so a failure here isn't fatal.
    hours_property = c["hours"]
    try:
        client.data_sources.update(
            data_source_id=calendar_id,
            properties={hours_property: {"formula": {"expression": WORK_HOURS_FORMULA}}},
        )
    except APIResponseError:
        hours_property = ""

    # Select rather than status: the API can't set up a status property's
    # options, and the dashboard handles both.
    todo_db = client.databases.create(
        parent={"type": "page_id", "page_id": page["id"]},
        title=_title("TODOs"),
        icon={"type": "emoji", "emoji": "✅"},
        is_inline=True,
        initial_data_source={
            "properties": {
                t["title"]: {"title": {}},
                t["due"]: {"date": {}},
                t["status"]: {
                    "select": {"options": _options(("To do", "gray"), ("In progress", "blue"), ("Done", "green"))}
                },
                t["priority"]: {
                    "select": {"options": _options(("High", "red"), ("Medium", "yellow"), ("Low", "gray"))}
                },
            }
        },
    )
    todo_id = todo_db["data_sources"][0]["id"]

    return {
        "notion": {
            "phd_page_url": page.get("url", ""),
            "calendar_data_source_id": calendar_id,
            "todo_data_source_id": todo_id,
        },
        "calendar": {
            "title_property": c["title"],
            "date_property": c["start"],
            "end_property": c["end"],
            "location_property": c["location"],
            "description_property": c["description"],
            "link_property": c["link"],
            "tags_property": c["tags"],
            "workday_tag": WORKDAY_TAG,
            "hours_property": hours_property,
        },
        "todo": {
            "title_property": t["title"],
            "due_property": t["due"],
            "status_property": t["status"],
            "priority_property": t["priority"],
            "completed_statuses": ["Done"],
        },
    }


# ---------------------------------------------------------------------------
# Use existing databases
# ---------------------------------------------------------------------------


def _find(props: dict[str, Any], preferred: str, types: set[str], skip: set[str] = frozenset()) -> str:
    """The preferred name if it exists with a fitting type, else the first
    property of that type, else ''."""

    if props.get(preferred, {}).get("type") in types:
        return preferred
    for name, prop in props.items():
        if prop.get("type") in types and name not in skip:
            return name
    return ""


def _completed_statuses(prop: dict[str, Any]) -> list[str]:
    """Done-like options of a status or select property. The first entry is
    what clicking a TODO sets, so it has to be a real option."""

    if prop.get("type") == "status":
        status = prop.get("status", {})
        names = {o["id"]: o["name"] for o in status.get("options", [])}
        for group in status.get("groups", []):
            if group.get("name", "").casefold() == "complete":
                found = [names[i] for i in group.get("option_ids", []) if i in names]
                if found:
                    return found

    options = [o.get("name", "") for o in (prop.get(prop.get("type", ""), {}) or {}).get("options", [])]
    wanted = {x.casefold() for x in DEFAULT_COMPLETED_STATUSES}
    found = [name for name in options if name.casefold() in wanted]
    return found or list(DEFAULT_COMPLETED_STATUSES)


def config_for_existing(token: str, calendar_id: str, todo_id: str, page_url: str = "") -> dict:
    """Detects property names in existing databases and returns the
    notion/calendar/todo config sections."""

    client = Client(auth=token)
    cal = client.data_sources.retrieve(data_source_id=calendar_id).get("properties", {})
    todo = client.data_sources.retrieve(data_source_id=todo_id).get("properties", {})
    c, t = CALENDAR_PROPS, TODO_PROPS

    start = _find(cal, c["start"], {"date"})
    end = _find(cal, c["end"], {"date"}, skip={start}) if c["end"] in cal else ""
    tags = _find(cal, c["tags"], {"multi_select", "select"})
    tag_options = [
        o.get("name", "") for o in (cal.get(tags, {}).get(cal.get(tags, {}).get("type", ""), {}) or {}).get("options", [])
    ]
    workday_tag = next((o for o in tag_options if o.casefold() == WORKDAY_TAG.casefold()), WORKDAY_TAG if tags else "")

    status = _find(todo, t["status"], {"status", "select"})

    return {
        "notion": {
            "phd_page_url": page_url,
            "calendar_data_source_id": calendar_id,
            "todo_data_source_id": todo_id,
        },
        "calendar": {
            "title_property": _find(cal, c["title"], {"title"}) or c["title"],
            "date_property": start or c["start"],
            "end_property": end,
            # Matched by name only: guessing "the first text property" picks
            # e.g. a Link column as the location.
            "location_property": c["location"] if c["location"] in cal else "",
            "description_property": c["description"] if c["description"] in cal else "",
            "link_property": _find(cal, c["link"], {"url"}) or (c["link"] if c["link"] in cal else ""),
            "tags_property": tags,
            "workday_tag": workday_tag,
            "hours_property": _find(cal, c["hours"], {"formula", "number"}) if c["hours"] in cal else "",
        },
        "todo": {
            "title_property": _find(todo, t["title"], {"title"}) or t["title"],
            "due_property": _find(todo, t["due"], {"date"}) or t["due"],
            "status_property": status or t["status"],
            "priority_property": _find(todo, t["priority"], {"select"}, skip={status}) if t["priority"] in todo else "",
            "completed_statuses": _completed_statuses(todo.get(status, {})),
        },
    }


def merge_config(old: dict, notion_sections: dict) -> dict:
    """New notion/calendar/todo sections on top of the old config, keeping
    app, hotkeys and voice settings."""

    config = dict(old or {})
    config.update(notion_sections)
    config["app"] = {**DEFAULT_APP, **(config.get("app") or {})}
    return config
