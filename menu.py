# Usage: uv run --no-project menu.py [--port PORT] [--timeout SECONDS]
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
args = parser.parse_args()

here = Path(__file__).with_name("choose.py")
if here.exists():  # run from a clone: use the files beside this one
    choose_path = here
    CHOOSE = f"uv run --no-project {shlex.quote(str(here))}"
    MENU = f"uv run --no-project {shlex.quote(str(Path(__file__)))}"
else:  # run from GitHub: fetch choose.py once
    choose_path = Path(tempfile.gettempdir()) / "menu-choose.py"
    choose_path.write_bytes(urllib.request.urlopen(REPO + "choose.py", timeout=30).read())
    CHOOSE, MENU = f"uv run --no-project {REPO}choose.py", f"uv run --no-project {REPO}menu.py"

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
    dict(id="video", group="Rich content", name="YouTube video",
         todo="A YouTube video plays above the question. Play a few seconds, then pick an answer.",
         args=["--timeout", "3600", "--video", "Cf19iCXTzII", "--question", "What is this episode about?",
               "Running BMad in teams", "Installing Python", "Cooking pasta"]),
    dict(id="blog", group="Rich content", name="Blog post",
         todo="A blog post opens in a frame above the question. Scroll it, then pick an answer.",
         args=["--timeout", "3600", "--page",
               "https://blog.bmadcode.com/blog/your-ai-should-be-arguing-with-you-and-making-you-sweat/",
               "--question", "What does the post say your AI should do?",
               "Argue with you", "Agree with everything", "Stay quiet"]),
    dict(id="docs", group="Rich content", name="Docs page",
         todo="A BMad docs page opens in a frame above the question. Scroll it, then pick an answer.",
         args=["--timeout", "3600", "--page", "https://docs.bmad-method.org/plan/set-up-the-ticket-tree/",
               "--question", "What does this page help you set up?",
               "The ticket tree", "A web server", "A YouTube channel"]),
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
        p = subprocess.Popen([sys.executable, str(choose_path), *t["args"]], env=env, text=True,
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
nav .eyebrow{padding:0 10px 6px} nav .group{padding-top:20px}
nav button{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;padding:10px 12px;font-size:15px;
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
.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-fg);padding:10px 18px;font-size:15px;cursor:pointer;margin-top:16px}
.welcome{max-width:720px}
.welcome h2{font-size:clamp(26px,3.2vw,34px);line-height:1.2;margin:6px 0 10px}
.lead{margin:0 0 14px;font-size:20px;line-height:1.5;font-weight:500;letter-spacing:-.005em;max-width:34em;text-wrap:pretty}
.body{margin:0 0 12px;font-size:16px;line-height:1.65;color:var(--muted);max-width:40em;text-wrap:pretty}
.body em{font-style:italic;color:var(--fg)}
.body strong{font-weight:600;color:var(--fg)}
.welcome .body:last-of-type{margin-bottom:32px}
.steps{list-style:none;margin:8px 0 0;padding:0;max-width:62ch}
.steps li{display:flex;gap:16px;align-items:baseline;padding:12px 0;border-top:1px solid var(--line)}
.steps li:last-child{border-bottom:1px solid var(--line)}
.steps .n{flex:none;width:2ch;font-family:var(--mono);font-size:13px;color:var(--muted-2)}
@media (max-width:720px){.wrap{grid-template-columns:1fr} nav{border-right:0;border-bottom:1px solid var(--line)}}
</style>
<header class="top"><div><div class="eyebrow">uv-html-llm cookbook &amp; lab</div><h1>LLM + HTML GUI Integration: Proof of Concept</h1></div>
<button id="theme" type="button">Light</button></header>
<div class="wrap"><nav aria-label="Tests"><div class="eyebrow">Question types</div></nav>
<main id="main"><section class="welcome"><div class="eyebrow">uv-html-llm cookbook &amp; lab</div>
<h2>Welcome to the LLM + HTML GUI Integration Proof of Concept</h2>
<p class="lead">This page shows how your LLM chat can ask you a question here in your browser, instead of in plain chat text.</p>
<p class="body">A web page can use proper UI design (layout, images, examples) to give each question its context, because <em>a picture is worth a thousand words</em>. That makes it useful for <strong>teaching, training and integrated help</strong>.</p>
<p class="body">Each test on the left tries one kind of question: one choice, several choices, your own answer, and a few awkward cases.</p>
<div class="eyebrow">How it works</div>
<ol class="steps">
<li><span class="n">1</span><div>Pick a test on the left.</div></li>
<li><span class="n">2</span><div>Answer it in the page that opens here.</div></li>
<li class="key"><span class="n">3</span><div><strong>Then switch back to your LLM chat session yourself.</strong> This page can't do that for you.</div></li>
<li><span class="n">4</span><div>The chat shows your answer and asks "Go back to the test page?" If you say <strong>Yes</strong>, this page opens again automatically, ready for your next test.</div></li>
</ol></section></main></div>
<script>
const TESTS=__TESTS__, TOKEN=__TOKEN__, CHOOSE=__CHOOSE__, REOPEN=__REOPEN__;
const nav=document.querySelector('nav'), main=document.getElementById('main');
// Done marks are shared between tabs; a fresh start (not a reopen) clears them.
let ticks={}; try{ if(!REOPEN) localStorage.removeItem('menu-ticks'); ticks=JSON.parse(localStorage.getItem('menu-ticks')||'{}'); }catch(e){}
let current=null, finished=false;
let group='';
for (const t of TESTS) {
  if (t.group && t.group!==group) { group=t.group; nav.appendChild(el('div','eyebrow group',group)); }
  const b=document.createElement('button'); b.type='button'; b.dataset.id=t.id;
  b.innerHTML='<span></span><span class="tick"></span>'; b.firstChild.textContent=t.name;
  if (ticks[t.id]) b.lastChild.textContent='done';
  b.onclick=()=>start(t); nav.appendChild(b);
}
function el(tag, cls, text){ const e=document.createElement(tag); if(cls)e.className=cls; if(text!=null)e.textContent=text; return e; }
async function start(t){
  if (finished) return;
  current=t;
  for (const b of nav.querySelectorAll('button')) b.setAttribute('aria-current', b.dataset.id===t.id);
  main.replaceChildren(el('h2',null,t.name), el('p','todo',t.todo), el('p','todo','Starting…'));
  await fetch('/start/'+t.id,{method:'POST'});
  if (current!==t) return;
  const f=el('iframe'); f.title=t.name+' test page'; f.src='/test?'+Date.now();
  f.setAttribute('allow','clipboard-write; encrypted-media; picture-in-picture; fullscreen');
  f.onload=()=>{ try{ f.style.height=Math.max(480, f.contentDocument.documentElement.scrollHeight+24)+'px'; }catch(e){} };
  main.replaceChildren(el('h2',null,t.name), el('p','todo',t.todo), f, el('p','cmd',CHOOSE+' '+t.shown));
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
                                            "group": t.get("group", ""), "shown": " ".join(shlex.quote(a) for a in t["args"])} for t in TESTS])))


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
command = CHOOSE + " " + " ".join(shlex.quote(a) for a in t["args"])
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
if t.get("copy"):
    print("This test copies a prompt instead of returning one. If the person hasn't pasted it yet, ask them to, "
          "and show what they pasted under the table.\n")
print(f"""Then ask "Go back to the test page?" as a menu with two options:
  1. Yes, back to the test page
  2. No, I'm done
Use your multiple-choice question tool if you have one; otherwise show the two numbered options and wait for 1 or 2.
If they choose Yes, run this in the background and do what it prints:
{reopen}
A new test page tab opens in front, and the old one closes itself. If they choose No, stop.""")
