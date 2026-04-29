from __future__ import annotations

import json
import logging
import math
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
from pyvantagepro import VantagePro2

CONFIG_PATH = "/data/options.json"
DEFAULT_MQTT_HOST = "core-mosquitto"
DEFAULT_MQTT_PORT = 1883

LOGGER = logging.getLogger("davis_weatherlink_mqtt")
SHOULD_STOP = False


@dataclass(frozen=True)
class SensorEntity:
    key: str
    name: str
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: str | None = None
    precision: int | None = None
    enabled_by_default: bool = True


STANDARD_SENSORS: list[SensorEntity] = [
    SensorEntity("outdoor_temperature_f", "Outdoor Temperature", "temperature", "\u00b0F", "measurement", precision=1),
    SensorEntity("outdoor_humidity_pct", "Outdoor Humidity", "humidity", "%", "measurement", precision=0),
    SensorEntity("dew_point_f", "Dew Point", "temperature", "\u00b0F", "measurement", precision=1),
    SensorEntity("wind_chill_f", "Wind Chill", "temperature", "\u00b0F", "measurement", precision=1),
    SensorEntity("heat_index_f", "Heat Index", "temperature", "\u00b0F", "measurement", precision=1),
    SensorEntity("barometer_inhg", "Barometer", "pressure", "inHg", "measurement", precision=3),
    SensorEntity("wind_speed_mph", "Wind Speed", "wind_speed", "mph", "measurement", precision=0),
    SensorEntity("wind_speed_10_min_mph", "10 Minute Wind Speed", "wind_speed", "mph", "measurement", precision=0),
    SensorEntity("wind_direction_deg", "Wind Direction", "wind_direction", "\u00b0", "measurement_angle", precision=0),
    SensorEntity("rain_rate_in_per_hr", "Rain Rate", "precipitation_intensity", "in/h", "measurement", precision=2),
    SensorEntity("rain_day_in", "Rain Today", "precipitation", "in", "total_increasing", precision=2),
    SensorEntity("rain_month_in", "Rain This Month", "precipitation", "in", "total_increasing", precision=2),
    SensorEntity("rain_year_in", "Rain This Year", "precipitation", "in", "total_increasing", precision=2),
    SensorEntity("rain_storm_in", "Storm Rain", "precipitation", "in", "total_increasing", precision=2),
    SensorEntity("indoor_temperature_f", "Indoor Temperature", "temperature", "\u00b0F", "measurement", precision=1),
    SensorEntity("indoor_humidity_pct", "Indoor Humidity", "humidity", "%", "measurement", precision=0),
    SensorEntity("battery_voltage_v", "Console Battery Voltage", "voltage", "V", "measurement", precision=2),
]

OPTIONAL_SENSORS: list[SensorEntity] = [
    SensorEntity("solar_radiation_w_m2", "Solar Radiation", "irradiance", "W/m\u00b2", "measurement", precision=0, enabled_by_default=False),
    SensorEntity("uv_index", "UV Index", None, None, "measurement", icon="mdi:weather-sunny", precision=1, enabled_by_default=False),
    SensorEntity("et_day_in", "ET Today", "precipitation", "in", "total_increasing", precision=3, enabled_by_default=False),
    SensorEntity("et_month_in", "ET This Month", "precipitation", "in", "total_increasing", precision=2, enabled_by_default=False),
    SensorEntity("et_year_in", "ET This Year", "precipitation", "in", "total_increasing", precision=2, enabled_by_default=False),
]

DIAGNOSTIC_SENSORS: list[SensorEntity] = [
    SensorEntity("bar_trend", "Bar Trend", icon="mdi:gauge", entity_category="diagnostic"),
    SensorEntity("bar_trend_code", "Bar Trend Code", icon="mdi:gauge", entity_category="diagnostic", enabled_by_default=False),
    SensorEntity("battery_status", "Battery Status", icon="mdi:battery", entity_category="diagnostic"),
    SensorEntity("forecast_icon", "Forecast Icon", icon="mdi:weather-partly-cloudy", entity_category="diagnostic", enabled_by_default=False),
    SensorEntity("forecast_rule", "Forecast Rule", icon="mdi:weather-partly-cloudy", entity_category="diagnostic", enabled_by_default=False),
    SensorEntity("sunrise", "Console Sunrise", icon="mdi:weather-sunset-up", entity_category="diagnostic", enabled_by_default=False),
    SensorEntity("sunset", "Console Sunset", icon="mdi:weather-sunset-down", entity_category="diagnostic", enabled_by_default=False),
    SensorEntity("storm_start_date", "Storm Start Date", icon="mdi:weather-pouring", entity_category="diagnostic", enabled_by_default=False),
]

LAST_UPDATE_SENSOR = SensorEntity(
    "updated_at",
    "Last Update",
    "timestamp",
    entity_category="diagnostic",
)

