# Davis WeatherLinkIP MQTT Home Assistant Add-on

A Home Assistant add-on that reads live `LOOP` packets from a Davis WeatherLinkIP data logger over the local network and publishes normalized weather station data to MQTT.

This was built for a Davis Vantage Vue with the classic WeatherLinkIP logger, but it should also work with Davis stations supported by the same WeatherLinkIP `LOOP` protocol.

## What It Does

- Connects directly to the WeatherLinkIP TCP service, usually port `22222`.
- Uses PyVantagePro to decode Davis `LOOP` packets.
- Publishes one retained JSON state payload to MQTT.
- Publishes MQTT discovery configs for Home Assistant.
- Exposes a `Last Update` sensor with the full decoded raw packet fields as attributes.
- Includes an example YAML package for Home Assistant installations where MQTT discovery is disabled.

## Installation

In Home Assistant:

1. Go to **Settings > Add-ons > Add-on Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add this repository URL:

```text
https://github.com/John-Vance/davis-weatherlinkip-mqtt
```

4. Install **Davis WeatherLinkIP MQTT**.
5. Configure `station_host` for your WeatherLinkIP logger IP address.
6. Start the add-on.

The add-on expects Home Assistant's MQTT service to be available. The official Mosquitto broker add-on works well.

## Add-on Options

```yaml
station_host: 192.168.1.17
station_port: 22222
station_timeout_seconds: 10
interval_seconds: 30
retry_seconds: 15
discovery_prefix: homeassistant
base_topic: home/weather/davis_vantage_vue
device_name: Davis Vantage Vue
device_id: davis_weatherlinkip
publish_raw_fields: true
```

`device_id` is used in MQTT unique IDs. If your station has a visible WeatherLinkIP device ID, use that value for stable Home Assistant entity IDs.

## MQTT Topics

By default:

- State: `home/weather/davis_vantage_vue/state`
- Availability: `home/weather/davis_vantage_vue/availability`
- Discovery: `homeassistant/sensor/.../config`

The state payload includes normalized keys such as:

- `outdoor_temperature_f`
- `outdoor_humidity_pct`
- `dew_point_f`
- `wind_chill_f`
- `heat_index_f`
- `barometer_inhg`
- `wind_speed_mph`
- `wind_direction_deg`
- `rain_rate_in_per_hr`
- `rain_day_in`
- `rain_month_in`
- `rain_year_in`
- `battery_voltage_v`
- `battery_status`
- `raw_fields`

Missing Davis values such as `255`, `32767`, or invalid packed dates are normalized to `null` where appropriate.

## Manual MQTT Package

If MQTT discovery is disabled in Home Assistant, copy `examples/davis_weatherlink.yaml` into `/config/packages/` and enable packages in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Adjust the MQTT topics, unique IDs, device ID, and station URL in the example package to match your add-on options.

Run a config check and restart Home Assistant Core after adding the package.

## Notes

This add-on intentionally reads from the local WeatherLinkIP logger and does not require Davis cloud credentials.

PyVantagePro is licensed under GPLv3, so this add-on is published under GPLv3 as well.
