'''
    weather.py
    Định nghĩa các lớp dữ liệu cho yêu cầu thời tiết và kết quả thời tiết.
    Đầu vào: người dùng gửi vào. 
    Đầu ra: dữ liệu thời tiết được trả về từ API thời tiết.
'''


# Literal dùng để giới hạn giá trị của một biến chỉ có thể là một trong các giá trị cụ thể được liệt kê.
from typing import Literal

from pydantic import BaseModel, Field


'''
    Schema WeatherQuery: đây là schema cho dữ liệu đầu vào khi người dùng hỏi về thời tiết. 
'''
class WeatherQuery(BaseModel):
    """Input schema for the realtime weather tool."""

    location: str = Field(
        min_length=1,
        description="City, address, landmark, province, country, or any place name.",
        examples=["Hanoi, Vietnam", "Tokyo", "New York", "Eiffel Tower"],
    )

    language: str = Field(
        default="vi",
        min_length=2,
        max_length=5,
        description="Language code used for geocoding results, for example vi or en.",
    )

    units: Literal["metric", "imperial"] = Field(
        default="metric",
        description="Use metric for Celsius/km/h/mm or imperial for Fahrenheit/mph/inch.",
    )

    include_forecast: bool = Field(
        default=False,
        description="Set true when the user asks for a short forecast, not only current weather.",
    )


''' 
    Schema Coordinates: đây là schema cho dữ liệu tọa độ địa lý của một địa điểm.
    Nó bao gồm tên địa điểm, quốc gia, tỉnh/thành phố, vĩ độ, kinh độ và múi giờ. 
    Các trường country, admin1 và timezone là tùy chọn (có thể là None) vì không phải lúc nào cũng có thông tin này.
'''
class Coordinates(BaseModel):
    name: str
    country: str | None = None
    admin1: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None


'''
    Schema CurrentWeather: đây là schema cho dữ liệu thời tiết hiện tại của một địa điểm.
    Nó bao gồm các thông tin như thời gian, nhiệt độ, độ ẩm, lượng mưa, tốc độ gió, hướng gió, mã thời tiết và mô tả thời tiết.
    Các trường temperature, apparent_temperature, relative_humidity, precipitation, rain, showers, snowfall, cloud_cover, surface_pressure, wind_speed, wind_direction và weather_code là tùy chọn (có thể là None) vì không phải lúc nào cũng có thông tin này.
    Các trường temperature_unit, wind_speed_unit và precipitation_unit chỉ định đơn vị đo lường được sử dụng cho các giá trị tương ứng.
'''
class CurrentWeather(BaseModel):
    time: str
    temperature: float | None = None
    apparent_temperature: float | None = None
    relative_humidity: float | None = None
    precipitation: float | None = None
    rain: float | None = None
    showers: float | None = None
    snowfall: float | None = None
    cloud_cover: float | None = None
    surface_pressure: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    weather_code: int | None = None
    weather_description: str
    temperature_unit: str
    wind_speed_unit: str
    precipitation_unit: str


'''
    Schema DailyForecast: đây là schema cho dữ liệu dự báo thời tiết hàng ngày của một địa điểm.
    Nó bao gồm các thông tin như ngày, mã thời tiết, mô tả thời tiết, nhiệt độ cao nhất, nhiệt độ thấp nhất và tổng lượng mưa.
    Các trường weather_code, temperature_max, temperature_min và precipitation_sum là tùy chọn (có thể là None) vì không phải lúc nào cũng có thông tin này.
'''
class DailyForecast(BaseModel):
    date: str
    weather_code: int | None = None
    weather_description: str
    temperature_max: float | None = None
    temperature_min: float | None = None
    precipitation_sum: float | None = None


''' 
    Schema WeatherResult: đây là schema cho kết quả thời tiết tổng hợp của một địa điểm.
    Nó bao gồm thông tin về vị trí, thời tiết hiện tại và dự báo hàng ngày.
'''
class WeatherResult(BaseModel):
    location: Coordinates
    current: CurrentWeather
    daily_forecast: list[DailyForecast] = Field(default_factory=list)
    source: str = "Open-Meteo"
