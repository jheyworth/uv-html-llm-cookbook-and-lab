# Usage: uv run --no-project menu.py
# Opens a menu page with one button per choose.py test. The clicked test is
# printed as a prompt for the agent to carry out; that prompt ends by opening
# the menu again, until the person clicks Finish.
import os, shlex, subprocess, sys, tempfile, urllib.request
from pathlib import Path

REPO = "https://raw.githubusercontent.com/jheyworth/uv-html-llm-cookbook-and-lab/main/"
here = Path(__file__).with_name("choose.py")
if here.exists():  # run from a clone: use the files beside this one
    choose_path, CHOOSE, MENU = here, f"uv run --no-project {shlex.quote(str(here))}", \
        f"uv run --no-project {shlex.quote(str(Path(__file__)))}"
else:  # run from GitHub: fetch choose.py once
    choose_path = Path(tempfile.gettempdir()) / "menu-choose.py"
    choose_path.write_bytes(urllib.request.urlopen(REPO + "choose.py", timeout=30).read())
    CHOOSE, MENU = f"uv run --no-project {REPO}choose.py", f"uv run --no-project {REPO}menu.py"


def cmd(*args):
    return CHOOSE + " " + " ".join(shlex.quote(a) for a in args)


TESTS = {
    "One choice": (cmd("--timeout", "3600", "--question", "Which plan?", "Plan A", "Plan B", "Plan C"), ""),
    "Several choices": (cmd("--timeout", "3600", "--multi", "--question", "Which plans should we keep?",
                            "Plan A", "Plan B", "Plan C", "Plan D"), ""),
    "Your own answer": (cmd("--timeout", "3600", "--other", "--question", "Where should we meet?",
                            "Office", "Café"), ""),
    "Several choices plus your own": (cmd("--timeout", "3600", "--multi", "--other", "--question",
                                          "Which snacks?", "Biscuits", "Fruit", "Crisps"), ""),
    "Awkward text": (cmd("--timeout", "3600", "--question", "Do these read right?",
                         "Tom's plan", "R&D", "Go 🚀", 'Say "hi"', "<b>x</b>"), ""),
    "Copy-prompt page": (cmd("--fallback", "--question", "Which day suits you?", "Monday", "Wednesday", "Friday"),
                         " It exits with code 4 straight away: wait for the person to paste their answer into the chat."),
    "Nobody answers": (cmd("--timeout", "10", "--question", "Leave this unanswered", "A", "B"),
                       " Expect exit code 3 after 10 seconds."),
}

p = subprocess.run([sys.executable, str(choose_path), "--timeout", "3600", "--question", "Which test?",
                    *TESTS, "Finish"], stdout=subprocess.PIPE, text=True, encoding="utf-8",
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
picked = p.stdout.strip()
if p.returncode == 4:
    print(f"The menu switched to its copy-prompt page. When the person pastes which test they want, "
          f"run it in the background: {' | '.join(f'{k}: {c}' for k, (c, _) in TESTS.items())}. "
          f"Then tell them what came back and its exit code, and open the menu again: {MENU}")
elif p.returncode or not picked:
    sys.exit(p.returncode or 1)
elif picked == "Finish":
    print("The person clicked Finish. Stop the test menu.")
else:
    command, note = TESTS[picked]
    print(f'Test "{picked}": run this in the background and wait for the person\'s answer: {command}{note} '
          f"Then tell them in one line what came back and its exit code, "
          f"and open the menu again by running in the background: {MENU}")
