import re
import fitz
from pathlib import Path
from models.transcript import Course
from collections import defaultdict

SEMESTER_RE = re.compile(r"^\s*20\d{3}\s*$")
COURSE_CODE_RE = re.compile(r"^\s*[A-Z]{1,5}[A-Z0-9_-]*\d{3,5}[A-Z0-9_-]*\s*$")
GRADE_RE = re.compile(r"^\s*(A\+?|B\+?|C\+?|D\+?|F|P|I|W)\s*$")

def _to_float(value: str | None):
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None

def parse_courses(pdf_path: str) -> list[Course]:
    doc = fitz.open(pdf_path)
    courses = []
    
    for page in doc:
        # 1. Lấy tất cả các block chữ kèm tọa độ hình học
        blocks = page.get_text("blocks")
        
        # Loại bỏ các block nằm sau chữ "Kết quả học tập sinh viên" nếu có
        clean_blocks = []
        for b in blocks:
            if "Kết quả học tập sinh viên" in b[4]:
                break
            clean_blocks.append(b)
            
        # 2. Gom các dòng text có cùng tọa độ Y (cho phép sai số nhỏ do lệch dòng ~ 3 pixel)
        rows_dict = defaultdict(list)
        for x0, y0, x1, y1, text, block_no, block_type in clean_blocks:
            text_str = text.strip()
            if not text_str or text_str == "\xa0":
                continue
                
            # Làm tròn tọa độ Y để gom các text nằm trên cùng hàng ngang
            row_key = round(y0 / 3) * 3 
            rows_dict[row_key].append((x0, text_str))
            
        # 3. Sắp xếp các hàng từ trên xuống dưới, các chữ trong hàng từ trái qua phải
        sorted_row_keys = sorted(rows_dict.keys())
        
        current_semester = None
        
        for y_key in sorted_row_keys:
            # Sắp xếp các cột theo tọa độ X từ trái sang phải
            row_items = sorted(rows_dict[y_key], key=lambda item: item[0])
            row_texts = [item[1] for item in row_items]
            
            # Kết hợp các text trong hàng thành một chuỗi duy nhất để phân tích bằng Regex độc lập
            # Ví dụ: "20232 ET2000 Nhập môn kỹ thuật điện tử-viễn thông 3 123456 8.0 7.5 B+"
            full_row_text = " ".join(row_texts)
            
            # Kiểm tra nếu hàng này chứa thông tin học kỳ (ví dụ dòng tiêu đề phụ)
            if len(row_texts) == 1 and SEMESTER_RE.match(row_texts[0]):
                current_semester = row_texts[0]
                continue
                
            # Trích xuất dữ liệu bằng một biểu thức Regex bao quát toàn bộ hàng
            # Giải pháp này an toàn hơn rất nhiều vì không phụ thuộc vào chỉ số mảng lines[i]
            match = re.search(
                r'^(?P<semester>\d{5})?\s*'
                r'(?P<code>[A-Z]{1,5}[A-Z0-9_-]*\d{3,5}[A-Z0-9_-]*)\s+'
                r'(?P<name>.+)\s+'
                r'(?P<credits>\d+)\s+'
                r'(?P<class_id>\d+)\s+'
                r'(?:(?P<process>[\d.,-]+)\s+)?'
                r'(?P<exam>[\d.,-]+)\s+'
                r'(?P<letter>A\+?|B\+?|C\+?|D\+?|F|P|I|W)(?=\s|$)',
                full_row_text
            )
            
            if match:
                data = match.groupdict()
                
                # Nếu đầu dòng không có học kỳ, lấy học kỳ ghi nhớ gần nhất
                semester = data['semester'] if data['semester'] else current_semester
                if not semester:
                    continue # Bỏ qua nếu chưa xác định được học kỳ
                    
                courses.append(Course(
                    semester=semester,
                    code=data['code'],
                    name=data['name'].strip(),
                    credits=int(data['credits']),
                    class_id=data['class_id'],
                    process_score=_to_float(data['process']),
                    exam_score=_to_float(data['exam']),
                    letter_grade=data['letter']
                ))
                
    return courses

def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


