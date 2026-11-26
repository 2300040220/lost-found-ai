# PPT Presentation Content (14 slides)

**Slide 1: Title.** Design and Development of Agentic Edge AI Based Real-Time Item Lost-Found System. Your name, guide, department, year.

**Slide 2: Problem.** Lost items are scattered across notice boards and chats. No automatic comparison. Slow, manual, insecure handover of personal belongings.

**Slide 3: Objectives.** Report lost/found items; AI finds matches (text + image); real-time alerts; verified, admin-approved return; run locally, free, open source.

**Slide 4: Technology stack.** HTML/CSS/JS + Bootstrap 5 | Flask + Flask-SocketIO | SQLite | scikit-learn (TF-IDF, cosine) | OpenCV | NumPy | Windows 11 + VS Code.

**Slide 5: Architecture.** Show the architecture diagram from `docs/ARCHITECTURE.md` (browser, Flask, coordinator + 4 agents, SQLite, uploads, Socket.IO).

**Slide 6: What is Edge AI here.** AI runs on the local computer; no cloud AI or paid APIs; data stays on the machine. Honest note: ordinary PC, no dedicated edge hardware.

**Slide 7: The four agents.** Intake (validate + structure), Matching (score + rank), Verification (advisory ownership check), Notification (live alerts). Coordinator connects them and logs every step.

**Slide 8: Agent workflow.** Show the sequence diagram: report > intake > save > match > notify > live dashboard.

**Slide 9: Matching algorithm.** TF-IDF + cosine on text; metadata (category, colour, brand, date, location); OpenCV colour + ORB for images; final = 0.45 text + 0.25 details + 0.30 image; threshold 0.40.

**Slide 10: Claim and return workflow.** Owner claims > questions > advisory score > admin approves/rejects > items returned > contacts released > stats update live. "AI never declares ownership."

**Slide 11: Database design.** Show ER diagram: users, admin, lost_items, found_items, matches, claims, notifications, agent_logs.

**Slide 12: Security and privacy.** Hashing, sessions, RBAC, CSRF, upload validation, contact released only after approval, per-user real-time rooms.

**Slide 13: Demo and testing.** Live two-browser demo. 24 automated tests across 12 scenarios; table of results from `docs/TESTING.md`.

**Slide 14: Conclusion and future work.** Working real-time local AI system. Future: sentence embeddings, CNN features, email/SMS, mobile app, HTTPS deployment. Thank you / questions.

Demo script (3 minutes): two browsers, report lost, report found with a photo, show both toasts and counters, claim, admin approve, show contacts released and Admin > Overview agent log.
