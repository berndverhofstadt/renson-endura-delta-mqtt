"""Inbound MQTT command handling.

Every accepted command maps to exactly one device field write, except the
virtual `filter_reset` button which reads `Filter preset time` and writes it
back into `Filter remaining time` - the sequence that clears the filter
counter (`Filter used time` drops to 0 as a side effect).

Nothing here can stop the fans. `Total nominal airflow` and the per-level
percentages are refused in shared/renson_client.py because writing them latches
fan tacho errors 35/36 that only a power cycle clears.
"""

import logging

from app.topics import FILTER_RESET, slug_from_command_topic
from app.validation import ValidationError, validate_write
from shared.fields import BY_SLUG, controllable

LOGGER = logging.getLogger("renson.commands")

PRESS_PAYLOADS = {"1", "on", "true", "press", "reset", "trigger"}


class CommandHandler:
    def __init__(self, client, base_topic, expose_installer=False, enabled=True):
        self.client = client
        self.base_topic = base_topic
        self.enabled = enabled
        self.fields = {f.slug: f for f in controllable(expose_installer)}

    @property
    def slugs(self):
        """Command slugs this handler answers to, virtual button included."""
        return sorted(list(self.fields) + [FILTER_RESET])

    def handle(self, topic, payload):
        """Apply one inbound message. Returns True when the device was written."""
        slug = slug_from_command_topic(self.base_topic, topic)
        if slug is None:
            return False

        if not self.enabled:
            LOGGER.warning("command_ignored_controls_disabled slug=%s", slug)
            return False

        if slug == FILTER_RESET:
            return self._reset_filter(payload)

        field = self.fields.get(slug)
        if field is None:
            # Distinguish "not a control" from "typo" so the log is actionable.
            known = BY_SLUG.get(slug)
            if known is None:
                LOGGER.warning("command_unknown slug=%s", slug)
            else:
                LOGGER.warning("command_not_controllable slug=%s control=%s", slug, known.control)
            return False

        try:
            value = validate_write(field, payload)
        except ValidationError as exc:
            LOGGER.warning("command_rejected slug=%s payload=%s err=%s", slug, payload, exc)
            return False

        echoed = self.client.write_field(field.name, value, field.index)
        # The device answers 200 even when it quietly substitutes a value, so
        # compare what came back with what was asked for.
        if echoed is not None and str(echoed).lower() != value.lower():
            LOGGER.warning("command_coerced slug=%s requested=%s device_returned=%s",
                           slug, value, echoed)
        else:
            LOGGER.info("command_applied slug=%s value=%s", slug, value)
        return True

    def _reset_filter(self, payload):
        if str(payload).strip().lower() not in PRESS_PAYLOADS:
            LOGGER.warning("filter_reset_ignored payload=%s", payload)
            return False

        preset = self.client.read_field("Filter preset time")
        self.client.write_field("Filter remaining time", preset)
        LOGGER.info("filter_reset_applied preset_days=%s", preset)
        return True
