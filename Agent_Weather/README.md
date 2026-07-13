# AI Weather Agent

Dự án này xây dựng một AI Agent trả lời thời tiết theo thời gian thực cho bất kỳ địa điểm nào trên thế giới. Agent sử dụng LangChain để điều phối tool, Gemini 2.5 Flash làm bộ não suy luận, Pydantic để định nghĩa schema dữ liệu, và Open-Meteo để lấy dữ liệu thời tiết realtime.

## Tính năng

- Hỏi thời tiết hiện tại theo tên thành phố, quốc gia, địa danh, hoặc landmark.
- Hỗ trợ truy vấn vị trí trên toàn cầu thông qua Open-Meteo Geocoding API.
- Lấy dữ liệu realtime gồm nhiệt độ, cảm giác thực, độ ẩm, mưa, tuyết, mây, áp suất, gió và hướng gió.
- Hỗ trợ đơn vị metric mặc định và imperial khi người dùng yêu cầu Fahrenheit/mph.
- Hỗ trợ dự báo ngắn ngày khi câu hỏi có nội dung về dự báo.
- Sử dụng schema Pydantic cho input tool, kết quả thời tiết và output của assistant.
- Tách code theo cấu trúc module rõ ràng để dễ mở rộng.

## Cấu trúc dự án

```text
.
|-- app.py
|-- .env
|-- requirements.txt
|-- config.py
|-- llm.py
|-- schemas/
|   |-- __init__.py
|   |-- answer.py
|   `-- weather.py
|-- tools/
|   |-- __init__.py
|   `-- weather.py
|-- prompts/
|   `-- system_prompt.py
`-- agent/
    |-- __init__.py
    `-- assistant.py
