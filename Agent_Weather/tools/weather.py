from __future__ import annotations

import json
from typing import Any

import requests
from langchain_core.tools import tool

from config import get_settings
from schemas.weather import Coordinates, CurrentWeather, DailyForecast, WeatherQuery, WeatherResult

''' Vì các API thời tiết thường không trả về trạng thái thời tiết mà chỉ trả về các mã số nên phải ánh xạ các mã đó sang trạng thái thời tiết '''
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODE_MAP = {
    0: "Troi quang",
    1: "Gan nhu quang",
    2: "May rai rac",
    3: "Nhieu may",
    45: "Suong mu",
    48: "Suong mu dong bang",
    51: "Mua phun nhe",
    53: "Mua phun vua",
    55: "Mua phun nang",
    56: "Mua phun dong bang nhe",
    57: "Mua phun dong bang nang",
    61: "Mua nhe",
    63: "Mua vua",
    65: "Mua nang",
    66: "Mua dong bang nhe",
    67: "Mua dong bang nang",
    71: "Tuyet roi nhe",
    73: "Tuyet roi vua",
    75: "Tuyet roi nang",
    77: "Hat tuyet",
    80: "Mua rao nhe",
    81: "Mua rao vua",
    82: "Mua rao du doi",
    85: "Mua tuyet rao nhe",
    86: "Mua tuyet rao nang",
    95: "Giong bao",
    96: "Giong bao kem mua da nhe",
    99: "Giong bao kem mua da nang",
}


def _describe_weather(code: int | None) -> str:
    if code is None:
        return "Khong ro"
    return WEATHER_CODE_MAP.get(code, f"Ma thoi tiet {code}")


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    timeout = get_settings().request_timeout_seconds
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Weather service returned an invalid response.")
    return data


def _geocode(query: WeatherQuery) -> Coordinates:
    data = _request_json(
        GEOCODING_URL,
        {
            "name": query.location,
            "count": 1,
            "language": query.language,
            "format": "json",
        },
    )
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Could not find coordinates for location: {query.location}")

    place = results[0]
    return Coordinates(
        name=place["name"],
        country=place.get("country"),
        admin1=place.get("admin1"),
        latitude=place["latitude"],
        longitude=place["longitude"],
        timezone=place.get("timezone"),
    )


def _fetch_weather(query: WeatherQuery, location: Coordinates) -> WeatherResult:
    is_metric = query.units == "metric"
    params: dict[str, Any] = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "showers",
                "snowfall",
                "weather_code",
                "cloud_cover",
                "surface_pressure",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "timezone": "auto",
        "temperature_unit": "celsius" if is_metric else "fahrenheit",
        "wind_speed_unit": "kmh" if is_metric else "mph",
        "precipitation_unit": "mm" if is_metric else "inch",
        "forecast_days": 3 if query.include_forecast else 1,
    }

    if query.include_forecast:
        params["daily"] = ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
            ]
        )

    data = _request_json(FORECAST_URL, params)
    current = data.get("current") or {}
    units = data.get("current_units") or {}
    weather_code = current.get("weather_code")

    daily_forecast: list[DailyForecast] = []
    daily = data.get("daily") or {}
    for index, date in enumerate(daily.get("time") or []):
        code = _list_get(daily.get("weather_code"), index)
        daily_forecast.append(
            DailyForecast(
                date=date,
                weather_code=code,
                weather_description=_describe_weather(code),
                temperature_max=_list_get(daily.get("temperature_2m_max"), index),
                temperature_min=_list_get(daily.get("temperature_2m_min"), index),
                precipitation_sum=_list_get(daily.get("precipitation_sum"), index),
            )
        )

    return WeatherResult(
        location=location,
        current=CurrentWeather(
            time=current.get("time", ""),
            temperature=current.get("temperature_2m"),
            apparent_temperature=current.get("apparent_temperature"),
            relative_humidity=current.get("relative_humidity_2m"),
            precipitation=current.get("precipitation"),
            rain=current.get("rain"),
            showers=current.get("showers"),
            snowfall=current.get("snowfall"),
            cloud_cover=current.get("cloud_cover"),
            surface_pressure=current.get("surface_pressure"),
            wind_speed=current.get("wind_speed_10m"),
            wind_direction=current.get("wind_direction_10m"),
            weather_code=weather_code,
            weather_description=_describe_weather(weather_code),
            temperature_unit=units.get("temperature_2m", "degC" if is_metric else "degF"),
            wind_speed_unit=units.get("wind_speed_10m", "km/h" if is_metric else "mph"),
            precipitation_unit=units.get("precipitation", "mm" if is_metric else "inch"),
        ),
        daily_forecast=daily_forecast,
    )


def _list_get(values: list[Any] | None, index: int) -> Any:
    if not values or index >= len(values):
        return None
    return values[index]


@tool(args_schema=WeatherQuery)
def get_realtime_weather(
    location: str,
    language: str = "vi",
    units: str = "metric",
    include_forecast: bool = False,
) -> str:
    """Get realtime current weather for any place in the world by place name."""

    try:
        query = WeatherQuery(
            location=location,
            language=language,
            units=units,
            include_forecast=include_forecast,
        )
        coordinates = _geocode(query)
        result = _fetch_weather(query, coordinates)
        return result.model_dump_json(indent=2)
    except Exception as exc:
        error = {
            "error": str(exc),
            "hint": "Try a more specific location such as city, country, or landmark.",
        }
        return json.dumps(error, ensure_ascii=False, indent=2)
