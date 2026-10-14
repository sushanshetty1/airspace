# Website: notes for the build

These are pre-event notes on content and direction only. The site itself is built after kickoff (October 15, 00:01 IST).

## Who it is for, and the one thing they should leave knowing

**Reader:** a developer who runs more than one coding agent, or a judge with five minutes.

**One thing:** two agents can each pass their tests and still break the build together. Airspace sees the collision in the code graph and holds the edit before it is written.

If a section does not help that land, it goes.

## Structure

One app in `web/`. The marketing site is at `/`. Tower (the live app) and its playground come later, at `/tower` and `/playground`, in the same visual language.

1. **Hero**
   - Eyebrow: *For developers who run more than one coding agent*
   - Heading: **Air-traffic control for coding agents.**
   - Sub: *Run four Claude Code sessions on one feature. Airspace keeps a live graph of how your code connects, and holds the edit that would break someone else's work before it is written.*
   - Buttons: **Open Tower** (live replay) and **Read the code** (GitHub).
   - Visual: the radar, animated in SVG, telling the whole story in one loop. Two cones grow on a code graph. They meet at `slugify`. A HOLD card slides in. A briefing goes out. The card turns to cleared. No video file.
2. **The problem: passes alone, fails together**
   - Three cards in sequence:
     1. Agent A changes `slugify(value, allow_unicode=False)` to `slugify(value, *, unicode=False)`. Tests: green.
     2. Agent B adds `slugify(post.title, True)`. Tests: green.
     3. Merge: red.
   - One line: *Git compares lines. It cannot see that B's new code depends on the function A is rewriting.*
   - Stat: 97% interference on constructed tasks, with an honest footnote and a link to the paper.
3. **How it works**, in three steps, each with a small live visual:
   1. *File a flight plan*: a cone draws itself.
   2. *Ask before every write*: the hook check, showing cleared, then hold.
   3. *Brief, don't surprise*: the briefing card with the new signature and the path.
4. **Tower**
   - Heading: *See every agent at once. Step in when you need to.*
   - A faithful mock of the Tower UI: radar, flight log, collision detail.
   - Actions as plain verbs: release, pause, hand off, message, approve.
   - Line: *Every hold in the terminal links to its collision in Tower.*
5. **Why a graph**
   - The four points from the README.
   - One real Cypher query, shown as code.
   - Line: *The decision is a graph query, not a model call.*
   - FalkorDB credited plainly.
6. **Proof**: the benchmark table and chart. Until measured, it says *Measuring now* with the method described. No invented numbers.
7. **Get started**: works with Claude Code, Codex and any MCP client. A three-line install snippet with a copy button.
8. **Footer**: built for the FalkorDB Hackathon 2026; GitHub link; Apache-2.0; AI-assistance disclosure.

## Visual direction

Taken from the README banner and diagrams, so the repo and site feel like one product.

- **Type:** Geist for text, Geist Mono for code, labels and data. Tight, confident headings; comfortable body at 17 to 18 px.
- **Colour:**
  - Near-black `#0c0e11` and white surfaces. Dark is the default, with a full light theme.
  - One accent, international orange `#ff5a1f`, used only for collisions, holds and the primary button.
  - Agent colours blue `#5aa2ff` and violet `#b18cff`, used only for agents.
- **Shape:** 24 px radius cards, 2 px hairline borders, soft shadows only on floating cards. An 8 px spacing grid. Content width around 1200 px.
- **Motion:** only where it explains something (the radar loop and the step visuals). Everything respects `prefers-reduced-motion` with a static end state.

## Rules (no AI feel)

- No em dashes or en dashes anywhere in copy.
- No "AI-powered", "supercharge", "seamless", "revolutionize", "unlock", "effortless", or similar words.
- No emoji, sparkle icons, glowing gradients, blurred blobs or glassmorphism.
- No generic three-card feature grid with icons. Every visual shows the real product or real code.
- Real names, real code, real numbers. If a number isn't measured yet, say so.
- Short sentences. Plain verbs. Say what it does, not how it feels.
- Every interactive element is keyboard reachable with a visible focus ring. Colour is never the only signal: holds also say HOLD.
- Fast: no heavy libraries on the marketing page. SVG and CSS first.

## Quality bar before it ships

- Checked at 390, 768, 1024 and 1440 px wide, in light and dark.
- No horizontal scroll, no text covered by the header, no layout shift on load.
- Lighthouse performance and accessibility at 95 or above.
- Every link works, and the GitHub link points at the public repo.
