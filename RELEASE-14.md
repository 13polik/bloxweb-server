# BloxWeb 14

## Implemented

- Distinct Glock, USP-S, Desert Eagle, MP5, AK-47, M4A1 and AWP view models, with a supporting left hand on the four two-handed weapons.
- Enemy gunfire audio in solo and online play, with stereo position, distance attenuation and the existing sound setting.
- Four shared arena definitions. Server-controlled online voting, one current vote per player, 15-second deadline, random tie-break and fresh voting after a completed match restart.
- CS2-inspired original menu, with map diagrams, arsenal and settings. Existing low-poly identity and base game rules retained.
- Real model-backed Studio generation using a compact, validated rectangle/object representation. Separate explicitly non-AI procedural generator; neither executes generated code.
- Region rotation with undo, mirrored project copies, project confirmation before importing AI output.
- Persistent publication, owner-only update/withdrawal, catalog discovery, shared playable URLs and access from a separate account.

## Verification

- Five isolated backend test cases pass, covering project validation, compact AI conversion, publication authorization and updates, withdrawal, explicit AI unavailability, voting, timeout, collision selection and match restart.
- All 13 inline JavaScript blocks parse; Python compiles; Git whitespace checks pass.
- Browser: desktop 1440 × 960 and mobile 375 × 812, without horizontal overflow in the new menus and Studio.
- Browser: two independent accounts both voted Citadel and entered an unpaused shared match with five server-controlled bots.
- Browser: one account published a project, another launched it from the shared catalog; the owner then withdrew the test publication.
- Browser: actual AI response produced “Leśna Ścieżka”, accepted as a new local project. Procedural generation, rotation and undo were also exercised.
- Browser: all seven weapon models verified, including one-handed versus two-handed state; AK-47 and AWP screenshots inspected. Fire/reload exercised; enemy sound events observed.
- Browser: simultaneous mobile joystick/fire contact consumed four rounds without console errors. Avatar rotation, friends/messages/settings navigation, Castle Defense launch and football launch checked.
- Fixed issues discovered during QA: SDK version-header incompatibility; fragile AI array counting replaced with compact geometry; multiplayer phase reference; community recent-history startup race; disabled pause button after Studio retry.

## Deployment status

This release is prepared separately from production. Before deploying to the existing Render service:

- Confirm the Render workspace/service and publication scope.
- Read the current PostgreSQL schema, then apply the additive `migrations/014_studio.sql` as schema owner.
- Configure the production AI provider key and supported model, or leave AI explicitly unavailable while retaining the non-AI generator.
- Deploy code only after migration and repeat the shared-account flows on the live URL.

Temporary preview credentials are not copied into the repository or production. Studio currently creates bounded, single-player 2D platformers, not arbitrary game engines or multiplayer games. Static preview source is built from `public/index.html`, with its backend URL changed to the sandbox proxy, browser storage replaced with memory and native fullscreen replaced with the existing virtual fullscreen fallback. Export draft projects before closing the preview; Render keeps the normal browser storage behavior.
