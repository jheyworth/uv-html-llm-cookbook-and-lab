#!/usr/bin/env bash
# Walks through choose.py in three short rounds, using the real script.
# Run from anywhere: ./demo.sh
cd "$(dirname "$0")" || exit 1

show() {  # print what an agent would receive
  echo
  echo "  The agent received:  $1"
  echo "  Exit code:           $2"
  echo
}

pause() { read -r -p "Press Enter to continue... "; echo; }

echo "choose.py demo: three rounds, about a minute in all."
echo "Each round opens a page in your browser. Answer it there."
echo
pause

echo "Round 1 of 3: one choice"
echo "Click one colour in the browser."
answer=$(uv run --no-project choose.py --timeout 120 --question "Pick a colour" "Red" "Green" "Blue")
show "$answer" $?
pause

echo "Round 2 of 3: several choices plus your own"
echo "Tick one or more fruits, type your own in 'Other...', then press Submit."
answer=$(uv run --no-project choose.py --timeout 120 --multi --other --question "Which fruits do you like?" "Apples" "Pears" "Plums")
show "$answer" $?
pause

echo "Round 3 of 3: the copy-prompt fallback (used when the browser can't reach the script)"
echo "Click a day in the browser. Then come back here, paste the copied prompt and press Enter."
uv run --no-project choose.py --fallback --question "Which day suits you?" "Monday" "Wednesday" "Friday" 2>/dev/null
code=$?
read -r -p "Paste here: " pasted
show "$pasted" $code

echo "Demo finished. In real use the agent runs these commands and reads the answer."
