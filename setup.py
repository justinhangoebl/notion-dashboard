from __future__ import annotations

import getpass
import os
from pathlib import Path

import yaml
from dotenv import set_key
from notion_client import Client


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.yaml"


TYPE_CONV = {
    "date": "DATE",
    "checkbox": "CHECKBOX",
    "number": "NUMBER",
    "url": "URL"
}

def text(prop: dict) -> str:
    type = prop.get("type")
    value = prop.get(type)

    if type in {"title", "rich_text"}:
        return "".join(x.get("plain_text", "") for x in value or [])

    if type in {"select", "status"}:
        return (value or {}).get("name", "") if value else ""

    return TYPE_CONV.get(type, type or "UNKNOWN")


def main():
    print("=" * 70)
    print("Notion Dashboard setup")
    print("=" * 70)

    token = os.getenv("NOTION_TOKEN", "").strip()

    if not token:
        token = getpass.getpass("Notion integration token: ").strip()

    if not token:
        raise SystemExit("No token supplied.")

    set_key(str(ENV_PATH), "NOTION_TOKEN", token)

    notion = Client(auth=token)

    print("\nSearching your Notion workspace...")
    results = notion.search(page_size=100).get("results", [])

    data_sources = [
        item
        for item in results
        if item.get("object") in {"data_source", "database"}
    ]

    if not data_sources:
        print(
            "\nNo databases/data sources were found.\n"
            "Make sure your integration has been connected to your Notion page."
        )
        return

    print("\nAvailable databases/data sources:\n")

    for i, item in enumerate(data_sources, 1):
        title = "Untitled"

        if item.get("object") == "data_source":
            title = "".join(
                x.get("plain_text", "")
                for x in item.get("title", [])
            ) or "Untitled"

            item_id = item.get("id")
            print(f"[{i}] {title}")
            print(f"    ID: {item_id}")

        else:
            title = "".join(
                x.get("plain_text", "")
                for x in item.get("title", [])
            ) or "Untitled"

            item_id = item.get("id")
            print(f"[{i}] {title}")
            print(f"    ID: {item_id}")

        try:
            props = item.get("properties", {})
            if not props and item.get("object") == "data_source":
                props = notion.data_sources.retrieve(
                    data_source_id=item["id"]
                ).get("properties", {})

            for name, prop in props.items():
                print(f"       - {name!r}: {text(prop)}")
        except Exception as exc:
            print(f"       (Could not read properties: {exc})")

        print()

    def choose(prompt: str) -> str:
        while True:
            raw = input(prompt).strip()

            try:
                index = int(raw) - 1
                if 0 <= index < len(data_sources):
                    return data_sources[index]["id"]
            except ValueError:
                pass

            # Also allow direct IDs.
            if raw:
                return raw

            print("Enter a list number or a data-source ID.")

    calendar_id = choose("Calendar database number/ID: ")
    todo_id = choose("TODO database number/ID: ")

    phd_url = input(
        "\nNotion page URL (leave blank to skip auto-opening): "
    ).strip()

    calendar_props = {}
    todo_props = {}

    try:
        calendar_props = notion.data_sources.retrieve(
            data_source_id=calendar_id
        ).get("properties", {})
    except Exception:
        pass

    try:
        todo_props = notion.data_sources.retrieve(
            data_source_id=todo_id
        ).get("properties", {})
    except Exception:
        pass

    def find_name(props, types, default):
        for name, prop in props.items():
            if prop.get("type") in types:
                return name
        return default

    calendar_title = find_name(calendar_props, {"title"}, "Name")
    calendar_date = find_name(calendar_props, {"date"}, "Date")
    calendar_location = find_name(
        calendar_props, {"rich_text", "select"}, "Location"
    )
    calendar_description = find_name(
        calendar_props, {"rich_text"}, "Description"
    )

    todo_title = find_name(todo_props, {"title"}, "Name")
    todo_due = find_name(todo_props, {"date"}, "Due")
    todo_status = find_name(
        todo_props, {"status", "select"}, "Status"
    )
    todo_priority = find_name(
        todo_props, {"select", "status"}, "Priority"
    )

    config = {
        "notion": {
            "phd_page_url": phd_url,
            "calendar_data_source_id": calendar_id,
            "todo_data_source_id": todo_id,
        },
        "calendar": {
            "title_property": calendar_title,
            "date_property": calendar_date,
            "location_property": calendar_location,
            "description_property": calendar_description,
        },
        "todo": {
            "title_property": todo_title,
            "due_property": todo_due,
            "status_property": todo_status,
            "priority_property": todo_priority,
            "completed_statuses": [
                "Done",
                "Completed",
                "Cancelled",
            ],
        },
        "app": {
            "refresh_minutes": 5,
            "max_todos": 12,
            "max_meetings": 10,
            "open_notion_on_start": bool(phd_url),
            "start_minimized": False,
            "window_width": 520,
            "window_height": 760,
        },
    }

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            config,
            f,
            sort_keys=False,
            allow_unicode=True,
        )

    print("\nConfiguration saved to:")
    print(CONFIG_PATH)
    print("\nDetected properties:")
    print(f"  Calendar title: {calendar_title}")
    print(f"  Calendar date:  {calendar_date}")
    print(f"  TODO title:     {todo_title}")
    print(f"  TODO due:       {todo_due}")
    print(f"  TODO status:    {todo_status}")
    print("\nRun:")
    print(r"  .\.venv\Scripts\python.exe main.py")


if __name__ == "__main__":
    main()
