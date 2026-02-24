"""
Two-way synchroniser between Alexa Shopping List and Microsoft To Do.

Strategy
--------
State is persisted in a JSON file (default: /config/state.json).
Each sync cycle:

1.  Load last-known state (the "anchor").
2.  Fetch current items from Alexa and MS Todo.
3.  Diff each side against the anchor to find:
      - new items (to push to the other side)
      - deleted / completed items (to remove / complete on the other side)
4.  Apply changes, update anchor, save state.

If we can't reconcile changes (both sides modified the same item), the
MS Todo version wins (like anylist did in the original).
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from alexa import AlexaAPI, AlexaItem
from mstodo import MSTodo, MSTodoItem

log = logging.getLogger(__name__)


@dataclass
class AnchorItem:
    """One item as it was at the last successful sync."""
    alexa_id: Optional[str]
    todo_id: Optional[str]
    value: str


@dataclass
class SyncState:
    items: list[AnchorItem] = field(default_factory=list)

    def find_by_alexa_id(self, aid: str) -> Optional[AnchorItem]:
        return next((i for i in self.items if i.alexa_id == aid), None)

    def find_by_todo_id(self, tid: str) -> Optional[AnchorItem]:
        return next((i for i in self.items if i.todo_id == tid), None)

    def find_by_value(self, value: str) -> Optional[AnchorItem]:
        return next((i for i in self.items if i.value.lower() == value.lower()), None)

    def to_dict(self) -> dict:
        return {"items": [
            {"alexa_id": i.alexa_id, "todo_id": i.todo_id, "value": i.value}
            for i in self.items
        ]}

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        s = cls()
        for item in data.get("items", []):
            s.items.append(AnchorItem(
                alexa_id=item.get("alexa_id"),
                todo_id=item.get("todo_id"),
                value=item.get("value", ""),
            ))
        return s


class Synchronizer:
    def __init__(self, config: dict, state_path: str = "/config/state.json"):
        self.config = config
        self.state_path = state_path
        self.alexa = AlexaAPI(config)
        self.todo = MSTodo(config, config_path=os.environ.get("CONFIG_PATH", "config.json"))

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> SyncState:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    return SyncState.from_dict(json.load(f))
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Could not load state (%s), starting fresh.", e)
        return SyncState()

    def _save_state(self, state: SyncState):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(state.to_dict(), f, indent=2)

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------

    def connect(self):
        log.info("Connecting to services...")
        self.todo.connect()
        # Alexa login is lazy, but trigger it early so we fail fast
        self.alexa._ensure_logged_in()
        log.info("Connected to both services.")

    # ------------------------------------------------------------------
    # Core sync
    # ------------------------------------------------------------------

    def sync(self):
        log.info("--- Sync cycle start ---")
        state = self._load_state()

        try:
            alexa_items: list[AlexaItem] = self.alexa.get_active_items()
            todo_items: list[MSTodoItem] = self.todo.get_items()
        except Exception as e:
            log.error("Failed to fetch items: %s", e)
            return

        alexa_by_id = {i.id: i for i in alexa_items}
        todo_by_id = {i.id: i for i in todo_items}

        new_state = SyncState()

        # ------------------------------------------------------------------
        # Walk anchor items and detect deletions / completions
        # ------------------------------------------------------------------
        for anchor in state.items:
            alexa_gone = anchor.alexa_id and anchor.alexa_id not in alexa_by_id
            todo_gone = anchor.todo_id and anchor.todo_id not in todo_by_id

            if alexa_gone and todo_gone:
                # Both removed → just drop from anchor
                log.debug("Both removed '%s', dropping anchor", anchor.value)
                continue

            if alexa_gone and not todo_gone:
                # Removed from Alexa → remove from Todo too
                log.info("'%s' removed from Alexa → removing from MS Todo", anchor.value)
                try:
                    self.todo.delete_item(todo_by_id[anchor.todo_id])
                    del todo_by_id[anchor.todo_id]
                except Exception as e:
                    log.error("Could not delete '%s' from MS Todo: %s", anchor.value, e)
                continue

            if not alexa_gone and todo_gone:
                # Removed from Todo → remove from Alexa too
                log.info("'%s' removed from MS Todo → removing from Alexa", anchor.value)
                try:
                    self.alexa.delete_item(alexa_by_id[anchor.alexa_id])
                    del alexa_by_id[anchor.alexa_id]
                except Exception as e:
                    log.error("Could not delete '%s' from Alexa: %s", anchor.value, e)
                continue

            # Both still present — keep in anchor
            new_state.items.append(anchor)
            # Remove from "new items" consideration
            if anchor.alexa_id in alexa_by_id:
                del alexa_by_id[anchor.alexa_id]
            if anchor.todo_id in todo_by_id:
                del todo_by_id[anchor.todo_id]

        # ------------------------------------------------------------------
        # Remaining Alexa items are NEW (not in anchor) → push to Todo
        # ------------------------------------------------------------------
        for alexa_item in list(alexa_by_id.values()):
            # Maybe it already exists in Todo by name?
            existing_todo = next(
                (t for t in todo_by_id.values()
                 if t.value.lower() == alexa_item.value.lower()),
                None
            )
            if existing_todo:
                log.debug("Matched '%s' by name between Alexa and Todo", alexa_item.value)
                new_state.items.append(AnchorItem(
                    alexa_id=alexa_item.id,
                    todo_id=existing_todo.id,
                    value=alexa_item.value,
                ))
                del todo_by_id[existing_todo.id]
            else:
                log.info("New item on Alexa '%s' → adding to MS Todo", alexa_item.value)
                try:
                    new_todo = self.todo.add_item(alexa_item.value)
                    new_state.items.append(AnchorItem(
                        alexa_id=alexa_item.id,
                        todo_id=new_todo.id,
                        value=alexa_item.value,
                    ))
                except Exception as e:
                    log.error("Could not add '%s' to MS Todo: %s", alexa_item.value, e)

        # ------------------------------------------------------------------
        # Remaining Todo items are NEW → push to Alexa
        # ------------------------------------------------------------------
        for todo_item in list(todo_by_id.values()):
            log.info("New item in MS Todo '%s' → adding to Alexa", todo_item.value)
            try:
                new_alexa = self.alexa.add_item(todo_item.value)
                new_state.items.append(AnchorItem(
                    alexa_id=new_alexa.id,
                    todo_id=todo_item.id,
                    value=todo_item.value,
                ))
            except Exception as e:
                log.error("Could not add '%s' to Alexa: %s", todo_item.value, e)

        self._save_state(new_state)
        log.info("--- Sync done (%d items) ---", len(new_state.items))

    # ------------------------------------------------------------------
    # Full initial sync (first run / bootstrap)
    # ------------------------------------------------------------------

    def initial_sync(self):
        """On first run, merge both lists and build the anchor."""
        log.info("Initial sync: merging Alexa and MS Todo lists")
        state = SyncState()

        try:
            alexa_items = self.alexa.get_active_items()
            todo_items = self.todo.get_items()
        except Exception as e:
            log.error("Initial sync fetch failed: %s", e)
            raise

        todo_by_name = {i.value.lower(): i for i in todo_items}
        alexa_by_name = {i.value.lower(): i for i in alexa_items}

        # Merge both lists
        all_names = set(todo_by_name) | set(alexa_by_name)
        for name in all_names:
            todo_item = todo_by_name.get(name)
            alexa_item = alexa_by_name.get(name)

            if todo_item and alexa_item:
                # Already on both sides
                state.items.append(AnchorItem(
                    alexa_id=alexa_item.id,
                    todo_id=todo_item.id,
                    value=alexa_item.value,
                ))
            elif todo_item and not alexa_item:
                # Only on Todo → add to Alexa
                log.info("Initial: '%s' only in Todo → adding to Alexa", todo_item.value)
                try:
                    new_alexa = self.alexa.add_item(todo_item.value)
                    state.items.append(AnchorItem(
                        alexa_id=new_alexa.id,
                        todo_id=todo_item.id,
                        value=todo_item.value,
                    ))
                except Exception as e:
                    log.error("Could not add '%s' to Alexa: %s", todo_item.value, e)
            elif alexa_item and not todo_item:
                # Only on Alexa → add to Todo
                log.info("Initial: '%s' only in Alexa → adding to Todo", alexa_item.value)
                try:
                    new_todo = self.todo.add_item(alexa_item.value)
                    state.items.append(AnchorItem(
                        alexa_id=alexa_item.id,
                        todo_id=new_todo.id,
                        value=alexa_item.value,
                    ))
                except Exception as e:
                    log.error("Could not add '%s' to Todo: %s", alexa_item.value, e)

        self._save_state(state)
        log.info("Initial sync complete: %d items", len(state.items))
