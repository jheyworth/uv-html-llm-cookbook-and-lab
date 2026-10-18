# Usage: uv run --no-project menu.py [--port PORT] [--timeout SECONDS] [--key GITHUB_TOKEN]
# Opens a test page: a left menu with one item per choose.py test, and the
# real choose.py page for the selected test in the main pane. Once the person
# answers, this script prints the result as a prompt for the agent and exits.
# The prompt ends by offering to reopen the page in a new tab; the old tab
# closes itself, or greys out if the browser won't let it close.
import argparse, http.server, json, os, re, secrets, shlex, subprocess, sys, tempfile, threading, \
    urllib.request, webbrowser
from pathlib import Path

REPO = "https://raw.githubusercontent.com/jheyworth/uv-html-llm-cookbook-and-lab/main/"
parser = argparse.ArgumentParser()
parser.add_argument("--timeout", type=float, default=3600, help="seconds before the page stops (default 3600)")
parser.add_argument("--port", type=int, default=8764, help="port for the test page (default 8764)")
parser.add_argument("--reopen", action="store_true", help="keep the done marks from earlier tests")
parser.add_argument("--key", help="GitHub token, for when the repo is private: used for this script's own downloads")
args = parser.parse_args()


def fetch(path):
    # Downloads one file from the repo; with --key, the token goes in a header, never in an address.
    headers = {"Authorization": f"token {args.key}"} if args.key else {}
    return urllib.request.urlopen(urllib.request.Request(REPO + path, headers=headers), timeout=30).read()

here = Path(__file__).with_name("choose.py")
if here.exists():  # run from a clone: use the files beside this one
    choose_path = here
    CHOOSE = f"uv run --no-project {shlex.quote(str(here))}"
    MENU = f"uv run --no-project {shlex.quote(str(Path(__file__)))}"
else:  # run from GitHub: fetch choose.py once
    choose_path = Path(tempfile.gettempdir()) / "menu-choose.py"
    choose_path.write_bytes(fetch("choose.py"))
    CHOOSE, MENU = f"uv run --no-project {REPO}choose.py", f"uv run --no-project {REPO}menu.py"
    if args.key:  # reopening needs the key too; commands shown on the page never include it
        keyed = REPO.replace("https://", f"https://x-access-token:{args.key}@")
        MENU = f"uv run --no-project {keyed}menu.py --key {shlex.quote(args.key)}"
# The local-file test needs a picture on this machine: the clone's own copy, or one fetched once.
local_diagram = Path(__file__).with_name("assets") / "how-it-works.svg"
if not local_diagram.exists():
    local_diagram = Path(tempfile.gettempdir()) / "menu-how-it-works.svg"
    local_diagram.write_bytes(fetch("assets/how-it-works.svg"))
# The flowchart page this menu serves at /flowchart: the clone's own copy, or one fetched once from GitHub.
flowchart = Path(__file__).with_name("assets") / "greenfield-flowchart.html"
if not flowchart.exists():
    flowchart = Path(tempfile.gettempdir()) / "menu-greenfield-flowchart.html"
    flowchart.write_bytes(fetch("assets/greenfield-flowchart.html"))
# A browser can't send the key, so with --key the pictures come through this menu at /asset/<name>.
ASSET = "__MENU__/asset/" if args.key else REPO + "assets/"
ASSET_TYPES = {".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml"}
asset_cache = {}
# Drawn by the LLM for the "drawn by the LLM" test: an agent would write this SVG itself.
CHART = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 200" font-family="Helvetica, Arial, sans-serif">'
         '<text x="10" y="20" font-size="14" fill="#8b96a5">Sign-ups this week</text>'
         '<rect x="40" y="110" width="70" height="60" fill="#8b96a5"/><rect x="145" y="50" width="70" height="120" fill="#5fd38d"/>'
         '<rect x="250" y="80" width="70" height="90" fill="#8b96a5"/><path d="M20 170H340" stroke="#8b96a5"/>'
         '<g font-size="13" fill="#8b96a5" text-anchor="middle"><text x="75" y="190">Tuesday</text>'
         '<text x="180" y="190">Wednesday</text><text x="285" y="190">Thursday</text></g></svg>')

MEANING = {0: "answered", 2: "command typed wrong", 3: "nobody answered in time",
           4: "switched to the copy-prompt page"}
