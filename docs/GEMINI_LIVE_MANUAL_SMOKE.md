# Gemini Live — manual real-provider smoke checklist

## Purpose and boundary

This checklist verifies the real Gemini Live provider, microphone path, audio response, tool round-trip, turn completion and reconnect behavior. The automated CI suite uses deterministic fake provider/client sockets; it does **not** prove compatibility with Google's live service.

**Run this only on an isolated staging deployment.** The staging service must use a disposable SQLite database and its own Gemini credentials. Do not run this checklist against the production Chappie/Turso memory unless a separate explicit approval is given. A real-provider run consumes Gemini API quota.

## Preconditions

- [ ] A staging Render service is deployed from the candidate commit.
- [ ] `CHAPPIE_STORAGE_BACKEND=sqlite` points to a disposable staging database; no production Turso URL/token is configured.
- [ ] `GEMINI_API_KEY` and `CHAPPIE_API_TOKEN` are configured in the staging service's secret environment settings.
- [ ] Neither secret is present in source files, browser URLs, screenshots, shell history, or logs.
- [ ] The test account is the staging owner and the database contains no personal or production data.
- [ ] A short, unique test word is chosen (for example, `zorbital`); do not use personal or sensitive information.

## 1. Service readiness and ticket

- [ ] Open `/health`; expect `status: ok` and `gemini_configured: true`.
- [ ] Open `/ready`; expect HTTP 200, `status: ready`, and `database: connected`.
- [ ] Open Chappie's UI and start Gemini Live. The UI should request a short-lived, single-use ticket through `POST /api/live/ticket`.
- [ ] Confirm the WebSocket reaches `/ws/live?ticket=...` and the UI receives its connected state.
- [ ] Confirm Gemini sends setup completion. Never put the Gemini API key in the WebSocket URL.

## 2. Real microphone input and audio output

- [ ] Grant microphone permission in the browser.
- [ ] Speak one short sentence containing the chosen test word.
- [ ] Confirm the input transcription appears in the UI.
- [ ] Wait for the provider's turn-complete event before ending the turn.
- [ ] Confirm Chappie's response audio is audible and the transcript matches the response.
- [ ] Confirm the response obeys Chappie's learned-vocabulary gate; a word not yet permitted must not be spoken merely because Gemini generated it.

## 3. Shared brain and read-only tool round-trip

- [ ] Teach the test word through written Chat and confirm it appears in the staging vocabulary.
- [ ] Start a **new** Gemini Live session. Confirm its initial context includes the Chat-learned word.
- [ ] Ask for one action that uses a tool explicitly marked read-only in the current Live tool schema.
- [ ] Confirm the tool call is received, executed once, and its result is returned to Gemini and the UI.
- [ ] Do not test a tool that creates, deletes, resets, or modifies memories, goals, settings, or database records during this smoke test.

## 4. Live camera and visual-analysis provenance

- [ ] Grant camera permission in the staging browser and start the Live camera stream.
- [ ] Confirm the client sends camera frames to the same Live session; do not save image bytes in the memory database.
- [ ] While a recent frame is being sent, ask explicitly: "Que vois-tu ?" or "Décris ce que tu vois."
- [ ] Confirm Gemini Live returns its spoken/text response and the completed turn is recorded.
- [ ] Refresh the sensory-observation list and verify exactly one `gemini_live_visual_analysis` observation for the completed visual question.
- [ ] Verify its provenance includes the Live model, session ID, frame sequence, MIME type, question, and `gemini_live_output_transcription` channel.
- [ ] Verify `semantic_analysis_performed=true`, `human_review_required=true`, `semantic_understanding_confirmed=false`, `is_learned_fact=false`, `image_bytes_persisted=false`, and confidence remains 0 (uncalibrated).
- [ ] Confirm the post-turn shared-brain refresh contains the visual observation and provenance but not image bytes.
- [ ] With the camera still active, ask an ordinary greeting. Confirm no new `gemini_live_visual_analysis` observation is created for that non-visual question.
- [ ] Stop the camera, wait more than 15 seconds, then ask another visual question. Confirm no analysis is persisted from the stale frame.
- [ ] In the UI, select the visual observation and submit a concrete evidence description only after the word has reached the required imitation stage. Confirm the association is recorded without automatically promoting the word to understood/usable or creating a world fact.

## 5. Turn completion and persistence

- [ ] Complete one Live turn containing a second unique test word.
- [ ] Confirm the user transcript and assistant response appear once in conversation history.
- [ ] Confirm one completed Live journal event is recorded for that turn, not one per transcript fragment.
- [ ] Close the UI session, then reconnect using a newly issued ticket.
- [ ] Confirm the completed Live word is present in the new Live context and can be retrieved through written Chat.
- [ ] Confirm reconnect does not duplicate the prior conversation turn or learning event.

## 6. Interrupted turn must remain history-only

- [ ] Begin speaking a third unique word, then interrupt or close the Live session before turn completion.
- [ ] Confirm the partial transcript may remain in conversation history with interrupted provenance.
- [ ] Confirm the interrupted word is **not** added to confirmed vocabulary.
- [ ] Confirm the interrupted turn does not create a new mood event, affective snapshot, or confirmed audio sensory observation.
- [ ] Reconnect with a fresh ticket. Confirm the completed words remain available but the interrupted word is absent from the learned vocabulary/context.

## 7. Isolation, logs and cleanup

- [ ] Verify that a separate isolated test identity cannot see the staging owner's vocabulary or transcript.
- [ ] Review Render logs for setup, WebSocket, provider, and persistence errors.
- [ ] Verify no API key, bearer token, signed ticket, or sensitive transcript was logged.
- [ ] Record the staging commit SHA, browser/device, test time, and pass/fail results without recording secrets.
- [ ] Delete the disposable staging database and staging test credentials when the smoke test is complete.

## Expected result

All setup, microphone, provider audio, read-only tool, turn-complete, persistence, interruption and reconnect checks pass. If any check fails, preserve the staging logs with secrets redacted and do not promote the candidate to production.

## Important limitation

A passing fake-provider CI suite proves the application's deterministic bridge and persistence behavior against the test protocol only. Only this credential-protected staging checklist can verify real Gemini Live service compatibility. It must not be used as a reason to reset or experiment on production memory.
