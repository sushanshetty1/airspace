# Demo video

**File:** attached to the [`demo-video` release](https://github.com/sushanshetty1/airspace/releases/tag/demo-video) (`airspace-demo.mp4`, 2:48, 1080p). Source: [`video/`](../video).

## Title

Airspace: air-traffic control for parallel coding agents, built on FalkorDB

## Description

Split a feature between two coding agents and each one passes its own tests. Merge them, and main is red: one agent changed a function the other was busy calling. With worktrees alone, 0 of 18 merges came out green.

Airspace keeps a live FalkorDB graph of how your code connects, and of the agents working on it: what each one claims, and every caller and test two hops out. Every edit is checked against that graph before it is written. The one that would collide is held, and the agent is told the new contract, so its retry lands clean.

In this video:
- The idea: one live code graph per repo, and the Cypher that clears or holds an edit
- Tower, the session view, replaying two real Claude Code sessions: overlapping airspaces, a held edit, the briefing, the retry
- Pre-flight on the real Flask repo: which tasks can run in parallel before any agent starts
- Memory: fixes written onto the code graph and told to the next agent that touches that code
- The playground, and workspaces for your own repo
- Results on Flask with real Claude Code agents: 9 of 9 merges green with Airspace, 5 of 9 when each agent is told the other's task, 0 of 9 with worktrees alone

Live: https://airspace.sushans.dev
Code: https://github.com/sushanshetty1/airspace

Built for the FalkorDB Hackathon 2026, Track 01 (Agents That Act on Connected Data) and Track 02 (Agent Memory and Coordination).

Chapters:
0:00 The problem
0:17 The idea: a live code graph
0:45 Tower, the session view
1:18 Pre-flight on Flask
1:39 Memory
1:52 Playground and workspaces
2:18 Results on Flask
2:41 Airspace
