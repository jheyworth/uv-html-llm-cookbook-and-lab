# LLM + HTML GUI Integration: Proof of Concept

`choose.py` lets an AI agent (Claude Code, Codex CLI and others) ask you a multiple-choice question on a web page, and get your answer back as plain text. It needs no cloud service, no API key and no packages: just [uv](https://docs.astral.sh/uv/).

## Try it from your LLM chat session

Create a new, empty project folder and open a new chat session in it, in an agent that can run commands (Claude Code, Codex CLI and others). The BMad tests install BMad into that folder. Then paste one of these two prompts.

**1. Demo (now):** runs straight from this private GitHub repo, with nothing cloned. Put a read-only GitHub token in place of `<TOKEN>`, once:

```text
Run this in the background and do what it prints: K='<TOKEN>'; uv run --no-project "https://x-access-token:$K@raw.githubusercontent.com/jheyworth/uv-html-llm-cookbook-and-lab/main/menu.py" --key "$K"
```

**2. Production (final):** the scripts come from the company's own Git, such as an on-prem GitHub Enterprise, with a `git clone`, using the company's own login and SSO. Many enterprise Git servers don't serve raw links, and none use `raw.githubusercontent.com`. Put the company's address in place of `<company git>`:

```text
Run "git clone https://<company git>/<path>/uv-html-llm-cookbook-and-lab", then run "uv run --no-project uv-html-llm-cookbook-and-lab/menu.py" in the background and do what it prints.
```

The raw-link route in prompt 1 is only for this demo.

A test page opens in your browser, with a list of tests on the left. Pick one and answer it, then switch back to your LLM chat session yourself. The chat shows your answer and asks if you want another test. If you say yes, the test page opens again automatically.

The tests come in four groups: **Question types** (the kinds of question choose.py can ask), **Rich content** (pictures, video and web pages above the question), **BMad** (install BMad, set it up, ask the PO agent for help, and customize her) and **Greenfield project** (ask BMad how to start, and an interactive flowchart of the workflow).

`menu.py` options: `--port` (default 8764), `--timeout` (seconds before the page stops, default 3600) and `--key` (the GitHub token in prompt 1, used for the script's own downloads; with it, the pictures come through the test page from your machine, because a browser can't send the token). Use a fine-grained token: read-only, this repo only, short expiry. From a clone (prompt 2), no key is needed: menu.py uses the files beside it.

## Files

- `choose.py`: the question page
- `menu.py`: the test page
- `demo.sh`: terminal demo
- `tests.sh`: automated checks
- `assets/`: pictures for the Rich content tests, and the greenfield flowchart page. menu.py serves the flowchart at `/flowchart`, because GitHub serves HTML files as plain text.

## Try the demo

Open a terminal in this folder, then copy and run:

```sh
./demo.sh
```

[demo.sh](demo.sh) takes about a minute. It runs three rounds with the real script: one choice, several choices plus your own answer, and the copy-prompt fallback. After each round it shows what an agent would receive.

## Run the tests

`./tests.sh` runs 53 automated checks in about 20 seconds, without opening the browser. `./tests.sh --clicks` then asks you to click through five pages and confirm each answer.

## How it works

1. The agent runs `uv run --no-project choose.py "Plan A" "Plan B"`.
2. The script starts a small web server on this computer only (`localhost`, port 8765) and opens the page in your browser.
3. You click an answer. The page sends it back to the script.
4. The script prints your answer and stops. The agent reads that printed line as the result of its command.

Status messages go to a separate stream (stderr), so the answer is always the last line the agent sees.

If the browser can't reach the script, for example on a locked-down work laptop, the script opens a **copy-prompt page** instead. Clicking an answer there copies a ready-made prompt, such as `My answer to "Which plan?": Plan B`, for you to paste into the chat.

## Options

| Option | What it does |
| --- | --- |
| `--question "Which plan?"` | Text shown above the buttons. Default: "Pick one". |
| `--multi` | Tick boxes and a Submit button; the answer is a list, such as `["Plan A", "Plan C"]`. |
| `--other` | Adds a free-text "Other..." box. |
| `--image SRC` | A picture above the question: an `https://` address, a local PNG, JPG, GIF, SVG or WebP file, or SVG text starting with `<svg`. Local files and SVG text are put into the page itself. |
| `--video ID` | Plays a YouTube video above the question, by its 11-character ID (privacy-enhanced youtube-nocookie.com player). |
| `--page URL` | Shows a web page above the question, in a sandboxed frame: an `https://` address, or `http://localhost:PORT/...` for a page served on this machine (the test page serves its flowchart this way). Sites that block framing will show as blank. |
| `--timeout 600` | Seconds to wait for an answer. Default: 300. |
| `--load-wait 30` | Seconds for the browser to load the page before the copy-prompt page also opens. Default: 30. |
| `--fallback` | Go straight to the copy-prompt page. |

Example with everything:

```sh
uv run --no-project choose.py --question "Which snacks?" --multi --other --timeout 600 "Biscuits" "Fruit" "Crisps"
```

An option that itself starts with `-` needs `--` before the options: `choose.py -- "-1" "+1"`.

## Exit codes

| Code | Meaning | What the agent should do |
| --- | --- | --- |
| 0 | Answered | Read the last line of output |
| 2 | Command typed wrong | Fix the command |
| 3 | Nobody answered in time | Ask again, or carry on without |
| 4 | Switched to the copy-prompt page | Wait for the person to paste their answer into the chat |

## Notes for agents

- The answer from the normal page has spaces after commas in a list; the pasted prompt has none. Both are valid JSON: parse the list, don't compare the text.
- Many agents stop a command after about 2 minutes. Run `choose.py` in the background, or with a longer command timeout.
- `BROWSER=true` stops the browser from opening, which is useful for automated tests.
- uv can run the script straight from GitHub: `uv run --no-project https://raw.githubusercontent.com/jheyworth/uv-html-llm-cookbook-and-lab/main/choose.py "A" "B"`. Tested on 18 Oct 2026.

## Limits

- The browser and the agent must be on the same computer. A cloud-based agent's `localhost` is the cloud machine, not yours.
- Work laptops may block uv or Python from running at all. The script can't detect that, because it never starts; the agent would have to write a copy-prompt page itself.
- Not yet tested under Codex CLI, Antigravity CLI or GitHub Copilot.
