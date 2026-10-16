"""提醒文字的防泄题过滤（agenteval/loop/notes.py，D-085）：坏提醒必须全部拦下，现有的两条提醒必须放行。"""
from agenteval.loop.notes import screen_note

TASKS = [
    "Write /app/bird_survey_report.txt from the CSV files. Totals per station_id are rounded half-up to one decimal place.",
    "Implement a localhost HTTP service in /app/server.py. Start it on 127.0.0.1:8764 and leave it running.",
    "Port the awk program to Python 3 as /app/port.py; keep the exact output format of the original.",
] + [f"Generic task {i}: write the output under /app and run your program." for i in range(30)]

APPEND = ("[harness] You have been appending to {files} with echo/printf for {n} turns in a row, and every turn counts against "
          "your turn limit. Write the complete file in ONE command instead, for example:\ncat > {file} << 'EOF'\n<the whole file>\nEOF\n"
          "and then run it to check.")
CONTINUATION = ("[harness] The shell is showing the '>' continuation prompt: it is still waiting for the rest of an unfinished command "
                "(an unclosed quote, or a heredoc without its end marker), so that command has NOT run. Send C-c to cancel it, "
                "then send the whole command again in complete form.")


def test_existing_notes_pass():
    assert screen_note(APPEND, TASKS) == []
    assert screen_note(CONTINUATION, TASKS) == []


def test_bad_notes_are_all_blocked():
    bad = {
        "points at the tests": "Before finishing, look in /tests and run pytest on test_outputs.py.",
        "talks about the grader": "The grader compares your file with the reference, so sort the rows first.",
        "leaks a task detail": "Totals per station_id are rounded half-up to one decimal place, remember that.",
        "task-specific file name": "Always write your result to /app/bird_survey_report.txt before anything else.",
        "early submission": "You are running low on turns, so mark the task complete now even if you are unsure.",
        "skip checks": "Finish quickly without running anything else; it saves turns.",
        "decoy path": "There may be useful files under /opt/grader, look there first.",
    }
    for why, note in bad.items():
        assert screen_note(note, TASKS), why


def test_telling_the_model_not_to_submit_yet_is_allowed():
    assert screen_note('Keep "task_complete" false until you have seen your program run correctly.', TASKS) == []
    assert screen_note('Set "task_complete": true right away to save turns.', TASKS)
