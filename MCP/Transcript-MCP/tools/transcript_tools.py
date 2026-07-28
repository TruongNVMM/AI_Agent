from services.parserPDF import parse_courses
from services.calculate_gpa import calculate_gpa
from services.calculate_cpa import calculate_cpa
from services.calculate_override import apply_overrides


def register_transcript_tools(mcp, pdf_path: str):
    @mcp.tool
    def list_courses() -> list[dict]:
        """Liệt kê toàn bộ học phần đã parse từ bảng điểm."""
        return [c.model_dump() for c in parse_courses(pdf_path)]

    @mcp.tool
    def get_semester_gpa(semester: str) -> dict:
        """Tính GPA của một học kỳ, ví dụ 20251."""
        courses = parse_courses(pdf_path)
        return calculate_gpa(courses, semester)

    @mcp.tool
    def get_cpa(up_to_semester: str | None = None) -> dict:
        """Tính CPA tích lũy, có xử lý học phần học lại."""
        courses = parse_courses(pdf_path)
        return calculate_cpa(courses, up_to_semester)

    @mcp.tool
    def simulate_grades(overrides: list[dict], up_to_semester: str | None = None) -> dict:
        """Điều chỉnh tạm thời điểm chữ của một số học phần rồi tính lại CPA/GPA."""
        courses = parse_courses(pdf_path)
        simulated = apply_overrides(courses, overrides)

        semesters = sorted({c.semester for c in simulated})
        return {
            "semester_gpas": [
                calculate_gpa(simulated, semester)
                for semester in semesters
            ],
            "cpa": calculate_cpa(simulated, up_to_semester),
        }