TESTS = [
    dict(id="one", name="Multiple choice", todo="Click one choice.",
         args=["--timeout", "3600", "--question", "Which one?", "Choice A", "Choice B", "Choice C"]),
    dict(id="multi", name="Several choices", todo="Tick two or three, then press Submit.",
         args=["--timeout", "3600", "--multi", "--question", "Which ones?",
               "Choice A", "Choice B", "Choice C", "Choice D"]),
    dict(id="other", name="Your own answer", todo="Type anything in the Other box and press Enter.",
         args=["--timeout", "3600", "--other", "--question", "Where should we meet?", "Office", "Café"]),
    dict(id="multi-other", name="Several plus your own",
         todo="Tick one or two, type your own in Other, then press Submit.",
         args=["--timeout", "3600", "--multi", "--other", "--question", "Which snacks?",
               "Biscuits", "Fruit", "Crisps"]),
    dict(id="awkward", name="Awkward text",
         todo="Check each button reads exactly as written, with <b>x</b> not in bold, then click one.",
         args=["--timeout", "3600", "--question", "Do these read right?",
               "Tom's plan", "R&D", "Go 🚀", 'Say "hi"', "<b>x</b>"]),
    dict(id="fallback", name="Copy-prompt page", copy=True,
         todo="This is the page used when the browser can't reach the script. Click a day: it copies a prompt. "
              "Then press \"I've copied it\" below.",
         args=["--fallback", "--question", "Which day suits you?", "Monday", "Wednesday", "Friday"]),
    dict(id="timeout", name="Nobody answers", todo="Don't click anything. It gives up after 10 seconds.",
         args=["--timeout", "10", "--question", "Leave this unanswered", "A", "B"]),
    dict(id="png", group="Rich content", name="Picture (PNG)",
         proves="A question can come with a real screenshot.",
         how="The agent passes a web address with --image. The address points to a PNG in this project's GitHub "
             "repo, and the browser loads it like any picture on a web page. Nothing is installed; the picture just "
             "needs an internet connection.",
         todo="Look at the screenshot, then answer.",
         args=["--timeout", "3600", "--image", ASSET + "chat-and-page.png",
               "--question", "After you answer, which window do you switch back to?", "The chat", "The browser", "Neither"]),
    dict(id="gif", group="Rich content", name="Animated GIF",
         proves="A short looping clip can show a task step by step, the way training material does.",
         how="An animated GIF loads exactly like the PNG: a web address passed with --image. The browser plays the "
             "loop on its own; no player or extra code is needed.",
         todo="Watch the loop once or twice, then answer.",
         args=["--timeout", "3600", "--image", ASSET + "flow.gif",
               "--question", "What do you do after you answer on the page?",
               "Switch back to the chat", "Wait for the page to move on", "Reload the page"]),
    dict(id="svg", group="Rich content", name="Vector diagram (SVG)",
         proves="A diagram can explain how something is built, and stays sharp at any size.",
         how="The agent runs uv run choose.py with a question and the options. choose.py starts a small web server "
             "on your own machine (address 127.0.0.1, port 8765 or a free one) and opens this page in your browser. "
             "Nothing goes to a cloud service. This test page is a wrapper around choose.py: it runs the same script "
             "and shows its page in the frame below.",
         todo="Follow the diagram from left to right, then answer.",
         args=["--timeout", "3600", "--image", ASSET + "how-it-works.svg",
               "--question", "Which part runs on your own machine?",
               "choose.py's small web server", "A cloud service", "GitHub"]),
    dict(id="svg-anim", group="Rich content", name="Animated diagram (SVG)",
         proves="Movement can show the order things happen in.",
         how="When you click an answer, the page sends it to choose.py on your machine. choose.py prints the answer "
             "as plain text and stops, with an exit code that says how it ended (0 means answered). The agent reads "
             "that printed text, which is how your answer reaches the chat. The animation is built into the SVG file "
             "itself, so no scripts run.",
         todo="Watch the answer travel, then answer.",
         args=["--timeout", "3600", "--image", ASSET + "answer-path.svg",
               "--question", "How does your answer reach the chat?",
               "choose.py prints it for the agent", "The page emails it", "You type it into the chat"]),
    dict(id="local", group="Rich content", name="Picture from a local file",
         proves="The agent can use pictures from your own project, with no internet needed for the picture.",
         how="The agent passes a file path with --image instead of a web address. choose.py reads the file and puts "
             "the picture into the page itself, so the browser needs nothing else. A GitHub link, by contrast, needs "
             "the internet, and GitHub can take up to 5 minutes to show a changed picture.",
         todo="This is the same diagram as the vector test, loaded from a file on your machine. Answer when ready.",
         args=["--timeout", "3600", "--image", str(local_diagram),
               "--question", "Which kind of picture still shows without the internet?",
               "A local file", "A GitHub link", "A YouTube video"]),
    dict(id="drawn", group="Rich content", name="Drawn by the LLM",
         proves="The LLM can draw a picture to fit the question, on the spot.",
         how="The agent writes the SVG itself and passes the text with --image. choose.py shows it as a picture, "
             "never as part of the page, so even if the drawing contained code it could not run. This only works for "
             "vector drawings, not photos.",
         todo="Read the chart, then answer.",
         args=["--timeout", "3600", "--image", CHART, "--question", "Which bar is tallest?",
               "Tuesday", "Wednesday", "Thursday"]),
    dict(id="video", group="Rich content", name="YouTube video",
         proves="A question can come with a full video walkthrough.",
         how="The agent passes only the video's ID with --video, never the page code for a player. choose.py builds "
             "the player itself, using youtube-nocookie.com, YouTube's privacy-enhanced player. It needs the "
             "internet, and YouTube shows its own branding.",
         todo="Play a few seconds, then answer.",
         args=["--timeout", "3600", "--video", "Cf19iCXTzII", "--question", "What is this episode about?",
               "Running BMad in teams", "Installing Python", "Cooking pasta"]),
    dict(id="blog", group="Rich content", name="Blog post",
         proves="A question can come with reading material, here a BMad Code blog post.",
         how="The agent passes an https:// address with --page. choose.py shows the page in a sandboxed frame: the "
             "page can run and scroll, but cannot take over this page. Some sites block being shown in a frame; "
             "those show up blank.",
         todo="Scroll the post, then answer.",
         args=["--timeout", "3600", "--page",
               "https://blog.bmadcode.com/blog/your-ai-should-be-arguing-with-you-and-making-you-sweat/",
               "--question", "What does the post say your AI should do?",
               "Argue with you", "Agree with everything", "Stay quiet"]),
    dict(id="docs", group="Rich content", name="Docs page",
         proves="Integrated help: the agent opens the exact docs page you need, right next to the question.",
         how="The same --page option as the blog post test, pointing at a page of the BMad Method docs. The docs "
             "stay live, so the help is always the current version.",
         todo="Scroll the page, then answer.",
         args=["--timeout", "3600", "--page", "https://docs.bmad-method.org/plan/set-up-the-ticket-tree/",
               "--question", "What does this page help you set up?",
               "The ticket tree", "A web server", "A YouTube channel"]),
    dict(id="bmad-install", group="BMad", name="1. Install BMad",
         proves="The page hands you the exact command: copy it, paste it, done.",
         steps=["Click the Copy button.", "Open a terminal in your project folder.",
                "Paste what's on the clipboard into the terminal and press Enter to run it.",
                "Switch back to this page and say how it went, below."],
         run="npx skills add bmad-code-org/BMAD-METHOD -y",
         todo="Copy, paste, run, then answer below. If you got an error, paste it into Other.",
         args=["--timeout", "3600", "--other", "--question", "How did the install go?", "It worked", "I got an error"]),
    dict(id="bmad-setup", group="BMad", name="2. Set up BMad",
         proves="The page asks; your LLM session does the work. One click here, and the session runs the step.",
         how="Click Yes. Your answer goes back to your chat session, which runs bmad setup for you. Setup gets the "
             "folder ready for BMad's skills. Then switch back to your session to see what it did.",
         todo="Click Yes, then switch back to your session.",
         yes="Yes, run bmad setup",
         act="Use the bmad skill to run bmad setup in this project, and show the person what it did. " + "If you can't find the skill, tell the person that skills installed during a session may only load in a new one, so they should open a new session in this folder and paste the menu prompt again. If you are blocked from running it, say so and ask the person to tell you in the chat to go ahead.",
         args=["--timeout", "3600", "--question", "Run bmad setup now?", "Yes, run bmad setup", "Not now"]),
    dict(id="bmad-po", group="BMad", name="3. Get help on the PO agent",
         proves="You can ask any BMad skill to explain itself, in plain words, right after its name.",
         how="Click Yes. Your chat session calls Sofia, the PO agent, as /bmad-agent-po please show me a FAQ on "
             "what the PO Agent can do, and shows you her FAQ. To get help on any other skill, type its name and "
             "your request in your chat the same way.",
         todo="Click Yes, then switch back to your session and read Sofia's answer.",
         yes="Yes, ask Sofia",
         act="Run the bmad-agent-po skill with this request: `please show me a FAQ on what the PO Agent can do`. "
             "Show the person her answer. " + "If you can't find the skill, tell the person that skills installed during a session may only load in a new one, so they should open a new session in this folder and paste the menu prompt again. If you are blocked from running it, say so and ask the person to tell you in the chat to go ahead.",
         args=["--timeout", "3600", "--question", "Ask Sofia, the PO agent, for her FAQ now?", "Yes, ask Sofia", "Not now"]),
    dict(id="bmad-customize", group="BMad", name="4. Customize Sofia",
         proves="A real choice, made on the page: tick the rules you want, and the session sets them up.",
         how="Tick one or more rules, or write your own in Other, then press Submit. Your chat session uses the "
             "bmad-customize skill to save them as rules Sofia, the PO agent, always follows, in a small file under "
             "_bmad/custom/. Run step 3 again to see her follow them.",
         todo="Tick, press Submit, then switch back to your session.",
         act="Use the bmad-customize skill to add these rules to Sofia, the PO agent (bmad-agent-po), as persistent "
             "facts: {answer}. Show the person the file it wrote. " + "If you can't find the skill, tell the person that skills installed during a session may only load in a new one, so they should open a new session in this folder and paste the menu prompt again. If you are blocked from running it, say so and ask the person to tell you in the chat to go ahead.",
         args=["--timeout", "3600", "--multi", "--other", "--question", "What should Sofia always do?",
               "Write tickets in British English", "Keep every ticket under 200 words",
               "Ask before slicing an epic into stories"]),
    dict(id="greenfield-start", group="Greenfield project", name="Get started",
         proves="One question to BMad's own help gets a new project going, step by step.",
         how="Click Yes. Your chat session asks the bmad skill, BMad's built-in help: /bmad Help me set up a new "
             "Greenfield Project. It looks at your project and tells you where to start and what comes next.",
         todo="Click Yes, then switch back to your session.",
         yes="Yes, ask bmad",
         act="Run the bmad skill with this request: `Help me set up a new Greenfield Project`. Show the person its "
             "answer. " + "If you can't find the skill, tell the person that skills installed during a session may only load in a new one, so they should open a new session in this folder and paste the menu prompt again. If you are blocked from running it, say so and ask the person to tell you in the chat to go ahead.",
         args=["--timeout", "3600", "--question", "Ask bmad how to start a new greenfield project?",
               "Yes, ask bmad", "Not now"]),
    dict(id="greenfield-flowchart", group="Greenfield project", name="Workflow flowchart",
         proves="A whole interactive page can come with a question, served from a plain GitHub repo.",
         how="The flowchart is an HTML page in this project's GitHub repo. GitHub serves it as plain text, so it "
             "can't be linked to directly; instead this test page downloads it and serves it itself, from your "
             "machine, at /flowchart. choose.py shows it in a frame like any web page. Click any command in it to "
             "copy it.",
         todo="Read the flowchart, then answer.",
         args=["--timeout", "3600", "--page", "__MENU__/flowchart",
               "--question", "With a vague notion, which phase do you start in?", "Clarify", "Plan", "Build & Verify"]),
]
BY_ID = {t["id"]: t for t in TESTS}
TOKEN = secrets.token_hex(4)  # tells an old tab that a new menu has started
lock = threading.Lock()
cur = {"test": None, "proc": None, "port": None, "copy_page": None}
state = {"status": "idle"}
delivered = threading.Event()

