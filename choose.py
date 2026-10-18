# Usage: uv run choose.py [--question TEXT] [--timeout SECONDS] [--multi] [--other]
#                         [--image SRC] [--video YOUTUBE_ID] [--page HTTPS_URL]
#                         [--load-wait SECONDS] [--fallback] "Option A" "Option B" "Option C"
# Serves a page with one button per option (and optionally a picture, video or
# web page above the question), waits for a click,
# prints the chosen option to stdout, then exits.
#
# Exit codes:
#   0  answered; the answer is on stdout (a JSON list with --multi)
#   2  command typed wrong (argparse)
#   3  nobody answered within --timeout (default 300 s)
#   4  switched to the copy-prompt page: the person will paste their answer
#      into the chat instead. Happens when no local port can be opened, when
#      the browser has not loaded the page within --load-wait (default 30 s)
#      and nobody answers before the timeout, or with --fallback.
import argparse, base64, html, http.server, json, re, sys, tempfile, threading, webbrowser
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--timeout", type=float, default=300, help="seconds to wait (default 300)")
parser.add_argument("--question", default="Pick one", help="text shown above the buttons")
parser.add_argument("--multi", action="store_true", help="tick several, print them as a JSON list")
parser.add_argument("--other", action="store_true", help="add a free-text 'Other' box")
parser.add_argument("--load-wait", type=float, default=30,
                    help="seconds for the browser to load the page before the copy-prompt page also opens (default 30)")
parser.add_argument("--fallback", action="store_true", help="go straight to the copy-prompt page")
parser.add_argument("--image", help="picture above the question: an https:// (or http://localhost) address, a local file "
                    "(PNG, JPG, GIF, SVG, WebP) or SVG text starting with <svg")
parser.add_argument("--video", help="YouTube video ID to play above the question")
parser.add_argument("--page", help="https:// web page (or one served on this machine at http://localhost) "
                    "to show above the question, in a sandboxed frame")
parser.add_argument("options", nargs="*")
args = parser.parse_args()
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".svg": "image/svg+xml", ".webp": "image/webp"}


def data_uri(mime, data):
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


LOCAL_URL = re.compile(r"http://(localhost|127\.0\.0\.1)(:\d+)?/")  # a page or picture served on this machine


def make_media():
    # Local files and SVG text go into the page as data, so no extra request is needed.
    # Everything is shown as <img> or a sandboxed frame: nothing passed in can run on this page.
    parts = []
    if args.image:
        src = args.image.strip()
        if src.startswith("<svg"):
            src = data_uri("image/svg+xml", src.encode())
        elif not (src.startswith("https://") or LOCAL_URL.match(src)):
            path = Path(src).expanduser()
            if path.suffix.lower() not in TYPES or not path.is_file():
                parser.error(f"--image: no PNG, JPG, GIF, SVG or WebP file at {src}")
            src = data_uri(TYPES[path.suffix.lower()], path.read_bytes())
        parts.append(f'<img class="media" src="{html.escape(src)}" alt="">')
    if args.video:
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video):
            parser.error("--video: give the 11-character YouTube video ID, e.g. Cf19iCXTzII")
        parts.append(f'<iframe class="media video" src="https://www.youtube-nocookie.com/embed/{args.video}" '
                     'title="Video" allow="encrypted-media; picture-in-picture; fullscreen" '
                     'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>')
    if args.page:
        if not (args.page.startswith("https://") or LOCAL_URL.match(args.page)):
            parser.error("--page: give an https:// address, or http://localhost:PORT/... for a page on this machine")
        parts.append(f'<iframe class="media page" src="{html.escape(args.page)}" title="Web page" '
                     'sandbox="allow-scripts allow-same-origin" allow="clipboard-write"></iframe>')
    return "".join(parts)


MEDIA = make_media()
options = args.options or ["Yes", "No"]
choice = {}
loaded = threading.Event()
PORT = 8765