BAR_TRENDS = {
    -60: "falling rapidly",
    -20: "falling slowly",
    0: "steady",
    20: "rising slowly",
    60: "rising rapidly",
    80: "no trend available",
}

BATTERY_STATUSES = {
    0: "ok",
    1: "replace console battery",
    2: "transmitter battery low",
}


def handle_signal(signum: int, frame: Any) -> None:
    del signum, frame
    global SHOULD_STOP
    SHOULD_STOP = True


def load_options() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as options_file:
        options = json.load(options_file)
    options["station_port"] = int(options.get("station_port", 22222))
    options["station_timeout_seconds"] = int(options.get("station_timeout_seconds", 10))
    options["interval_seconds"] = int(options.get("interval_seconds", 30))
    options["retry_seconds"] = int(options.get("retry_seconds", 15))
    options["base_topic"] = str(options.get("base_topic", "home/weather/davis_vantage_vue")).strip("/")
    options["discovery_prefix"] = str(options.get("discovery_prefix", "homeassistant")).strip("/")
    options["device_id"] = str(options.get("device_id", "davis_weatherlinkip")).strip()
    options["device_name"] = str(options.get("device_name", "Davis Vantage Vue")).strip()
    return options


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("pylink").setLevel(logging.WARNING)
    logging.getLogger("pyvpdriver").setLevel(logging.WARNING)


def create_mqtt_client(client_id: str, availability_topic: str) -> mqtt.Client:
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:
        client = mqtt.Client(client_id=client_id)

    mqtt_username = os.getenv("MQTT_USERNAME") or os.getenv("MQTT_USER")
    mqtt_password = os.getenv("MQTT_PASSWORD")
    if mqtt_username:
        client.username_pw_set(mqtt_username, mqtt_password)

    client.will_set(availability_topic, payload="offline", retain=True)
    client.reconnect_delay_set(min_delay=2, max_delay=60)
    return client


def connect_mqtt(client: mqtt.Client) -> None:
    mqtt_host = os.getenv("MQTT_HOST", DEFAULT_MQTT_HOST)
    mqtt_port = int(os.getenv("MQTT_PORT", str(DEFAULT_MQTT_PORT)))
    LOGGER.info("Connecting to MQTT broker %s:%s", mqtt_host, mqtt_port)
    client.connect(mqtt_host, mqtt_port, keepalive=60)
    client.loop_start()


def sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "davis_weatherlinkip"


def snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return sanitize_slug(value)


def value_template(key: str) -> str:
    return "{% if value_json." + key + " is not none %}{{ value_json." + key + " }}{% endif %}"


def device_info(options: dict[str, Any]) -> dict[str, Any]:
    device_id = sanitize_slug(options["device_id"])
    return {
        "identifiers": [f"davis_weatherlinkip_{device_id}"],
        "name": options["device_name"],
        "manufacturer": "Davis Instruments",
        "model": "Vantage Vue with WeatherLinkIP",
        "configuration_url": f"http://{options['station_host']}/",
    }


def discovery_payload(entity: SensorEntity, options: dict[str, Any], state_topic: str, availability_topic: str) -> dict[str, Any]:
    object_prefix = sanitize_slug(options["device_name"])
    unique_prefix = sanitize_slug(options["device_id"])
    payload: dict[str, Any] = {
        "name": entity.name,
        "object_id": f"{object_prefix}_{entity.key}",
        "unique_id": f"davis_weatherlinkip_{unique_prefix}_{entity.key}",
        "state_topic": state_topic,
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "value_template": value_template(entity.key),
        "device": device_info(options),
        "enabled_by_default": entity.enabled_by_default,
    }
    if entity.device_class:
        payload["device_class"] = entity.device_class
    if entity.unit:
        payload["unit_of_measurement"] = entity.unit
    if entity.state_class:
        payload["state_class"] = entity.state_class
    if entity.icon:
        payload["icon"] = entity.icon
    if entity.entity_category:
        payload["entity_category"] = entity.entity_category
    if entity.precision is not None:
        payload["suggested_display_precision"] = entity.precision
    if entity.key == LAST_UPDATE_SENSOR.key:
        payload["json_attributes_topic"] = state_topic
    return payload


def publish_discovery(client: mqtt.Client, options: dict[str, Any], state_topic: str, availability_topic: str) -> None:
    all_entities = [LAST_UPDATE_SENSOR] + STANDARD_SENSORS + OPTIONAL_SENSORS + DIAGNOSTIC_SENSORS
    device_slug = sanitize_slug(options["device_id"])
    for entity in all_entities:
        topic = f"{options['discovery_prefix']}/sensor/{device_slug}/{entity.key}/config"
        payload = discovery_payload(entity, options, state_topic, availability_topic)
        result = client.publish(topic, json.dumps(payload, separators=(",", ":")), retain=True)
        result.wait_for_publish(timeout=10)
    LOGGER.info("Published %s MQTT discovery configs", len(all_entities))


