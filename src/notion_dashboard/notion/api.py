from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator
import os

from notion_client import Client


@dataclass
class Meeting:
    id: str
    title: str
    start: datetime | date | None
    end: datetime | date | None
    location: str = ""
    description: str = ""
    url: str = ""
    link: str = ""


@dataclass
class Todo:
    id: str
    title: str
    due: datetime | date | None
    status: str
    priority: str = ""
    url: str = ""


@dataclass
class Workday:
    id: str
    title: str
    start: datetime | date | None
    end: datetime | date | None
    hours: float
    url: str = ""

    @property
    def is_open(self) -> bool:
        """Clocked in but not yet out: a start time and no end."""
        return isinstance(self.start, datetime) and self.end is None

    def hours_at(self, now: datetime) -> float:
        """Hours worked, counting an open session up to `now`."""
        if self.is_open:
            return max(0.0, (now - self.start).total_seconds() / 3600)
        return self.hours


def tag_names(prop: dict[str, Any] | None) -> set[str]:
    if not prop:
        return set()
    if prop.get("type") == "multi_select":
        return {t.get("name", "").casefold() for t in prop.get("multi_select") or []}
    if prop.get("type") == "select" and prop.get("select"):
        return {prop["select"].get("name", "").casefold()}
    return set()


def formula_number(prop: dict[str, Any] | None) -> float:
    if not prop or prop.get("type") != "formula":
        return 0.0
    value = prop.get("formula") or {}
    if value.get("type") == "number" and value.get("number") is not None:
        return float(value["number"])
    return 0.0


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def todo_sort_key(item: Todo):
    priority_rank = PRIORITY_RANK.get(item.priority.strip().casefold(), len(PRIORITY_RANK))

    if item.due is None:
        due_rank = (1, date.max)
    else:
        due_date = item.due.date() if isinstance(item.due, datetime) else item.due
        due_rank = (0, due_date)

    return (priority_rank, due_rank, item.title.casefold())


