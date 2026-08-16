"""Topic layout, shared by the poller and the openHAB config generator.

    <base>/<category>/<slug>          state, retained
    <base>/set/<slug>                 command
    <base>/status                     online | offline (LWT)
    <base>/status/last_success        ISO-8601 timestamp of the last good poll
    <base>/status/consecutive_failures
    <base>/diagnostics/errors         JSON array of active device errors
    <base>/diagnostics/error_active   ON when the unit reports any error
    <base>/fire/alarm                 mirrored fire-alarm state, ON | OFF
    <base>/fire/stop_confirmed        ON once both fans have actually stopped

Default base is home/ventilation/renson, so a broker ACL only needs

    topic readwrite home/ventilation/renson/#
"""

FILTER_RESET = "filter_reset"


def state_topic(base_topic, field):
    return f"{base_topic}/{field.category}/{field.slug}"


def command_topic(base_topic, slug):
    return f"{base_topic}/set/{slug}"


def command_wildcard(base_topic):
    return f"{base_topic}/set/+"


def slug_from_command_topic(base_topic, topic):
    prefix = f"{base_topic}/set/"
    return topic[len(prefix):] if topic.startswith(prefix) else None
