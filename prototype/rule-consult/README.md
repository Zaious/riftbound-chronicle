# Rule Consult static prototype

This no-build interface demonstrates a cited, unofficial rules consultation. It keeps confirmed facts, assumptions, source locators, analysis, confidence, and escalation separate, then exports `rule-consultation.v1` JSON.

Open `index.html` directly, or serve the folder with any static file server. The model connection is a manual bridge: copy the structured research brief into a Skill-enabled Agent and enter the verified result back into the interface.

Validate an exported artifact with:

```powershell
python skill/scripts/rule_consult.py validate path/to/consultation.json
```

The interface has no network/model call, browser persistence, official-ruling claim, or game-state write.
