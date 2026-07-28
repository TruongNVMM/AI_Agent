# Transcript MCP Server

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)
[![License](https://img.shields.io/badge/license-MIT-informational.svg)](LICENSE)

An intelligent **Model Context Protocol (MCP)** server was built using Python and [FastMCP](https://github.com/jlowin/fastmcp). This server allows Big Language Model (LLM) agents (such as Claude Desktop, Cursor, or Antigravity) to analyze Hanoi University of Technology's academic transcript PDF files, analyze semester-by-semester GPA, calculate overall cumulative GPA (CPA), and run score prediction simulations ("scenarios").

---

## Key Features

- **Automated PDF Parsing**: Extracts structured course data (course code, name, credits, scores, letter grades, semester) directly from academic transcript PDFs using `PyMuPDF`.
- **GPA & CPA Calculation**:
  - **Semester GPA**: Calculates GPA for individual academic terms.
  - **Cumulative CPA**: Computes cumulative GPA with intelligent retake logic (replaces earlier grades with the highest achieved grade per course code).
- **Predictive Grade Simulation**: Allows AI assistants to simulate potential grade improvements or future retakes and forecast overall GPA/CPA impacts.
- **Exposed MCP Resources**: Provides raw transcript text via standard MCP resource URIs (`transcript://raw`).
- **Type-Safe & Fast**: Powered by Pydantic models for strict data validation and FastMCP for light-speed protocol handling.

---

## Project Architecture

```
Transcript-MCP/
├── models/
│   └── transcript.py         # Pydantic data schemas (Course, SemesterResult, Grade Scale)
├── services/
│   ├── parserPDF.py          # PDF text extraction & structured regex parsing logic
│   ├── calculate_gpa.py      # Semester GPA calculation engine
│   ├── calculate_cpa.py      # Cumulative CPA calculation engine (with retake filter)
│   └── calculate_override.py # Grade override simulator logic
├── tools/
│   └── transcript_tools.py   # MCP tools registration wrapper
├── resources/
│   └── Bảng điểm.pdf        # Target academic transcript PDF
├── server.py                 # FastMCP entry point & resource declarations
├── fastmcp.json              # FastMCP CLI configuration
└── requirements.txt          # Project dependencies
```

---

## Available MCP Tools & Resources

### Tools

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `list_courses` | *None* | Parses and returns a full structured list of all completed and enrolled courses. |
| `get_semester_gpa` | `semester: str` (e.g. `"20251"`) | Returns the GPA and credit count for a specific academic semester. |
| `get_cpa` | `up_to_semester: str \| None` | Calculates cumulative CPA and total credits up to a given semester (or all time if omitted). Accounts for course retakes. |
| `simulate_grades` | `overrides: list[dict]`, `up_to_semester: str \| None` | Temporarily overrides letter grades for specified course codes and recalculates semester GPAs and cumulative CPA. |

#### Grade Override Format Example for `simulate_grades`:
```json
[
  { "code": "IT3040", "letter_grade": "A" },
  { "code": "MI1110", "letter_grade": "B+" }
]
```

---

### Resources

| Resource URI | Description |
| :--- | :--- |
| `transcript://raw` | Returns the raw, unparsed text content extracted from the target PDF transcript file. |

---

## Grade Point Scale

The engine maps letter grades to numerical quality points based on standard academic grading criteria:

| Letter Grade | Grade Points |
| :---: | :---: |
| **A+ / A** | `4.0` |
| **B+** | `3.5` |
| **B** | `3.0` |
| **C+** | `2.5` |
| **C** | `2.0` |
| **D+** | `1.5` |
| **D** | `1.0` |
| **F** | `0.0` |

---

## Getting Started

### 1. Prerequisites

- **Python**: Version `3.10` or higher required.
- **MCP Client**: Claude Desktop, Cursor, Antigravity, or any compatible MCP client application.

### 2. Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/TruongNVMM/AI_Agent.git
   cd Transcript-MCP
   ```

2. **Create and activate a virtual environment**:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **Linux / macOS**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Add your Transcript PDF**:
   Place your transcript PDF inside the `resources/` folder as `Bảng điểm.pdf`, or update the path in [server.py](file:///c:/Users/ediso/Desktop/AI_Agent/MCP/Transcript-MCP/server.py).

---

## Configuration & Integration

### Claude Desktop Integration

Add the following snippet to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "transcript-mcp": {
      "command": "python",
      "args": [
        "C:/Users/ediso/Desktop/AI_Agent/MCP/Transcript-MCP/server.py"
      ],
      "env": {
        "PYTHONPATH": "C:/Users/ediso/Desktop/AI_Agent/MCP/Transcript-MCP"
      }
    }
  }
}
```

> **Note**: Update the absolute paths according to your environment.

### Running with FastMCP CLI

FastMCP provides built-in development and inspector interfaces:

```bash
# Run in inspector / dev mode
fastmcp dev server.py

# Run standard MCP server over stdio
fastmcp run server.py
```

---

## Example Usage Scenarios

Once connected to your AI Assistant, you can ask prompts such as:

- *"What was my GPA in semester 20241?"*
- *"What is my current CPA, and how many cumulative credits have I passed?"*
- *"If I retake IT3040 and improve my grade from C to A, how will my overall CPA change?"*
- *"List all the courses I have taken in the IT department along with my grades."*

---

## License

This project is released under the [MIT License](LICENSE).
