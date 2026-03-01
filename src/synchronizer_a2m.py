"""
Module      : synchronizer_a2m
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Einweg-Synchronizer (Alexa → MS Todo). Neue Items auf Alexa
              werden zu MS Todo hinzugefügt. Löschungen werden nicht
              propagiert. Optionales Löschen des Originals nach dem Sync
              (delete_origin).
"""

import logging
from synchronizer import Synchronizer, SyncState, AnchorItem

log = logging.getLogger(__name__)


class SynchronizerA2M(Synchronizer):

    def sync(self):
        log.info("--- Sync cycle start (alexa → todo) ---")
        state = self._load_state()
        delete_origin = self.config.get("delete_origin", False)

        try:
            alexa_items = self.alexa.get_active_items()
            todo_items = self.todo.get_items()
        except Exception as e:
            log.error("Failed to fetch items: %s", e)
            return

        alexa_by_id = {i.id: i for i in alexa_items}
        todo_by_id = {i.id: i for i in todo_items}

        new_state = SyncState()

        for anchor in state.items:
            alexa_gone = anchor.alexa_id and anchor.alexa_id not in alexa_by_id
            todo_gone = anchor.todo_id and anchor.todo_id not in todo_by_id

            if alexa_gone and todo_gone:
                log.debug("Both removed '%s', dropping anchor", anchor.value)
                continue

            if alexa_gone or todo_gone:
                log.debug("'%s' removed from one side, dropping anchor (no propagation)", anchor.value)
                continue

            new_state.items.append(anchor)
            if anchor.alexa_id in alexa_by_id:
                del alexa_by_id[anchor.alexa_id]
            if anchor.todo_id in todo_by_id:
                del todo_by_id[anchor.todo_id]

        for alexa_item in list(alexa_by_id.values()):
            existing_todo = next(
                (t for t in todo_by_id.values()
                 if t.value.lower() == alexa_item.value.lower()),
                None
            )
            if existing_todo:
                log.debug("Matched '%s' by name", alexa_item.value)
                new_state.items.append(AnchorItem(
                    alexa_id=alexa_item.id,
                    todo_id=existing_todo.id,
                    value=alexa_item.value,
                ))
                del todo_by_id[existing_todo.id]
            else:
                log.info("New item on Alexa '%s' → adding to MS Todo", alexa_item.value)
                try:
                    new_todo = self.todo.add_item(alexa_item.value.capitalize())
                    new_state.items.append(AnchorItem(
                        alexa_id=alexa_item.id,
                        todo_id=new_todo.id,
                        value=alexa_item.value,
                    ))
                except Exception as e:
                    log.error("Could not add '%s' to MS Todo: %s", alexa_item.value, e)
                else:
                    if delete_origin:
                        try:
                            log.info("delete_origin: removing '%s' from Alexa", alexa_item.value)
                            self.alexa.delete_item(alexa_item)
                        except Exception as e:
                            log.error("Could not delete '%s' from Alexa (delete_origin): %s",
                                      alexa_item.value, e)

        self._save_state(new_state)
        log.info("--- Sync done (%d items) ---", len(new_state.items))

    def initial_sync(self):
        log.info("Initial sync (alexa → todo)")
        state = SyncState()
        delete_origin = self.config.get("delete_origin", False)

        try:
            alexa_items = self.alexa.get_active_items()
            todo_items = self.todo.get_items()
        except Exception as e:
            log.error("Initial sync fetch failed: %s", e)
            raise

        todo_by_name = {i.value.lower(): i for i in todo_items}

        for alexa_item in alexa_items:
            existing = todo_by_name.get(alexa_item.value.lower())
            if existing:
                state.items.append(AnchorItem(
                    alexa_id=alexa_item.id,
                    todo_id=existing.id,
                    value=alexa_item.value,
                ))
            else:
                log.info("Initial: '%s' only in Alexa → adding to Todo", alexa_item.value)
                try:
                    new_todo = self.todo.add_item(alexa_item.value.capitalize())
                    state.items.append(AnchorItem(
                        alexa_id=alexa_item.id,
                        todo_id=new_todo.id,
                        value=alexa_item.value,
                    ))
                except Exception as e:
                    log.error("Could not add '%s' to Todo: %s", alexa_item.value, e)
                else:
                    if delete_origin:
                        try:
                            self.alexa.delete_item(alexa_item)
                        except Exception as e:
                            log.error("Could not delete '%s' from Alexa (delete_origin): %s",
                                      alexa_item.value, e)

        self._save_state(state)
        log.info("Initial sync complete: %d items", len(state.items))
