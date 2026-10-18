#!/usr/bin/env bash
# Re-runs the choose.py tests from the 16 Oct session.
#   ./tests.sh           automated tests only (no browser, about 30 s)
#   ./tests.sh --clicks  then the tests that need a real click from you
# The copy-prompt paste test is round 3 of ./demo.sh.
cd "$(dirname "$0")" || exit 1

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FB=$(uv run --no-project python -c 'import tempfile; print(tempfile.gettempdir())')/choose-copy-prompt.html
pass=0; fail=0

check() {  # check NAME ACTUAL EXPECTED
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); echo "  pass  $1"
  else fail=$((fail + 1)); echo "  FAIL  $1: got [$2], expected [$3]"; fi
}
waitport() { for _ in $(seq 1 100); do curl -s -o /dev/null "http://localhost:${1:-8765}" && return; sleep 0.2; done; }
click() { curl -s -X POST --data-binary "$1" "http://localhost:${2:-8765}/choose"; }
jscheck() {  # node --check on the page's script; skipped if node is missing
  command -v node >/dev/null || { echo skipped; return; }
  sed -n '/<script>/,/<\/script>/p' "$1" | sed '1d;$d' > "$T/c.js"
  node --check "$T/c.js" 2>/dev/null && echo ok || echo FAIL
}
js_ok() { [ "$1" = skipped ] && echo ok || echo "$1"; }
run() { BROWSER=true uv run --no-project choose.py "$@"; }

if curl -s -o /dev/null http://localhost:8765; then
  echo "Port 8765 is in use. Stop that server first."; exit 1
fi
command -v node >/dev/null || echo "(node not found: page script checks skipped)"

echo "Handover tests"
run "Option A" "Option B" "Option C" > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click "Option B"; wait $P; ex=$?
check "1. fake click returns the option" "$(cat "$T/out")" "Option B"
check "1. exit code 0" "$ex" 0
check "2. one button per option" "$(grep -o '<button data-o=' "$T/page.html" | wc -l | tr -d ' ')" 3
check "2. page script is valid" "$(js_ok "$(jscheck "$T/page.html")")" ok

run "Tom's plan" "R&D" "Go 🚀" 'Say "hi"' "<b>x</b>" > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click 'Say "hi"'; wait $P
check "4. awkward text returns exactly" "$(cat "$T/out")" 'Say "hi"'
check "4. <b>x</b> shown as plain text" "$(grep -o '&lt;b&gt;x&lt;/b&gt;' "$T/page.html" | wc -l | tr -d ' ')" 2
run A B > "$T/out" 2>/dev/null & P=$!; waitport; click "Go 🚀"; wait $P
check "4. emoji survives" "$(cat "$T/out")" "Go 🚀"

run First > "$T/out1" 2>/dev/null & P1=$!; waitport
run Second > "$T/out2" 2> "$T/err2" & P2=$!
for _ in $(seq 1 50); do grep -q localhost "$T/err2" && break; sleep 0.2; done
port2=$(grep -o 'localhost:[0-9]*' "$T/err2" | cut -d: -f2)
waitport "$port2"; click First; click Second "$port2"; wait $P1; wait $P2
check "5. second copy moves off 8765" "$([ -n "$port2" ] && [ "$port2" != 8765 ] && echo moved)" moved
check "5. each copy gets its own answer" "$(cat "$T/out1") $(cat "$T/out2")" "First Second"

echo "Exit codes and --question"
run --timeout 1 --load-wait 5 A 2>/dev/null; check "timeout gives 3" $? 3
run --bad A 2>/dev/null; check "mistyped option gives 2" $? 2
run --question "Which plan for Q4?" A > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click A; wait $P
check "--question shown" "$(grep -c '<h2>Which plan for Q4?</h2>' "$T/page.html")" 1
run --question "Tom's <b>R&D</b> \"plan\" 🚀?" A > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click A; wait $P
check "awkward --question shown as plain text" "$(grep -c '&lt;b&gt;R&amp;D&lt;/b&gt;' "$T/page.html")" 1
run A > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click A; wait $P
check "no --question shows Pick one" "$(grep -c '<h2>Pick one</h2>' "$T/page.html")" 1
run > "$T/out" 2>/dev/null & P=$!
waitport; curl -s http://localhost:8765 > "$T/page.html"; click Yes; wait $P
check "no options shows Yes and No" "$(grep -o '<button data-o="[^"]*"' "$T/page.html" | tr '\n' ' ')" '<button data-o="Yes" <button data-o="No" '

echo "Flag combinations, normal page"
for mode in "" "--multi" "--other" "--multi --other"; do
  read -ra flags <<< "$mode"; rm -f "$FB"
  case "$mode" in *multi*) body='["R&D","Go 🚀"]'; want='["R&D", "Go 🚀"]';; *) body='Go 🚀'; want='Go 🚀';; esac
  run "${flags[@]}" "R&D" "Go 🚀" > "$T/out" 2>/dev/null & P=$!
  waitport; curl -s http://localhost:8765 > "$T/page.html"; click "$body"; wait $P; ex=$?
  check "[${mode:-none}] answer" "$(cat "$T/out")" "$want"
  check "[${mode:-none}] exit 0, no copy-prompt page" "$ex $([ -f "$FB" ] && echo fallback)" "0 "
  check "[${mode:-none}] page script is valid" "$(js_ok "$(jscheck "$T/page.html")")" ok
  check "[${mode:-none}] Other box only with --other" "$(grep -c 'id="other"' "$T/page.html")" "$([[ $mode == *other* ]] && echo 1 || echo 0)"
