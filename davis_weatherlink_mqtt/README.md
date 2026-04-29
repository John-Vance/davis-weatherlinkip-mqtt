# Davis WeatherLinkIP MQTT

Reads Davis WeatherLinkIP `LOOP` packets from a local weather station and publishes normalized data to Home Assistant through MQTT.

## Configuration

Set `station_host` to the IP address of your WeatherLinkIP logger. Most WeatherLinkIP loggers expose live data on TCP port `22222`.

```yaml
station_host: 192.168.1.17
station_port: 22222
interval_seconds: 30
base_topic: home/weather/davis_vantage_vue
device_name: Davis Vantage Vue
device_id: davis_weatherlinkip
publish_raw_fields: true
```

Use a stable `device_id`, such as the WeatherLinkIP device ID shown on the logger's web page, before Home Assistant creates entities.

## Output

The add-on publishes:

- MQTT availability to `<base_topic>/availability`
- MQTT state JSON to `<base_topic>/state`
- MQTT discovery configs under `<discovery_prefix>/sensor/.../config`

The `Last Update` sensor includes the complete decoded packet under `raw_fields` when `publish_raw_fields` is enabled.
