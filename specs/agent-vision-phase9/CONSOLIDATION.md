# Phase 9 post-release consolidation

Release tag agent-vision-v0.3.0 remains at 5f0cdc0; deployed package and frozen acceptance contract unchanged. The completed feature worktree and merged feature branch were retired. Historical coordinator registration artifacts and dispatch bootstrap are removed from the active tree; they remain available at the release tag and in the local verified archive. The 24 ticket issue files under .scratch/agent-vision-phase9/issues remain tracked because the frozen TICKETS.md and ticket-manifest.json reference their exact paths. Do not edit frozen files to relocate them.

Local NB frozen archive: opencv_custom_recovery/_frozen/20261127-agent-vision-v0.3.0/. evidence.zip and evidence-manifest.json retain raw campaign/audit files, test receipts, original paths and deduplicated SHA-256 payloads. Use restore-evidence.py to extract a prefix into a NEW directory. Original audit report paths are historical. The retired local-clean-history refs are mapped to independently restored v0.2.0 release.bundle refs. The two released tags and earlier qualification milestone remain. Do not restore over production Store.

Production runtime and point-in-time rollback copy remain in releases/agent-vision-v0.3.0; v0.2.0 venv and existing frozen archive remain. No deployment, Store or Android input changes were made by consolidation.
