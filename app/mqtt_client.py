import logging
import queue
import ssl
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Missing dependency: install requirements.txt") from exc


class MqttBridge:
    """Publishes state and queues inbound commands for the poll loop to apply.

    Commands are not acted on inside the paho network thread: they are queued
    and drained by the poller, so a burst of writes cannot overlap a read cycle
    or hold up the MQTT keepalive.
    """

    def __init__(self, host, port, username, password, status_topic, debug_mode=False,
                 mqtt_tls=None, client_id="renson-endura-bridge", publish_status=True):
        self.host = host
        self.port = port
        self.status_topic = status_topic
        self.debug_mode = debug_mode
        # Side tools must not take over the LWT of a running bridge, so they
        # connect with publish_status=False.
        self.publish_status = publish_status
        self.inbox = queue.Queue(maxsize=1000)
        self._connected = threading.Event()
        # A refused CONNACK also fires on_connect, so connect() waits for the
        # handshake to resolve and then inspects the code, rather than treating
        # "callback happened" as "we are connected".
        self._handshake = threading.Event()
        self._connect_rc = None
        self._connect_timeout_seconds = 10
        self._flush_timeout_seconds = 10
        self._pending = []
        self._subscriptions = []
        # Bumped on every (re)connect. Brokers without retained-message
        # persistence lose everything on restart, so callers watch this to know
        # when retained topics need republishing.
        self.connect_count = 0

        if mqtt_tls is None:
            mqtt_tls = port in (8883, 8884, 443)
        self.mqtt_tls = bool(mqtt_tls)

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
        self.client.enable_logger(logging.getLogger("mqtt"))
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        if self.mqtt_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        if username not in (None, ""):
            self.client.username_pw_set(username, password)
        if self.publish_status:
            self.client.will_set(self.status_topic, payload="offline", qos=1, retain=True)

    def _on_connect(self, client, userdata, flags, rc):
        self._connect_rc = rc
        if rc == 0:
            self.connect_count += 1
            # Subscriptions do not survive a reconnect, so restore them here
            # rather than only at startup.
            for topic in self._subscriptions:
                client.subscribe(topic, qos=1)
            self._connected.set()
        else:
            logging.getLogger("mqtt").error("mqtt_connect_refused rc=%s reason=%s",
                                            rc, mqtt.connack_string(rc))
            self._connected.clear()
        self._handshake.set()

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()

    def _on_message(self, client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace").strip()
        try:
            self.inbox.put_nowait((message.topic, payload))
        except queue.Full:
            logging.getLogger("mqtt").warning("inbox_full_dropping topic=%s", message.topic)

    def connect(self):
        self._handshake.clear()
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self._handshake.wait(timeout=self._connect_timeout_seconds):
            raise RuntimeError(f"MQTT connect timeout for host={self.host} port={self.port}")
        if self._connect_rc != 0:
            raise RuntimeError(
                f"MQTT broker at {self.host}:{self.port} refused the connection: "
                f"rc={self._connect_rc} ({mqtt.connack_string(self._connect_rc)})"
            )
        if self.publish_status:
            self.publish(self.status_topic, "online", retain=True)

    def subscribe(self, topic):
        if topic in self._subscriptions:
            return
        self._subscriptions.append(topic)
        if self.client.is_connected():
            self.client.subscribe(topic, qos=1)

    def drain(self):
        """Pop every queued (topic, payload) currently waiting."""
        messages = []
        while True:
            try:
                messages.append(self.inbox.get_nowait())
            except queue.Empty:
                return messages

    def publish(self, topic, payload, retain=True):
        if self.debug_mode:
            logging.getLogger("mqtt").warning("mqtt_debug_mode_active topic=%s payload=%s", topic, payload)
            return None

        if not self.client.is_connected():
            raise RuntimeError(f"MQTT publish failed for topic {topic}: not connected")

        info = self.client.publish(topic, str(payload), qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed for topic {topic}: rc={info.rc}")

        # Drop already-acknowledged messages so a long-running bridge does not
        # accumulate them, and keep the rest for flush().
        self._pending = [pending for pending in self._pending if not pending.is_published()]
        self._pending.append(info)
        return info

    def flush(self, timeout=None):
        """Block until every queued publish has been acknowledged by the broker."""
        deadline = time.monotonic() + (self._flush_timeout_seconds if timeout is None else timeout)
        pending, self._pending = self._pending, []
        for info in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"MQTT flush timeout with {len(pending)} message(s) queued")
            info.wait_for_publish(timeout=remaining)

    def close(self):
        try:
            if self.publish_status and self.client.is_connected():
                self.publish(self.status_topic, "offline", retain=True)
            self.flush()
        except Exception as exc:
            logging.getLogger("mqtt").warning("mqtt_flush_on_close_failed err=%s", exc)
        self.client.loop_stop()
        self.client.disconnect()
        self._connected.clear()