```

## Vai trò từng file

### `app.py`

Đây là entrypoint của ứng dụng. File này cung cấp giao diện CLI để chạy agent theo hai cách:

- Truyền câu hỏi trực tiếp qua command line.
- Chạy chế độ chat nếu không truyền câu hỏi.

Ví dụ:

```bash
python app.py "Thời tiết ở Hà Nội hôm nay thế nào?"
```

Hoặc:

```bash
python app.py
```

### `config.py`

File này đọc cấu hình từ biến môi trường và file `.env` bằng `pydantic-settings`.

Những cấu hình chính:

- `GOOGLE_API_KEY`: API key để gọi Gemini.
- `GEMINI_API_KEY`: tên biến thay thế nếu muốn dùng cách đặt tên riêng.
- `GEMINI_MODEL`: model Gemini cần dùng, mặc định là `gemini-2.5-flash`.
- `REQUEST_TIMEOUT_SECONDS`: timeout khi gọi API thời tiết, mặc định là `15`.

Nếu không có API key, ứng dụng sẽ báo lỗi rõ ràng.

### `llm.py`

File này khởi tạo model Gemini thông qua `ChatGoogleGenerativeAI` của `langchain-google-genai`.

Model mặc định:

```text
gemini-2.5-flash
```

Đây là bộ não của agent, chịu trách nhiệm hiểu câu hỏi, quyết định khi nào cần gọi tool và tạo câu trả lời cuối cùng.

### `schemas/answer.py`

Định nghĩa schema `AgentAnswer` cho output của assistant.

Schema gồm:

- `question`: câu hỏi gốc của người dùng.
- `answer`: câu trả lời từ AI Agent.

### `schemas/weather.py`

Định nghĩa các schema Pydantic liên quan đến thời tiết:

- `WeatherQuery`: input của weather tool.
- `Coordinates`: thông tin toạ độ và địa danh sau khi geocoding.
- `CurrentWeather`: dữ liệu thời tiết hiện tại.
- `DailyForecast`: dự báo theo ngày.
- `WeatherResult`: kết quả tổng hợp trả về từ weather tool.

`WeatherQuery` là schema quan trọng nhất vì được gán trực tiếp vào LangChain tool thông qua `args_schema`.

### `tools/weather.py`

Đây là tool lấy thời tiết realtime.

Tool thực hiện hai bước:

1. Gọi Open-Meteo Geocoding API để tìm toạ độ từ tên địa điểm.
2. Gọi Open-Meteo Forecast API để lấy thời tiết hiện tại và dự báo nếu cần.

Tool được định nghĩa bằng decorator:

```python
@tool(args_schema=WeatherQuery)
```

Nhờ đó, LangChain agent có thể gọi tool với input được validate bởi Pydantic.

### `prompts/system_prompt.py`

Chứa system prompt cho agent.

Prompt yêu cầu agent:

- Luôn gọi `get_realtime_weather` khi người dùng hỏi về thời tiết.
- Trả lời bằng tiếng Việt ngắn gọn, tự nhiên.
- Hỏi lại nếu địa điểm quá mơ hồ.
- Dùng metric mặc định, chuyển sang imperial khi người dùng yêu cầu.
- Không tự bịa số liệu thời tiết nếu tool không cung cấp.

### `agent/assistant.py`

File này lắp ráp AI Agent.

Thành phần chính:

- Gemini 2.5 Flash từ `llm.py`.
- Weather tool từ `tools/weather.py`.
- System prompt từ `prompts/system_prompt.py`.
- `create_tool_calling_agent` của LangChain.
- `AgentExecutor` để chạy agent.

Class chính:

```python
WeatherAssistant
```

Phương thức sử dụng:

```python
assistant = WeatherAssistant()
answer = assistant.ask("Thời tiết Tokyo hôm nay thế nào?")
print(answer.answer)
```

## Cài đặt

Tạo virtual environment nếu cần:

```bash
python -m venv .venv
```

Kích hoạt trên Windows PowerShell:

```bash
.\.venv\Scripts\Activate.ps1
```

Cài dependencies:

```bash
pip install -r requirements.txt
```

## Cấu hình `.env`

Trong file `.env`, thêm Gemini API key:

```env
GOOGLE_API_KEY=your_gemini_api_key
```

Hoặc:

```env
GEMINI_API_KEY=your_gemini_api_key
```

Có thể tuỳ chỉnh model:

```env
GEMINI_MODEL=gemini-2.5-flash
REQUEST_TIMEOUT_SECONDS=15
```

## Cách chạy

Hỏi một câu trực tiếp:

```bash
python app.py "Thời tiết ở Singapore bây giờ thế nào?"
```

Hỏi dự báo:

```bash
python app.py "Dự báo thời tiết ở Đà Nẵng 3 ngày tới thế nào?"
```

Hỏi bằng đơn vị imperial:

```bash
python app.py "What is the weather in New York in Fahrenheit?"
```

Chạy chế độ chat:

```bash
python app.py
```

Thoát khỏi chế độ chat bằng:

```text
exit
```

## Luồng hoạt động

1. Người dùng nhập câu hỏi vào `app.py`.
2. `app.py` tạo `WeatherAssistant`.
3. `WeatherAssistant` khởi tạo Gemini, prompt và weather tool.
4. Gemini đọc câu hỏi và quyết định gọi `get_realtime_weather`.
5. Tool validate input bằng `WeatherQuery`.
6. Tool tìm toạ độ địa điểm qua Open-Meteo Geocoding API.
7. Tool lấy dữ liệu thời tiết qua Open-Meteo Forecast API.
8. Kết quả được chuẩn hoá bằng Pydantic schema.
9. Gemini đọc kết quả tool và tạo câu trả lời tiếng Việt cho người dùng.

## Dependencies

File `requirements.txt` gồm các thư viện chính:

- `langchain`
- `langchain-core`
- `langchain-google-genai`
- `pydantic`
- `pydantic-settings`
- `python-dotenv`
- `requests`

## Ghi chú

- Open-Meteo không yêu cầu API key cho dữ liệu thời tiết cơ bản.
- Gemini cần API key riêng từ Google AI Studio hoặc Google Cloud.
- Agent chỉ nên trả lời dựa trên dữ liệu tool trả về, không tự tạo số liệu thời tiết.
- Nếu địa điểm không tìm thấy, tool sẽ trả về lỗi kèm gợi ý nhập địa điểm cụ thể hơn.

## Kiểm tra nhanh

Có thể kiểm tra cú pháp Python bằng:

```bash
python -m compileall app.py config.py llm.py schemas tools prompts agent
```

Lệnh này đã được chạy thành công trong quá trình tạo project.