# Colours and type from bmadcode.com (dark bands), with its light colours for the toggle.
THEME = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#111418;--panel:#1a1e24;--line:#2e353e;--line-2:#404854;--fg:#fff;--muted:#a2acb9;--muted-2:#7f8a99;
--accent:#0f35e0;--accent-fg:#fff;--ok:#5fd38d;--bad:#ff7a70;color-scheme:dark;
--sans:Archivo,-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
:root[data-theme="light"]{--bg:#fff;--panel:#f6f7f9;--line:#d3d8de;--line-2:#b6bdc7;--fg:#000;--muted:#5f6b7c;
--muted-2:#7c8797;--ok:#1d7a3a;--bad:#c1271d;color-scheme:light}
body{background:var(--bg);color:var(--fg);font-family:var(--sans)}
button,input,textarea{font-family:var(--sans);border-radius:2px}
button{background:var(--panel);color:var(--fg);border:1px solid var(--line-2);transition:border-color .18s,background-color .18s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.5;cursor:default}
button:focus-visible,input:focus-visible,label:focus-within{outline:2px solid var(--accent);outline-offset:2px}
#go{background:var(--accent);border-color:var(--accent);color:var(--accent-fg)}
/* Raised answer buttons (option D): soft blue border, a deeper bottom edge, a shadow; they press down on click. */
:root{--btn-top:#2b313a;--btn-bot:#1e232a;--btn-line:#5b7fd6;--btn-edge:#2f4a8f;--btn-shadow:rgba(0,0,0,.55)}
:root[data-theme="light"]{--btn-top:#ffffff;--btn-bot:#eef1f5;--btn-line:#5b7fd6;--btn-edge:#3f63bf;--btn-shadow:rgba(20,30,50,.18)}
body>button,#go,.primary,.copy{background:linear-gradient(var(--btn-top),var(--btn-bot));color:var(--fg);
border:1.5px solid var(--btn-line);border-bottom:5px solid var(--btn-edge);border-radius:6px;
box-shadow:0 4px 10px var(--btn-shadow);transition:transform .1s,box-shadow .1s,border-bottom-width .1s}
body>button:hover:not(:disabled),#go:hover:not(:disabled),.primary:hover,.copy:hover{filter:brightness(1.12);
border-color:var(--btn-line);border-bottom-color:var(--btn-edge)}
body>button:active:not(:disabled),#go:active:not(:disabled),.primary:active,.copy:active{transform:translateY(3px);
border-bottom-width:2px;box-shadow:0 1px 3px var(--btn-shadow)}
label{border:1px solid var(--line-2)!important;border-radius:2px!important;background:var(--panel)}
input,textarea{background:var(--panel);color:var(--fg);border:1px solid var(--line-2)}
</style>
<script>try{if(localStorage.getItem('menu-theme')==='light')document.documentElement.dataset.theme='light'}catch(e){}</script>"""


def run_test(t):
    with lock:
        old, cur["proc"] = cur["proc"], None  # so its watcher ignores it
        if old and old.poll() is None:
            old.terminate()
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "BROWSER": "true"}  # the menu shows the page
        p = subprocess.Popen([sys.executable, str(choose_path), *(a.replace("__MENU__", url) for a in t["args"])], env=env, text=True,
                             encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cur.update(test=t, proc=p, port=None, copy_page=None)
        state.clear(); state.update(status="running", id=t["id"])
        for line in p.stderr:  # wait until choose.py says where its page is
            if m := re.search(r"localhost:(\d+)", line):
                cur["port"] = int(m.group(1)); break
            if line.startswith("Copy-prompt page: "):
                cur["copy_page"] = Path(line.split(": ", 1)[1].strip()); break
    threading.Thread(target=watch, args=(t, p), daemon=True).start()


def watch(t, p):
    p.stderr.read()
    answer, code = p.stdout.read().strip(), p.wait()
    if cur["proc"] is not p or t.get("copy"):  # replaced by another test, or waiting for "I've copied it"
        return
    finish(t, answer, code)


def finish(t, answer, code):
    state.update(status="done", answer=answer, code=code, meaning=MEANING.get(code, "unexpected"))
    def stop():
        delivered.wait(3)  # let the page show the result before the server goes
        server.shutdown()
    threading.Thread(target=stop, daemon=True).start()


SHELL = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LLM + HTML GUI Integration: Proof of Concept</title>__THEME__
<style>
*{box-sizing:border-box} body{margin:0;line-height:1.5}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.top h1{margin:2px 0 0;font-size:20px;font-weight:600;letter-spacing:-.012em}
#theme{padding:6px 12px;font-size:13px;cursor:pointer}
.wrap{display:grid;grid-template-columns:260px 1fr;min-height:calc(100vh - 71px)}
nav{border-right:1px solid var(--line);padding:16px 12px;display:flex;flex-direction:column;gap:6px}
nav{gap:8px} .grp-sec{display:flex;flex-direction:column;gap:2px}
nav button.grp{font-family:var(--mono);font-size:13px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--fg);
background:var(--line);border:0;border-radius:0;padding:9px 10px;margin:0 -12px;width:calc(100% + 24px);justify-content:flex-start;gap:10px;cursor:pointer}
nav button.grp:hover:not(:disabled){background:var(--line-2);border-color:transparent}
.grp .arrow{display:inline-block;width:10px;transition:transform .15s} .grp-sec.open .grp .arrow{transform:rotate(90deg)}
.grp .count{margin-left:auto;font-weight:500;color:var(--muted)}
.grp-sec .items{display:none;flex-direction:column;gap:2px;padding:4px 0 6px} .grp-sec.open .items{display:flex}
nav button{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;padding:6px 12px;font-size:14px;
cursor:pointer;background:transparent;border:1px solid transparent;border-left:3px solid transparent}
nav button:hover:not(:disabled){background:var(--panel);border-color:var(--line)}
nav button[aria-current="true"]{background:var(--panel);border-color:var(--line);border-left-color:var(--accent);font-weight:600}
nav .tick{font-family:var(--mono);font-size:12px;color:var(--ok)}
main{padding:24px clamp(16px,3vw,40px);min-width:0}
main h2{margin:0 0 4px;font-size:24px;font-weight:600;letter-spacing:-.012em}
.todo{margin:0 0 16px;color:var(--muted);max-width:60ch}
iframe{display:block;width:100%;height:480px;border:1px solid var(--line);border-radius:2px;background:var(--bg)}
.cmd{font-family:var(--mono);font-size:12px;color:var(--muted-2);margin-top:12px;overflow-wrap:anywhere}
.big{font-size:22px;font-weight:600;margin:8px 0 16px;overflow-wrap:anywhere}
.panel{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:2px;background:var(--panel);padding:20px;max-width:640px}
.primary{padding:10px 18px;font-size:15px;cursor:pointer;margin-top:16px}
.welcome{max-width:720px}
.welcome h2{font-size:clamp(26px,3.2vw,34px);line-height:1.2;margin:6px 0 10px}
.lead{margin:0 0 14px;font-size:20px;line-height:1.5;font-weight:500;letter-spacing:-.005em;max-width:34em;text-wrap:pretty}
.body{margin:0 0 12px;font-size:16px;line-height:1.65;color:var(--muted);max-width:40em;text-wrap:pretty}
.body em{font-style:italic;color:var(--fg)}
.body strong{font-weight:600;color:var(--fg)}
.welcome .body:last-of-type{margin-bottom:32px}
.hood-h{margin-top:32px} .hood{margin:8px 0 0;padding-left:20px;max-width:40em;font-size:16px;line-height:1.6;color:var(--muted)}
.hood li{margin:6px 0} .hood strong{color:var(--fg);font-weight:600}
.writeup{max-width:720px;margin-bottom:20px} .writeup h2{margin-bottom:8px}
.writeup .lead{margin-bottom:18px} .writeup .eyebrow{margin-bottom:6px}
.dothis{margin:6px 0 4px;padding:18px 20px;background:var(--panel);border:1px solid var(--line-2);border-radius:6px}
.dothis ol{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:16px}
.dothis li{display:flex;gap:14px;align-items:flex-start;font-size:19px;line-height:1.45;font-weight:500}
.dothis li>div{flex:1;min-width:0}
.dothis .n{flex:none;width:32px;height:32px;display:grid;place-items:center;border-radius:50%;
font-family:var(--mono);font-size:15px;font-weight:600;background:var(--line);color:var(--fg)}
.dothis .runbox .run{font-size:16px;padding:14px 16px}
.dothis .copy{font-size:17px;padding:0 24px}
.runbox{display:flex;gap:10px;align-items:stretch;margin:14px 0 0}
.runbox .run{flex:1;margin:0}
.copy{flex:none;padding:0 18px;font-size:15px;font-weight:600;cursor:pointer}
.run{margin:14px 0 0;padding:12px 14px;font-family:var(--mono);font-size:14px;background:var(--panel);
border:1px solid var(--line-2);border-radius:2px;white-space:pre-wrap;overflow-wrap:anywhere;user-select:all}
.tryit{margin:14px 0 0;font-size:15px;color:var(--fg);font-weight:500}
.steps{list-style:none;margin:8px 0 0;padding:0;max-width:62ch}
.steps li{display:flex;gap:16px;align-items:baseline;padding:12px 0;border-top:1px solid var(--line)}
.steps li:last-child{border-bottom:1px solid var(--line)}
.steps .n{flex:none;width:2ch;font-family:var(--mono);font-size:13px;color:var(--muted-2)}
@media (max-width:720px){.wrap{grid-template-columns:1fr} nav{border-right:0;border-bottom:1px solid var(--line)}}
</style>
<header class="top"><div><div class="eyebrow">uv-html-llm cookbook &amp; lab</div><h1>LLM + HTML GUI Integration: Proof of Concept</h1></div>
<button id="theme" type="button">Light</button></header>
<div class="wrap"><nav aria-label="Tests"></nav>
<main id="main"><section class="welcome"><div class="eyebrow">uv-html-llm cookbook &amp; lab</div>
<h2>Welcome to the LLM + HTML GUI Integration Proof of Concept</h2>
<p class="lead">This page shows how your LLM chat can ask you a question here in your browser, instead of in plain chat text.</p>
<p class="body">A web page can use proper UI design (layout, images, examples) to give each question its context, because <em>a picture is worth a thousand words</em>. That makes it useful for <strong>teaching, training and integrated help</strong>.</p>
<p class="body">The tests on the left come in four groups: question types, rich content such as pictures, video and web pages, BMad, and starting a greenfield project.</p>
<div class="eyebrow">How it works</div>
<ol class="steps">
<li><span class="n">1</span><div>Pick a test on the left.</div></li>
<li><span class="n">2</span><div>Answer it in the page that opens here.</div></li>
<li class="key"><span class="n">3</span><div><strong>Then switch back to your LLM chat session yourself.</strong> This page can't do that for you.</div></li>
<li><span class="n">4</span><div>The chat shows your answer and asks "Go back to the test page?" If you say <strong>Yes</strong>, this page opens again automatically, ready for your next test.</div></li>
</ol>
<div class="eyebrow hood-h">Under the hood</div>
<ul class="hood">
<li>A <strong>Python script on GitHub</strong> builds this <strong>web page on your laptop</strong>.</li>
<li>The page <strong>talks to your LLM chat</strong> through <strong>localhost</strong>, a tiny web server on your own machine. Your clicks go back to the chat as plain text.</li>
<li><strong>No install, no cloud:</strong> one prompt and <strong>uv</strong>. In a company, the script can sit on an <strong>on-prem GitHub Enterprise</strong>.</li>
<li><strong>Fallback:</strong> if a locked-down laptop blocks localhost, the page copies a prompt for you to paste into the chat instead.</li>
</ul></section></main></div>
<script>
const TESTS=__TESTS__, TOKEN=__TOKEN__, CHOOSE=__CHOOSE__, REOPEN=__REOPEN__;
const nav=document.querySelector('nav'), main=document.getElementById('main');
// Done marks are shared between tabs; a fresh start (not a reopen) clears them.
let ticks={}; try{ if(!REOPEN) localStorage.removeItem('menu-ticks'); ticks=JSON.parse(localStorage.getItem('menu-ticks')||'{}'); }catch(e){}
let current=null, finished=false;
// The menu is an accordion: one band per group, all open at first. Open groups are remembered
// between tabs, so a reopened page keeps your place; a fresh start opens them all again.
const groups=new Map();
for (const t of TESTS) { const g=t.group||'Question types'; if(!groups.has(g)) groups.set(g,[]); groups.get(g).push(t); }
let open=[...groups.keys()];
try{ if(!REOPEN) localStorage.removeItem('menu-open'); open=JSON.parse(localStorage.getItem('menu-open')||'null')||open; }catch(e){}
function saveOpen(){ try{ localStorage.setItem('menu-open',JSON.stringify(open)); }catch(e){} }
function setOpen(g, on){ const sec=nav.querySelector('[data-group="'+CSS.escape(g)+'"]'); if(!sec) return;
  sec.classList.toggle('open',on); sec.firstChild.setAttribute('aria-expanded',on);
  open=open.filter(x=>x!==g); if(on) open.push(g); saveOpen(); }
for (const [g,list] of groups) {
  const sec=el('section','grp-sec'); sec.dataset.group=g;
  const h=el('button','grp'); h.type='button';
  h.append(el('span','arrow','▸'), el('span','gname',g), el('span','count',String(list.length)));
  h.onclick=()=>setOpen(g, !sec.classList.contains('open'));
  const items=el('div','items');
  for (const t of list) {
    const b=document.createElement('button'); b.type='button'; b.dataset.id=t.id;
    b.innerHTML='<span></span><span class="tick"></span>'; b.firstChild.textContent=t.name;
    if (ticks[t.id]) b.lastChild.textContent='done';
    b.onclick=()=>start(t); items.appendChild(b);
  }
  sec.append(h, items); nav.appendChild(sec);
  const on=open.includes(g); sec.classList.toggle('open',on); h.setAttribute('aria-expanded',on);
}
function head(t){
  if (!t.proves) return [el('h2',null,t.name), el('p','todo',t.todo)];
  const w=el('section','writeup');
  w.append(el('h2',null,t.name), el('p','lead',t.proves));
  if (t.how) w.append(el('div','eyebrow','How it works'), el('p','body',t.how));
  let runAt=w;
  if (t.steps.length) {
    const box=el('div','dothis'); box.append(el('div','eyebrow','Do this'));
    const ol=el('ol'); t.steps.forEach((x,k)=>{ const li=el('li'); li.append(el('span','n',String(k+1)), el('div',null,x));
      ol.append(li); if (k===0) runAt=li.lastChild; });
    box.append(ol); w.append(box);
  }
  if (t.run) {
    const box=el('div','runbox'), c=el('button','copy','Copy'); c.type='button';
    c.onclick=async()=>{ let ok=false;
      try{ await navigator.clipboard.writeText(t.run); ok=true; }catch(e){}
      if (!ok) { const r=document.createRange(); r.selectNodeContents(box.firstChild);
        const sel=getSelection(); sel.removeAllRanges(); sel.addRange(r); try{ ok=document.execCommand('copy'); }catch(e){} }
      c.textContent=ok?'Copied':'Press Cmd/Ctrl+C'; setTimeout(()=>c.textContent='Copy',2000); };
    box.append(el('pre','run',t.run), c); runAt.append(box);
  }
  if (!t.steps.length) w.append(el('p','tryit','Try it: '+t.todo));
  return [w];
}
function el(tag, cls, text){ const e=document.createElement(tag); if(cls)e.className=cls; if(text!=null)e.textContent=text; return e; }
async function start(t){
  if (finished) return;
  current=t;
  for (const b of nav.querySelectorAll('button[data-id]')) b.setAttribute('aria-current', b.dataset.id===t.id);
  setOpen(t.group||'Question types', true);
  main.replaceChildren(...head(t), el('p','todo','Starting…'));
  await fetch('/start/'+t.id,{method:'POST'});
  if (current!==t) return;
  const f=el('iframe'); f.title=t.name+' test page'; f.src='/test?'+Date.now();
  f.setAttribute('allow','clipboard-write; encrypted-media; picture-in-picture; fullscreen');
  f.onload=()=>{ try{ f.style.height=Math.max(480, f.contentDocument.documentElement.scrollHeight+24)+'px'; }catch(e){} };
  main.replaceChildren(...head(t), f, el('p','cmd',CHOOSE+' '+t.shown.replaceAll('__MENU__', location.origin)));
  if (t.copy) { const b=el('button','primary',"I've copied it"); b.type='button';
    b.onclick=()=>fetch('/copied',{method:'POST'}); main.appendChild(b); }
}
async function poll(){
  if (finished) return;
  let s; try{ s=await (await fetch('/state')).json(); }catch(e){ return; }
  if (s.status!=='done' || !current || s.id!==current.id) return;
  finished=true;
  ticks[current.id]=1; try{localStorage.setItem('menu-ticks',JSON.stringify(ticks))}catch(e){}
  nav.querySelector('[data-id="'+current.id+'"] .tick').textContent='done';
  for (const b of nav.querySelectorAll('button')) b.disabled=true;
  const p=el('div','panel');
  if (current.copy) p.append(el('div','eyebrow','Copy-prompt page'), el('div','big','Paste the copied prompt into your LLM chat session.'));
  else if (s.code===0) p.append(el('div','eyebrow','You chose'), el('div','big',s.answer));
  else p.append(el('div','eyebrow','Result'), el('div','big','Nothing came back: exit code '+s.code+' ('+s.meaning+').'));
  p.append(el('p',null,'Switch back to your LLM chat session to see this test run. It will ask if you want to come back; if you do, a new test page opens and this tab closes.'));
  main.replaceChildren(el('h2',null,current.name), p);
  // When a newer test page starts, this tab retires: it closes, or greys out if the browser won't allow that.
  const ping=async()=>{ try{ const r=await (await fetch('/ping')).text(); if(r!==TOKEN) retire(); }catch(e){} };
  const timer=setInterval(ping, 1000);
  document.addEventListener('visibilitychange', ()=>{ if (!document.hidden) ping(); });
  function retire(){
    clearInterval(timer); window.close();
    document.body.style.opacity='.45';
    main.replaceChildren(el('h2',null,'This test page is finished'),
      el('p','todo','A newer test page is open in another tab. You can close this one.'));
  }
}
setInterval(poll, 500);
const tb=document.getElementById('theme');
const setTheme=l=>{ document.documentElement.dataset.theme=l?'light':''; tb.textContent=l?'Dark':'Light';
  try{localStorage.setItem('menu-theme',l?'light':'dark')}catch(e){}
  const f=document.querySelector('iframe'); if(f&&f.contentDocument) f.contentDocument.documentElement.dataset.theme=l?'light':''; };
setTheme(document.documentElement.dataset.theme==='light');
tb.onclick=()=>setTheme(document.documentElement.dataset.theme!=='light');
</script></html>"""
SHELL = (SHELL.replace("__THEME__", THEME).replace("__REOPEN__", json.dumps(args.reopen)).replace("__TOKEN__", json.dumps(TOKEN)).replace("__CHOOSE__", json.dumps(CHOOSE))
         .replace("__TESTS__", json.dumps([{"id": t["id"], "name": t["name"], "todo": t["todo"], "copy": t.get("copy", False),
                                            "group": t.get("group", ""),
                                            "proves": t.get("proves", ""), "how": t.get("how", ""), "steps": t.get("steps", []), "run": t.get("run", ""), "shown": " ".join(shlex.quote(a) for a in t["args"])} for t in TESTS])))


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, code, body=b"", kind="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.partition("?")[0]
        if path == "/ping":
            self.reply(200, TOKEN.encode(), "text/plain")
        elif path == "/state":
            if state.get("status") == "done":
                delivered.set()
            self.reply(200, json.dumps(state).encode(), "application/json")
        elif path.startswith("/asset/") and Path(path).suffix in ASSET_TYPES and "/" not in path[7:]:
            name = path[7:]
            try:
                if name not in asset_cache:
                    asset_cache[name] = fetch("assets/" + name)
                self.reply(200, asset_cache[name], ASSET_TYPES[Path(path).suffix])
            except OSError:
                self.reply(404)
        elif path == "/flowchart":  # served from here, since GitHub serves HTML as plain text
            self.reply(200, flowchart.read_bytes())
        elif path == "/test":  # the real choose.py page, restyled
            if cur["copy_page"]:
                page = cur["copy_page"].read_text(encoding="utf-8")
            elif cur["port"]:
                page = urllib.request.urlopen(f"http://127.0.0.1:{cur['port']}/", timeout=10).read().decode()
            else:
                return self.reply(404)
            self.reply(200, page.replace("</style>", "</style>" + THEME, 1).encode())
        else:
            self.reply(200, SHELL.encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        path = self.path.strip("/")
        if path.startswith("start/") and path[6:] in BY_ID and state.get("status") != "done":
            run_test(BY_ID[path[6:]])
        elif path == "choose" and cur["port"]:  # the page's answer, passed on to choose.py
            req = urllib.request.Request(f"http://127.0.0.1:{cur['port']}/choose", data=body, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
        elif path == "copied" and cur["test"] and cur["test"].get("copy"):
            cur["proc"].wait()
            finish(cur["test"], "", cur["proc"].returncode)
        self.reply(204)

    def log_message(self, *a):
        pass  # keep stdout clean for the agent


try:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
except OSError:  # port busy: a free one (an old tab then can't see it and stays open)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
url = f"http://localhost:{server.server_address[1]}"
print(f"Opening the test page at {url}", file=sys.stderr)
webbrowser.open(url)  # a new tab; an older test page tab closes itself
timer = threading.Timer(args.timeout, server.shutdown)
timer.start()
server.serve_forever()
timer.cancel()
if cur["proc"] and cur["proc"].poll() is None:
    cur["proc"].terminate()

if state.get("status") != "done":
    print("Nobody picked a test on the test page. Stop.")
    sys.exit(0)
t = cur["test"]
command = CHOOSE + " " + " ".join(shlex.quote(a.replace("__MENU__", url)) for a in t["args"])
expected = state["code"] == {"fallback": 4, "timeout": 3}.get(t["id"], 0)
reopen = f"{MENU} --reopen" + (f" --port {args.port}" if args.port != 8764 else "")
answer = state["answer"] or ("(see the prompt you pasted)" if t.get("copy") else "(nothing)")
print(f"""The person ran a test on the test page. Show them this result exactly as laid out here, as Markdown:

### {'✅' if expected else '❌'} {t['name']}

| | |
|---|---|
| **Answer** | `{answer}` |
| **Exit code** | {state['code']} ({state['meaning']}){'' if expected else ', not what this test expects'} |

Command that ran:
```
{command}
```
""")
acting = bool(t.get("act")) and state["code"] == 0 and (state["answer"] == t["yes"] if t.get("yes") else True)
if acting:
    print(f"The person asked you to do this step now. {t['act'].replace('{answer}', answer)}\n")
if t.get("copy"):
    print("This test copies a prompt instead of returning one. If the person hasn't pasted it yet, ask them to, "
          "and show what they pasted under the table.\n")
print(f"""{'When that is done, ask' if acting else 'Then ask'} "Go back to the test page?" as a menu with two options:
  1. Yes, back to the test page
  2. No, I'm done
Use your multiple-choice question tool if you have one; otherwise show the two numbered options and wait for 1 or 2.
If they choose Yes, run this in the background and do what it prints:
{reopen}
A new test page tab opens in front, and the old one closes itself. If they choose No, stop.""")