def make_page(copy_mode):
    if args.multi:
        buttons = "".join(
            f'<label><input type="checkbox" value="{html.escape(o)}" onchange="sync()"> {html.escape(o)}</label>'
            for o in options
        )
        if args.other:
            buttons += '<input id="other" placeholder="Other..." oninput="sync()" onkeydown="enter(event)">'
        buttons += f'<button id="go" onclick="send()" disabled>{"Copy prompt" if copy_mode else "Submit"}</button>'
    else:
        buttons = "".join(
            f'<button data-o="{html.escape(o)}" onclick="pick(this.dataset.o)">{html.escape(o)}</button>'
            for o in options
        )
        if args.other:
            buttons += ('<input id="other" placeholder="Other..." oninput="sync()" onkeydown="enter(event)">'
                        f'<button id="go" onclick="sendOther()" disabled>{"Copy prompt" if copy_mode else "Send"}</button>')
    note = "<p>Your choice is copied as a prompt. Paste it into your chat with the agent.</p>" if copy_mode else ""
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Choose</title>
<style>body{{font-family:sans-serif;max-width:{720 if MEDIA else 420}px;margin:40px auto;padding:0 16px}}
.media{{display:block;width:100%;margin:0 0 20px;border:0;border-radius:4px}}
img.media{{height:auto}} .video{{aspect-ratio:16/9}} .page{{height:560px;background:#fff}}
button{{display:block;width:100%;padding:14px;margin:10px 0;font-size:17px;cursor:pointer}}
label{{display:block;padding:12px;margin:8px 0;font-size:17px;border:1px solid #ccc;border-radius:6px;cursor:pointer}}
#other{{display:block;width:100%;box-sizing:border-box;padding:12px;margin:10px 0;font-size:17px}}
textarea{{width:100%;box-sizing:border-box;height:90px;font-size:15px}}</style>
{MEDIA}<h2>{html.escape(args.question)}</h2>{note}{buttons}<p id="msg"></p>
<script>
const COPY_MODE={json.dumps(copy_mode)}, QUESTION={json.dumps(args.question)};
async function deliver(body, shown){{
  if (!COPY_MODE) {{
    await fetch('/choose',{{method:'POST',body:body}});
    document.body.innerHTML='<h2></h2><p>You can close this tab.</p>';
    document.querySelector('h2').textContent='Sent: '+shown;
    return;
  }}
  const prompt='My answer to "'+QUESTION+'": '+body;
  document.body.innerHTML='<h2>Copied</h2><p>Paste it into your chat with the agent. If pasting gives nothing, copy it from here:</p><textarea readonly></textarea>';
  const box=document.querySelector('textarea'); box.value=prompt; box.select();
  let ok=false;
  try {{ await navigator.clipboard.writeText(prompt); ok=true; }} catch(e) {{}}
  if (!ok) {{ try {{ ok=document.execCommand('copy'); }} catch(e) {{}} }}
  if (!ok) document.querySelector('h2').textContent='Copy it from the box below';
}}
function pick(o){{ deliver(o, o); }}
function typed(){{ const e=document.getElementById('other'); return e ? e.value.trim() : ''; }}
function picked(){{
  const v=[...document.querySelectorAll('input:checked')].map(i=>i.value);
  if (typed()) v.push(typed());
  return v;
}}
function sync(){{ document.getElementById('go').disabled=picked().length===0; }}
function sendOther(){{ if (typed()) pick(typed()); }}
function enter(e){{ if (e.key==='Enter') document.getElementById('go').click(); }}
function send(){{ const v=picked(); deliver(JSON.stringify(v), v.join(', ')); }}
</script>"""


def open_fallback():
    path = Path(tempfile.gettempdir()) / "choose-copy-prompt.html"
    path.write_text(make_page(copy_mode=True), encoding="utf-8")
    print(f"Copy-prompt page: {path}", file=sys.stderr)
    webbrowser.open(path.as_uri())


def fallback_exit(reason):
    print(reason, file=sys.stderr)
    open_fallback()
    sys.exit(4)


PAGE = make_page(copy_mode=False)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        loaded.set()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        choice["value"] = self.rfile.read(n).decode()
        self.send_response(204)
        self.end_headers()
        threading.Thread(target=server.shutdown).start()

    def log_message(self, *args):
        pass  # keep stdout clean for the agent


if args.fallback:
    fallback_exit("Using the copy-prompt page (--fallback).")
try:
    try:
        server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:  # port busy (e.g. another copy waiting): let the OS pick a free one
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
except OSError as e:  # no local port allowed at all
    fallback_exit(f"Could not open a local port ({e}).")
url = f"http://localhost:{server.server_address[1]}"
print(f"Open {url} and pick an option...", file=sys.stderr)
webbrowser.open(url)

fallback_shown = threading.Event()


def watch_load():
    # The browser may be blocked from localhost: if the page is never fetched,
    # also open the copy-prompt page, but keep serving in case it loads late.
    if not loaded.wait(args.load_wait) and "value" not in choice:
        print(f"The page was not loaded within {args.load_wait:g} seconds.", file=sys.stderr)
        open_fallback()
        fallback_shown.set()


threading.Thread(target=watch_load, daemon=True).start()
timer = threading.Timer(args.timeout, server.shutdown)
timer.start()
server.serve_forever()
timer.cancel()
if "value" not in choice:
    if fallback_shown.is_set():
        print("No answer through the page; expect it pasted into the chat.", file=sys.stderr)
        sys.exit(4)
    print(f"No choice made within {args.timeout:g} seconds.", file=sys.stderr)
    sys.exit(3)
if args.multi:
    print(json.dumps(json.loads(choice["value"]), ensure_ascii=False))
else:
    print(choice["value"])
