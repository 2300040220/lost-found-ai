# Project Review Explanation

## Problem
Lost items are reported on notice boards or group chats. Finders and owners rarely meet because nobody compares the reports.

## Solution
A web app where both sides file structured reports. Four agents compare them automatically, tell both users the moment a likely
match exists, and guide a verified, admin-approved return.

## What "Edge AI" means in this project
Edge AI = running the AI where the data lives instead of sending it to a cloud service.
* **Local operations:** text cleaning, TF-IDF vectorising, cosine similarity (scikit-learn), image resizing, colour histograms and
  ORB keypoint matching (OpenCV), scoring, claim verification, and notification routing.
* **No external AI APIs, no model downloads, no paid services.** The app works with the internet disconnected (only the browser
  styling/client libraries come from CDNs and can be vendored locally).
* **Honest limit:** it runs on an ordinary Windows 11 PC. No dedicated edge hardware (Jetson, Raspberry Pi, NPU) is used, so
  we call it *local / edge-style* AI and do not claim hardware acceleration.

## Why "agentic"
Each agent has one responsibility, takes structured input and returns structured output. A coordinator decides the order and
reacts to results (no matches means no notification; a rejected claim reopens the match). Every hand-over is logged. The agents
are deterministic and explainable rather than autonomous LLMs, which suits a safety-sensitive task like returning property.

## The four agents
1. **Intake** validates (required fields, category list, dates not in the future, valid contact), cleans text, normalises colours,
   maps synonyms (mobile = phone), extracts keywords and builds the canonical `search_text`.
2. **Matching** compares a new item with every open item of the opposite type owned by other users. Score = TF-IDF cosine
   similarity of the text + a metadata score (category, colour, brand, date gap, location overlap) + an OpenCV image score.
   Pairs at or above 0.40 are stored, ranked, top 5 kept.
3. **Verification** asks the owner three or four questions, compares answers with the finder's private clue and public description,
   and stores an **advisory** score. It cannot approve anything.
4. **Notification** writes notification rows and pushes Socket.IO events to each user's private room, plus aggregate dashboard updates.

## How matching works (worked example)
Lost: "Black Samsung phone, cracked screen" vs Found: "Samsung mobile ... black Samsung phone with cracked screen near library".
Synonym mapping turns "mobile" into "phone"; TF-IDF cosine gives about 0.7+ for text; category/colour/brand/date/location give about 0.9 for
metadata; combined (no photos) = 0.6 x text + 0.4 x metadata, above the 0.40 threshold, so both users are notified.
With photos on both sides the image score contributes 30%.

## Image matching
Photos are resized to 256x256 and blurred. Colour signature: hue histogram for coloured pixels, brightness histogram for grey ones
(stable against noise), compared with Bhattacharyya distance. Shape/texture: ORB keypoints matched with a Hamming-distance matcher.
Image score = 0.6 colour + 0.4 ORB. **It is a suggestion only; it cannot prove ownership.**

## Security and privacy
Hashed passwords, sessions, CSRF tokens, role-based admin routes, strict upload validation, parameterised SQL, auto-escaped templates.
Contact details are released only after an admin approves a claim; the finder's private clue and the AI score are never shown to normal users.

## Results
24 automated tests pass, covering the 12 required scenarios. The two-browser walkthrough in the README demonstrates real-time delivery.

## Limitations and future work
TF-IDF is lexical (no deep semantics); classical CV is weak on plain objects; add sentence embeddings (local `sentence-transformers`)
and a CNN feature extractor (MobileNet via ONNX) to improve accuracy while staying local; add email/SMS alerts, rate limiting,
password reset, HTTPS deployment, and a mobile app.
