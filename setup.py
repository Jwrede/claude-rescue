from setuptools import setup

setup(
    name="claude-rescue",
    version="0.1.0",
    description="Diagnose and recover corrupted Claude Code session JSONL files",
    py_modules=["claude_rescue"],
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "claude-rescue=claude_rescue:main",
        ],
    },
)
