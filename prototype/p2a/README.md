# P2-A static prototype

This is a no-build visual demonstration of the human-confirmed Player 2 Agent flow. It uses no Riot card images, no rules engine, no model API, and no persistent browser storage.

Run it from the repository root:

```powershell
python -m http.server 4173 --directory prototype/p2a
```

Then open `http://127.0.0.1:4173/`.

The prototype produces the same `p2a-session.v1` event shape as `skill/scripts/p2a_session.py`. Use the Python validator on an exported file before treating it as an auditable fixture:

```powershell
python skill/scripts/p2a_session.py validate path/to/exported-session.json
```

The Agent connection is deliberately a manual bridge at this stage: copy the confirmed state into a Skill-enabled Agent and paste its proposal back into the prototype. This makes the product flow demonstrable without binding the public repository to a model provider or pretending that the UI itself can enumerate legal actions.