done

echo "Flag combinations, --fallback"
for mode in "" "--multi" "--other" "--multi --other"; do
  read -ra flags <<< "$mode"; rm -f "$FB"
  run --fallback "${flags[@]}" "R&D" "Go 🚀" > "$T/out" 2>/dev/null; ex=$?
  check "[${mode:-none}] exit 4, nothing on stdout" "$ex [$(cat "$T/out")]" "4 []"
  check "[${mode:-none}] copy-prompt page written" "$([ -f "$FB" ] && echo yes)" yes
  check "[${mode:-none}] page script is valid" "$(js_ok "$(jscheck "$FB")")" ok
  check "[${mode:-none}] tick boxes only with --multi" "$(grep -o checkbox "$FB" | wc -l | tr -d ' ')" "$([[ $mode == *multi* ]] && echo 2 || echo 0)"
done

echo "Fallback switching"
rm -f "$FB"; run --load-wait 2 --timeout 5 A B > "$T/out" 2>/dev/null; ex=$?
check "page never loaded: exit 4 and copy-prompt page" "$ex $([ -f "$FB" ] && echo yes)" "4 yes"
rm -f "$FB"; run --load-wait 1 --timeout 30 A B > "$T/out" 2>/dev/null & P=$!
sleep 3; click B; wait $P; ex=$?
check "late click still returns the answer" "$ex $(cat "$T/out") $([ -f "$FB" ] && echo yes)" "0 B yes"
rm -f "$FB"; run --load-wait 3 A B > "$T/out" 2>/dev/null & P=$!
waitport; sleep 4; click A; wait $P; ex=$?
check "page loaded in time: no copy-prompt page" "$ex $(cat "$T/out") $([ -f "$FB" ] && echo yes || echo no)" "0 A no"
{ echo 'def BLOCKED(*a): raise PermissionError(1, "Operation not permitted")'
  sed 's/http\.server\.HTTPServer((/BLOCKED((/' choose.py; } > "$T/blocked.py"
rm -f "$FB"; BROWSER=true uv run --no-project "$T/blocked.py" A B > "$T/out" 2>/dev/null; ex=$?
check "no port allowed: exit 4 and copy-prompt page" "$ex $([ -f "$FB" ] && echo yes)" "4 yes"
rm -f "$FB"

echo "Run straight from GitHub"
URL=https://raw.githubusercontent.com/jheyworth/uv-html-llm-cookbook-and-lab/main/choose.py
# A private repo needs a GitHub token: GITHUB_KEY if set, else the gh CLI's own login, if any.
KEY=${GITHUB_KEY:-$(gh auth token 2>/dev/null)}
RUN_URL=$URL; AUTH=()
if [ -n "$KEY" ]; then RUN_URL=${URL/https:\/\//https://x-access-token:$KEY@}; AUTH=(-H "Authorization: token $KEY"); fi
if curl -sf "${AUTH[@]}" -o "$T/remote.py" "$URL"; then
  BROWSER=true uv run --no-project "$RUN_URL" --question "Which plan?" "Plan A" "Plan B" > "$T/out" 2>/dev/null & P=$!
  waitport; click "Plan B"; wait $P; ex=$?
  check "uv runs choose.py from its GitHub address" "$ex $(cat "$T/out")" "0 Plan B"
  cmp -s "$T/remote.py" choose.py; check "GitHub copy matches this folder's choose.py" $? 0
else
  echo "  skipped (GitHub not reachable)"
fi

echo
echo "Automated: $pass passed, $fail failed."
[ "$1" = "--clicks" ] || exit $((fail > 0))

ask() {  # ask TEST WHAT-TO-DO -- choose.py args...
  local name=$1 todo=$2; shift 3
  echo; echo "$name"; echo "  $todo"
  answer=$(uv run --no-project choose.py --timeout 600 "$@" 2>/dev/null); ex=$?
  echo "  Came back: $answer (exit code $ex)"
  read -r -p "  Is that what you chose? [y/n] " ok
  if [ "$ok" = y ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "  FAIL  $name"; fi
}

echo; echo "Click tests: each opens a page in your browser. You have 10 minutes for each."
ask "3. Real click" "Click any plan." -- --question "Which plan?" "Plan A" "Plan B" "Plan C"
echo; echo "6. Link opened by hand"
echo "  No tab opens this time. Open http://localhost:8765 yourself."
echo "  Check the five buttons read exactly: Tom's plan, R&D, Go 🚀, Say \"hi\", <b>x</b> (not bold). Then click one."
answer=$(BROWSER=true uv run --no-project choose.py --timeout 600 "Tom's plan" "R&D" "Go 🚀" 'Say "hi"' "<b>x</b>" 2>/dev/null); ex=$?
echo "  Came back: $answer (exit code $ex)"
read -r -p "  Did the buttons look right, and is that what you clicked? [y/n] " ok
if [ "$ok" = y ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "  FAIL  6. Link opened by hand"; fi
ask "--multi" "Tick two or three plans, then press Submit." -- --multi --question "Which plans should we keep?" "Plan A" "Plan B" "Plan C" "Plan D"
ask "--other" "Type a place in the Other box and press Enter." -- --other --question "Where should we meet?" "Office" "Café"
ask "--multi --other" "Tick one or two, type your own in Other, then press Submit." -- --multi --other --question "Which snacks for the meeting?" "Biscuits" "Fruit" "Crisps"

echo
echo "All tests: $pass passed, $fail failed. For the copy-prompt paste test, run ./demo.sh (round 3)."
exit $((fail > 0))