def signed_byte(value: Any) -> int | None:
    number = as_int(value, minimum=0, maximum=255)
    if number is None:
        return None
    return number - 256 if number > 127 else number


def as_float(
    value: Any,
    minimum: float | None = None,
    maximum: float | None = None,
    invalid_values: set[float] | None = None,
    digits: int | None = None,
) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if invalid_values and number in invalid_values:
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    if digits is not None:
        return round(number, digits)
    return number


def as_int(
    value: Any,
    minimum: int | None = None,
    maximum: int | None = None,
    invalid_values: set[int] | None = None,
) -> int | None:
    number = as_float(value)
    if number is None:
        return None
    integer = int(number)
    if invalid_values and integer in invalid_values:
        return None
    if minimum is not None and integer < minimum:
        return None
    if maximum is not None and integer > maximum:
        return None
    return integer


def dew_point_f(temperature_f: float | None, humidity_pct: float | None) -> float | None:
    if temperature_f is None or humidity_pct is None or humidity_pct <= 0:
        return None
    temperature_c = (temperature_f - 32.0) * 5.0 / 9.0
    gamma = math.log(humidity_pct / 100.0) + (17.625 * temperature_c) / (243.04 + temperature_c)
    dew_point_c = (243.04 * gamma) / (17.625 - gamma)
    return round(dew_point_c * 9.0 / 5.0 + 32.0, 1)


def heat_index_f(temperature_f: float | None, humidity_pct: float | None) -> float | None:
    if temperature_f is None or humidity_pct is None or temperature_f < 80:
        return None
    heat_index = (
        -42.379
        + 2.04901523 * temperature_f
        + 10.14333127 * humidity_pct
        - 0.22475541 * temperature_f * humidity_pct
        - 0.00683783 * temperature_f * temperature_f
        - 0.05481717 * humidity_pct * humidity_pct
        + 0.00122874 * temperature_f * temperature_f * humidity_pct
        + 0.00085282 * temperature_f * humidity_pct * humidity_pct
        - 0.00000199 * temperature_f * temperature_f * humidity_pct * humidity_pct
    )
    return round(heat_index, 1)


def wind_chill_f(temperature_f: float | None, wind_speed_mph: float | None) -> float | None:
    if temperature_f is None or wind_speed_mph is None or temperature_f > 50 or wind_speed_mph <= 3:
        return None
    wind_factor = wind_speed_mph ** 0.16
    return round(35.74 + 0.6215 * temperature_f - 35.75 * wind_factor + 0.4275 * temperature_f * wind_factor, 1)


def valid_storm_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def raw_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {snake_case(key): json_safe(value) for key, value in sorted(data.items())}


