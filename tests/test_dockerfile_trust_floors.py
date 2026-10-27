"""כל שלב ב-``Dockerfile`` מעדכן את מאגרי התעודות שלו לפני שהוא מוריד משהו.

**מה זה בא למנוע.** ב-pip 26.2.2 כל הורדה נבדקת גם מול certifi שה-pip מביא
בתוכו וגם מול ``ca-certificates`` של מערכת ההפעלה (ההסבר המלא בהערות שמעל
``PIP_MIN_VERSION`` ו-``CA_CERTIFICATES_MIN_VERSION`` בראש ה-``Dockerfile``).
רצפה נכונה לא מספיקה אם היא מגיעה מאוחר: עד התיקון, שלב הייצור התקין את
Playwright עם ה-pip של תמונת הבסיס, ורק כמה שכבות אחר כך שדרג את pip.

**שתי הבדיקות הראשונות הן בדיקות מקור, וזה מכוון.** בנייה של התמונה לא רצה
כאן, ומה שצריך לתפוס הוא שלב חדש, או ``pip install`` חדש, שנכתב לפני השדרוג.
הבדיקה השלישית מריצה את בדיקת הגרסה של ``ca-certificates`` כפי שהיא כתובה
בקובץ, מול ``dpkg`` אמיתי.

הערכים עצמם לא מועתקים לכאן: הבדיקות קוראות אותם מה-``ARG`` שבראש הקובץ.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
_PIP_UPGRADE = '"pip>=${PIP_MIN_VERSION}"'
_CA_CHECK = 'dpkg --compare-versions "$ca_version" ge "$CA_CERTIFICATES_MIN_VERSION"'
_CA_GUARD = ': "${CA_CERTIFICATES_MIN_VERSION'


def _instructions(text: str) -> list[str]:
    """הוראות לוגיות: שורות המשך מחוברות, ושורות הערה מושמטות כמו ש-Docker משמיט אותן."""
    instructions: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            current.append(line[:-1])
            continue
        current.append(line)
        joined = " ".join(part.strip() for part in current).strip()
        if joined:
            instructions.append(joined)
        current = []
    return instructions


def _global_args_and_stages() -> tuple[list[str], list[tuple[str, list[str]]]]:
    instructions = _instructions(_DOCKERFILE.read_text(encoding="utf-8"))
    global_args: list[str] = []
    stages: list[tuple[str, list[str]]] = []
    for instruction in instructions:
        if instruction.startswith("FROM "):
            stages.append((instruction, []))
        elif stages:
            stages[-1][1].append(instruction)
        else:
            global_args.append(instruction)
    return global_args, stages


def _global_default(name: str) -> str:
    global_args, _ = _global_args_and_stages()
    prefix = f"ARG {name}="
    values = [arg.removeprefix(prefix) for arg in global_args if arg.startswith(prefix)]
    message = f"{name} needs one ARG with a value before the first FROM"
    assert len(values) == 1 and values[0], message
    return values[0]


def _declared_before(stage: list[str], name: str, index: int) -> bool:
    return any(instruction == f"ARG {name}" for instruction in stage[:index])


def _is_run(instruction: str, command: str) -> bool:
    return instruction.startswith("RUN ") and command in instruction


def test_every_stage_upgrades_pip_to_the_floor_before_its_first_pip_install():
    _global_default("PIP_MIN_VERSION")
    _, stages = _global_args_and_stages()
    checked = []
    for header, stage in stages:
        pip_runs = [i for i, ins in enumerate(stage) if _is_run(ins, "pip install")]
        if not pip_runs:
            continue
        first = pip_runs[0]
        upgrades = "--upgrade" in stage[first] and _PIP_UPGRADE in stage[first]
        assert upgrades, f"{header}: the first pip install must upgrade pip, got: {stage[first]}"
        redeclared = _declared_before(stage, "PIP_MIN_VERSION", first)
        assert redeclared, f"{header}: ARG PIP_MIN_VERSION must be redeclared before it is used"
        checked.append(header)
    assert checked, "no stage runs pip install; the check above looked at nothing"


def test_every_stage_that_installs_apt_packages_checks_the_ca_certificates_floor():
    _global_default("CA_CERTIFICATES_MIN_VERSION")
    _, stages = _global_args_and_stages()
    checked = []
    for header, stage in stages:
        for index, instruction in enumerate(stage):
            if not _is_run(instruction, "apt-get install"):
                continue
            assert " ca-certificates " in instruction, f"{header}: install ca-certificates"
            assert _CA_CHECK in instruction, f"{header}: check CA_CERTIFICATES_MIN_VERSION"
            redeclared = _declared_before(stage, "CA_CERTIFICATES_MIN_VERSION", index)
            assert redeclared, f"{header}: ARG CA_CERTIFICATES_MIN_VERSION must be redeclared"
            checked.append(header)
    assert checked, "no stage runs apt-get install; the check above looked at nothing"


@pytest.mark.skipif(
    shutil.which("dpkg") is None or shutil.which("sh") is None, reason="needs dpkg and sh"
)
def test_the_ca_certificates_check_lets_the_floor_through_and_stops_an_older_one(tmp_path):
    floor = _global_default("CA_CERTIFICATES_MIN_VERSION")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_query = fake_bin / "dpkg-query"
    fake_query.write_text('#!/bin/sh\necho "$FAKE_CA_VERSION"\n', encoding="utf-8")
    fake_query.chmod(0o755)

    _, stages = _global_args_and_stages()
    checks = [ins[ins.index(_CA_GUARD) :] for _, st in stages for ins in st if _CA_GUARD in ins]
    assert checks, "no ca-certificates check found in the Dockerfile"

    # ב-Debian "~" ממיין לפני כל דבר, ולכן "<floor>~" היא הגרסה שמתחת לרצפה בדיוק.
    cases = {floor: 0, f"{floor}+1": 0, f"{floor}~": 1, "0": 1}
    for number, check in enumerate(checks):
        script = tmp_path / f"check_{number}.sh"
        script.write_text(f"set -eu\n{check}\n", encoding="utf-8")
        for installed, expected in cases.items():
            env = {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_CA_VERSION": installed,
                "CA_CERTIFICATES_MIN_VERSION": floor,
            }
            result = subprocess.run(
                ["sh", str(script)], env=env, capture_output=True, text=True, timeout=10
            )
            assert result.returncode == expected, (installed, result.returncode, result.stderr)
            if expected:
                assert "is older than" in result.stderr