def rich_text_value(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""

    typ = prop.get("type")
    value = prop.get(typ, {})

    if typ in {"title", "rich_text"}:
        return "".join(x.get("plain_text", "") for x in value or [])

    if typ == "select":
        return (value or {}).get("name", "") if value else ""

    if typ == "status":
        return (value or {}).get("name", "") if value else ""

    if typ == "multi_select":
        return ", ".join(x.get("name", "") for x in value or [])

    if typ == "people":
        return ", ".join(
            x.get("name") or x.get("person", {}).get("email", "")
            for x in value or []
        )

    if typ == "checkbox":
        return "Yes" if value else "No"

    if typ == "number":
        return "" if value is None else str(value)

    if typ == "url":
        return value or ""

    return ""


def date_value(prop: dict[str, Any] | None) -> tuple[datetime | date | None, datetime | date | None]:
    if not prop or prop.get("type") != "date":
        return None, None

    value = prop.get("date")
    if not value:
        return None, None

    start = parse_notion_datetime(value.get("start"))
    end = parse_notion_datetime(value.get("end"))

    return start, end


def parse_notion_datetime(value: str | None) -> datetime | date | None:
    if not value:
        return None

    # Date-only values are deliberately kept as date objects.
    if "T" not in value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def first_property(properties: dict[str, Any], configured: str, fallback_types: tuple[str, ...]) -> str:
    if configured in properties:
        return configured

    for name, prop in properties.items():
        if prop.get("type") in fallback_types:
            return name

    return configured


def _in_meeting_window(
    start: datetime | date,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if isinstance(start, datetime):
        aware_start = start if start.tzinfo else start.replace(tzinfo=window_start.tzinfo)
        return window_start <= aware_start <= window_end

    return window_start.date() <= start <= window_end.date()


class NotionRepository:
    def __init__(self, token: str):
        self.client = Client(auth=token)

    def search(self, query: str = "") -> list[dict[str, Any]]:
        return self.client.search(query=query).get("results", [])

    def data_source(self, data_source_id: str) -> dict[str, Any]:
        return self.client.data_sources.retrieve(data_source_id=data_source_id)

    def query_all(
        self,
        data_source_id: str,
        filter: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        cursor = None

        while True:
            kwargs: dict[str, Any] = {
                "data_source_id": data_source_id,
                "page_size": 100,
            }
            if filter:
                kwargs["filter"] = filter
            if cursor:
                kwargs["start_cursor"] = cursor

            response = self.client.data_sources.query(**kwargs)

            yield from response.get("results", [])

            if not response.get("has_more"):
                break

            cursor = response.get("next_cursor")
            if not cursor:
                break

    def get_meetings(
        self,
        data_source_id: str,
        title_property: str,
        date_property: str,
        location_property: str,
        description_property: str,
        link_property: str = "",
        tags_property: str = "",
        exclude_tag: str = "",
    ) -> list[Meeting]:
        result: list[Meeting] = []
        excluded = exclude_tag.casefold()

        now = datetime.now().astimezone()
        window_start = now - timedelta(hours=1)
        window_end = now + timedelta(days=7)

        for page in self.query_all(data_source_id):
            properties = page.get("properties", {})

            if excluded and excluded in tag_names(properties.get(tags_property)):
                continue

            title_name = first_property(properties, title_property, ("title",))
            date_name = first_property(properties, date_property, ("date",))

            start, end = date_value(properties.get(date_name))
            if start is None:
                continue

            if not _in_meeting_window(start, window_start, window_end):
                continue

            location = rich_text_value(properties.get(location_property))
            description = rich_text_value(properties.get(description_property))

            link = ""
            if link_property and link_property in properties:
                link = rich_text_value(properties.get(link_property))

            result.append(
                Meeting(
                    id=page.get("id", ""),
                    title=rich_text_value(properties.get(title_name)) or "Untitled meeting",
                    start=start,
                    end=end,
                    location=location,
                    description=description,
                    url=page.get("url", ""),
                    link=link,
                )
            )

        result.sort(key=lambda x: x.start or date.min)
        return result

    def get_todos(
        self,
        data_source_id: str,
        title_property: str,
        due_property: str,
        status_property: str,
        priority_property: str,
        completed_statuses: list[str],
    ) -> list[Todo]:
        result: list[Todo] = []
        completed = {x.casefold() for x in completed_statuses}

        for page in self.query_all(data_source_id):
            properties = page.get("properties", {})

            title_name = first_property(properties, title_property, ("title",))
            status_name = first_property(properties, status_property, ("status", "select"))
            due_name = first_property(properties, due_property, ("date",))
            priority_name = priority_property if priority_property in properties else ""

            title = rich_text_value(properties.get(title_name)) or "Untitled task"
            status = rich_text_value(properties.get(status_name))

            if status.casefold() in completed:
                continue

            due, _ = date_value(properties.get(due_name))

            # Show every open task, ordered by priority first, then due date.
            result.append(
                Todo(
                    id=page.get("id", ""),
                    title=title,
                    due=due,
                    status=status,
                    priority=rich_text_value(properties.get(priority_name)) if priority_name else "",
                    url=page.get("url", ""),
                )
            )

        result.sort(key=todo_sort_key)
        return result

    def get_workdays(
        self,
        data_source_id: str,
        tags_property: str,
        workday_tag: str,
        start_property: str,
        end_property: str,
        hours_property: str,
    ) -> list[Workday]:
        """All pages tagged as a workday, newest first.

        Hours come from the hours formula when it gives a positive number,
        otherwise from the dates: either StartDate's own start/end range or
        StartDate -> EndDate. (A page that stores its time as a range in
        StartDate with no EndDate makes the formula return 0.)
        """

        schema_type = self.data_source(data_source_id)["properties"].get(tags_property, {}).get("type")
        query_filter = None
        if schema_type in ("multi_select", "select"):
            operator = "contains" if schema_type == "multi_select" else "equals"
            query_filter = {"property": tags_property, schema_type: {operator: workday_tag}}

        result: list[Workday] = []
        wanted = workday_tag.casefold()

        for page in self.query_all(data_source_id, filter=query_filter):
            properties = page.get("properties", {})
            if wanted not in tag_names(properties.get(tags_property)):
                continue

            start, range_end = date_value(properties.get(start_property))
            end, _ = date_value(properties.get(end_property))
            end = end or range_end

            hours = formula_number(properties.get(hours_property))
            if hours <= 0 and isinstance(start, datetime) and isinstance(end, datetime):
                hours = max(0.0, (end - start).total_seconds() / 3600)

            result.append(
                Workday(
                    id=page.get("id", ""),
                    title=rich_text_value(properties.get(first_property(properties, "", ("title",)))),
                    start=start,
                    end=end,
                    hours=hours,
                    url=page.get("url", ""),
                )
            )

        def sort_key(item: Workday):
            value = item.start
            if isinstance(value, datetime):
                return value.date()
            return value or date.min

        result.sort(key=sort_key, reverse=True)
        return result

    def clock_in(
        self,
        data_source_id: str,
        tags_property: str,
        workday_tag: str,
        start_property: str,
        when: datetime,
    ) -> Workday:
        page = self.client.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties={
                tags_property: {"multi_select": [{"name": workday_tag}]},
                start_property: {"date": {"start": when.isoformat()}},
            },
        )
        return Workday(
            id=page.get("id", ""),
            title="",
            start=when,
            end=None,
            hours=0.0,
            url=page.get("url", ""),
        )

    def clock_out(
        self,
        workday: Workday,
        start_property: str,
        end_property: str,
        when: datetime,
    ) -> None:
        """Close an open workday: set the end property, or, if there is no
        separate end property, turn the start date into a start-end range."""

        if end_property:
            properties = {end_property: {"date": {"start": when.isoformat()}}}
        else:
            properties = {
                start_property: {"date": {"start": workday.start.isoformat(), "end": when.isoformat()}}
            }
        self.client.pages.update(page_id=workday.id, properties=properties)

    def set_todo_status(self, page_id: str, status_property: str, status_value: str) -> None:
        page = self.client.pages.retrieve(page_id=page_id)
        prop_type = page.get("properties", {}).get(status_property, {}).get("type", "status")

        payload = {prop_type: {"name": status_value}}
        self.client.pages.update(page_id=page_id, properties={status_property: payload})

    def create_todo(
        self,
        data_source_id: str,
        title_property: str,
        due_property: str,
        priority_property: str,
        title: str,
        due: date | None = None,
        priority: str = "",
    ) -> Todo:
        schema = self.data_source(data_source_id).get("properties", {})

        title_name = first_property(schema, title_property, ("title",))
        due_name = first_property(schema, due_property, ("date",))
        priority_name = priority_property if priority_property in schema else ""

        properties: dict[str, Any] = {
            title_name: {"title": [{"text": {"content": title}}]},
        }

        if due is not None:
            properties[due_name] = {"date": {"start": due.isoformat()}}

        if priority and priority_name:
            priority_type = schema.get(priority_name, {}).get("type", "select")
            properties[priority_name] = {priority_type: {"name": priority}}

        page = self.client.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=properties,
        )

        return Todo(
            id=page.get("id", ""),
            title=title,
            due=due,
            status="",
            priority=priority,
            url=page.get("url", ""),
        )

    def create_meeting(
        self,
        data_source_id: str,
        title_property: str,
        date_property: str,
        location_property: str,
        title: str,
        start: datetime,
        end: datetime | None = None,
        location: str = "",
        link_property: str = "",
        link: str = "",
    ) -> Meeting:
        schema = self.data_source(data_source_id).get("properties", {})

        title_name = first_property(schema, title_property, ("title",))
        date_name = first_property(schema, date_property, ("date",))

        date_payload: dict[str, Any] = {"start": start.isoformat()}
        if end is not None:
            date_payload["end"] = end.isoformat()

        properties: dict[str, Any] = {
            title_name: {"title": [{"text": {"content": title}}]},
            date_name: {"date": date_payload},
        }

        if location and location_property in schema:
            properties[location_property] = {"rich_text": [{"text": {"content": location}}]}

        if link and link_property in schema:
            if schema[link_property].get("type") == "url":
                properties[link_property] = {"url": link}
            else:
                properties[link_property] = {"rich_text": [{"text": {"content": link}}]}

        page = self.client.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=properties,
        )

        return Meeting(
            id=page.get("id", ""),
            title=title,
            start=start,
            end=end,
            location=location,
            url=page.get("url", ""),
            link=link,
        )

    def get_page_content(self, page_id: str) -> str:
        """Read a page's body back out as plain text, one line per block.

        Only handles paragraph-shaped text (the block types plain-text
        notes actually produce); other block types are skipped rather than
        guessed at. Bulleted list items come back as "- " lines, the same
        way set_page_content() writes them.
        """

        lines: list[str] = []

        for block in self._list_children(page_id):
            block_type = block.get("type", "")
            rich_text = block.get(block_type, {}).get("rich_text")
            if rich_text is None:
                continue

            prefix = "- " if block_type == "bulleted_list_item" else ""
            lines.append(prefix + "".join(t.get("plain_text", "") for t in rich_text))

        return "\n".join(lines)

    def set_page_content(self, page_id: str, text: str) -> None:
        """Replace a page's body with plain-text paragraphs, one per line.
        Lines starting with "- " become bulleted list items."""

        for block in self._list_children(page_id):
            self.client.blocks.delete(block_id=block["id"])

        def to_block(line: str) -> dict[str, Any]:
            block_type = "paragraph"
            if line.startswith("- "):
                block_type, line = "bulleted_list_item", line[2:]
            rich_text = [{"type": "text", "text": {"content": line}}] if line else []
            return {"object": "block", "type": block_type, block_type: {"rich_text": rich_text}}

        children = [to_block(line) for line in text.split("\n")] if text.strip() else []

        # The API caps a single append at 100 children.
        for i in range(0, len(children), 100):
            self.client.blocks.children.append(
                block_id=page_id,
                children=children[i : i + 100],
            )

    def _list_children(self, block_id: str) -> Iterator[dict[str, Any]]:
        cursor = None

        while True:
            kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor

            response = self.client.blocks.children.list(**kwargs)
            yield from response.get("results", [])

            if not response.get("has_more"):
                break

            cursor = response.get("next_cursor")
            if not cursor:
                break