def build_payload(data: dict[str, Any], include_raw_fields: bool) -> dict[str, Any]:
    outdoor_temperature = as_float(data.get("TempOut"), minimum=-100, maximum=150, invalid_values={3276.7}, digits=1)
    indoor_temperature = as_float(data.get("TempIn"), minimum=-100, maximum=150, invalid_values={3276.7}, digits=1)
    outdoor_humidity = as_int(data.get("HumOut"), minimum=0, maximum=100, invalid_values={255})
    indoor_humidity = as_int(data.get("HumIn"), minimum=0, maximum=100, invalid_values={255})
    wind_speed = as_float(data.get("WindSpeed"), minimum=0, maximum=250, invalid_values={255}, digits=0)
    bar_trend_code = signed_byte(data.get("BarTrend"))
    battery_status_code = as_int(data.get("BatteryStatus"), minimum=0, maximum=255)

    payload: dict[str, Any] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "outdoor_temperature_f": outdoor_temperature,
        "indoor_temperature_f": indoor_temperature,
        "outdoor_humidity_pct": outdoor_humidity,
        "indoor_humidity_pct": indoor_humidity,
        "dew_point_f": dew_point_f(outdoor_temperature, outdoor_humidity),
        "heat_index_f": heat_index_f(outdoor_temperature, outdoor_humidity),
        "wind_chill_f": wind_chill_f(outdoor_temperature, wind_speed),
        "barometer_inhg": as_float(data.get("Barometer"), minimum=20, maximum=33, invalid_values={0}, digits=3),
        "bar_trend_code": bar_trend_code,
        "bar_trend": BAR_TRENDS.get(bar_trend_code),
        "wind_speed_mph": wind_speed,
        "wind_speed_10_min_mph": as_float(data.get("WindSpeed10Min"), minimum=0, maximum=250, invalid_values={255}, digits=0),
        "wind_direction_deg": as_int(data.get("WindDir"), minimum=0, maximum=360, invalid_values={32767, 65535}),
        "rain_rate_in_per_hr": as_float(data.get("RainRate"), minimum=0, maximum=50, invalid_values={655.35}, digits=2),
        "rain_day_in": as_float(data.get("RainDay"), minimum=0, maximum=200, invalid_values={655.35}, digits=2),
        "rain_month_in": as_float(data.get("RainMonth"), minimum=0, maximum=500, invalid_values={655.35}, digits=2),
        "rain_year_in": as_float(data.get("RainYear"), minimum=0, maximum=1000, invalid_values={655.35}, digits=2),
        "rain_storm_in": as_float(data.get("RainStorm"), minimum=0, maximum=200, invalid_values={655.35}, digits=2),
        "storm_start_date": valid_storm_date(data.get("StormStartDate")),
        "et_day_in": as_float(data.get("ETDay"), minimum=0, maximum=10, invalid_values={65.535}, digits=3),
        "et_month_in": as_float(data.get("ETMonth"), minimum=0, maximum=100, invalid_values={655.35}, digits=2),
        "et_year_in": as_float(data.get("ETYear"), minimum=0, maximum=200, invalid_values={655.35}, digits=2),
        "solar_radiation_w_m2": as_float(data.get("SolarRad"), minimum=0, maximum=1800, invalid_values={32767, 65535}, digits=0),
        "uv_index": as_float(data.get("UV"), minimum=0, maximum=25, invalid_values={255}, digits=1),
        "battery_voltage_v": as_float(data.get("BatteryVolts"), minimum=0, maximum=10, digits=2),
        "battery_status": BATTERY_STATUSES.get(battery_status_code, str(battery_status_code) if battery_status_code is not None else None),
        "forecast_icon": as_int(data.get("ForecastIcon"), minimum=0, maximum=255, invalid_values={255}),
        "forecast_rule": as_int(data.get("ForecastRuleNo"), minimum=0, maximum=255, invalid_values={255}),
        "sunrise": data.get("SunRise") if isinstance(data.get("SunRise"), str) else None,
        "sunset": data.get("SunSet") if isinstance(data.get("SunSet"), str) else None,
    }

    if include_raw_fields:
        payload["raw_fields"] = raw_fields(data)
    return payload


def connect_station(options: dict[str, Any]) -> VantagePro2:
    station_url = f"tcp:{options['station_host']}:{options['station_port']}"
    LOGGER.info("Connecting to Davis station at %s", station_url)
    return VantagePro2.from_url(station_url, timeout=options["station_timeout_seconds"])


def close_station(station: VantagePro2 | None) -> None:
    if station is None:
        return
    try:
        station.link.close()
    except Exception as error:
        LOGGER.debug("Error while closing station link: %s", error)


def publish_state(client: mqtt.Client, state_topic: str, payload: dict[str, Any]) -> None:
    state_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    result = client.publish(state_topic, state_json, retain=True)
    result.wait_for_publish(timeout=10)


def main() -> int:
    setup_logging()
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    options = load_options()
    state_topic = f"{options['base_topic']}/state"
    availability_topic = f"{options['base_topic']}/availability"
    mqtt_client_id = f"davis-weatherlinkip-{sanitize_slug(options['device_id'])}"

    mqtt_client = create_mqtt_client(mqtt_client_id, availability_topic)
    connect_mqtt(mqtt_client)
    mqtt_client.publish(availability_topic, "online", retain=True).wait_for_publish(timeout=10)
    publish_discovery(mqtt_client, options, state_topic, availability_topic)

    station: VantagePro2 | None = None
    while not SHOULD_STOP:
        try:
            if station is None:
                station = connect_station(options)
            current_data = station.get_current_data()
            payload = build_payload(dict(current_data), bool(options.get("publish_raw_fields", True)))
            publish_state(mqtt_client, state_topic, payload)
            LOGGER.info(
                "Published Davis data: temp=%s F humidity=%s%% wind=%s mph rain_today=%s in",
                payload.get("outdoor_temperature_f"),
                payload.get("outdoor_humidity_pct"),
                payload.get("wind_speed_mph"),
                payload.get("rain_day_in"),
            )
            sleep_seconds = options["interval_seconds"]
        except Exception as error:
            LOGGER.exception("Davis polling failed: %s", error)
            close_station(station)
            station = None
            sleep_seconds = options["retry_seconds"]

        stop_at = time.monotonic() + sleep_seconds
        while not SHOULD_STOP and time.monotonic() < stop_at:
            time.sleep(min(1, stop_at - time.monotonic()))

    LOGGER.info("Stopping Davis WeatherLinkIP MQTT publisher")
    close_station(station)
    mqtt_client.publish(availability_topic, "offline", retain=True).wait_for_publish(timeout=10)
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
