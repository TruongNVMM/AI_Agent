from pathlib import Path
from fastmcp import FastMCP
from tools.transcript_tools import register_transcript_tools


BASE_DIR = Path(__file__).parent
PDF_PATH = BASE_DIR / "resources" / "Bảng điểm.pdf"

mcp = FastMCP(
    "Transcript MCP",
    instructions=(
        "Server phân tích bảng điểm PDF, tính GPA/CPA theo học kỳ, "
        "và mô phỏng thay đổi điểm tạm thời."
    ),
)

register_transcript_tools(mcp, str(PDF_PATH))


@mcp.resource("transcript://raw")
def transcript_raw() -> str:
    """Trả về text thô trích từ PDF bảng điểm."""
    from services.parserPDF import extract_text
    return extract_text(str(PDF_PATH))

if __name__ == "__main__":
    mcp.run()
