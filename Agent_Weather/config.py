'''
    config.py
    Đọc dữ liệu cấu hình từ biến môi trường và tệp .env, cung cấp các cài đặt ứng dụng.
    Đầu vào: Biến môi trường hoặc tệp .env chứa các giá trị cấu hình.
    Đầu ra: Một đối tượng Settings chứa các giá trị cấu hình đã được giải quyết.
'''


from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    '''
        SecretStr được sử dụng để lưu trữ các giá trị nhạy cảm như API keys. Nó giúp bảo vệ thông tin nhạy cảm bằng cách mã hóa và không hiển thị trực tiếp trong logs hoặc console.
        Field được sử dụng để định nghĩa các trường trong lớp Settings, cho phép chỉ định các giá trị mặc định, alias (tên biến môi trường), và các ràng buộc.
    '''
    google_api_key: SecretStr | None = Field(default=None, alias="GOOGLE_API_KEY") 
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    request_timeout_seconds: int = Field(default=15, alias="REQUEST_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ''' 
        @property: Biến hàm bên dưới thành một thuộc tính (property). 
        Có thể gọi settings.resolved_google_api_key như một biến thông thường thay vì phải gọi dạng hàm settings.resolved_google_api_key().
        Hàm get_secret_value() được sử dụng để lấy giá trị thực của SecretStr mà không hiển thị trực tiếp trong logs hoặc console, giúp bảo vệ thông tin nhạy cảm. 
    '''
    @property
    def resolved_google_api_key(self) -> str:
        secret = self.google_api_key or self.gemini_api_key
        if secret is None:
            raise ValueError(
                "Missing Gemini API key. Add GOOGLE_API_KEY=your_key or "
                "GEMINI_API_KEY=your_key to the .env file."
            )
        return secret.get_secret_value()

''' 
    @lru_cache(maxsize=1): Decorator này được sử dụng để lưu trữ kết quả của hàm get_settings() trong bộ nhớ cache. 
    Khi hàm được gọi lần đầu tiên, nó sẽ tạo một đối tượng Settings và lưu trữ nó. 
    Các lần gọi tiếp theo sẽ trả về đối tượng đã lưu trữ mà không cần tạo lại, giúp cải thiện hiệu suất và giảm thiểu việc đọc từ môi trường hoặc tệp .env nhiều lần.
'''
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
